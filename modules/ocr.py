import re
import os
import gc
import tempfile
import shutil
import subprocess
import logging
from typing import Tuple, Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class OCRProcessor:
    def __init__(self):
        self.enabled = True
        self._reader = None
        self.engine = (os.getenv("OCR_ENGINE", "auto") or "auto").lower()
        if self.engine == "auto":
            self.engine = self._auto_engine()
        
        # Advanced patterns for receipt fields
        self.patterns = {
            "total": [
                r'(?:total|bayar|jumlah|amount|grand total|nett|total bayar|harga|total tagihan|total due|sum|balance)[^\d]*([\d\.,]{3,})',
                r'[\d\.,]{4,}' # Fallback for large numbers
            ],
            "tax": [
                r'(?:tax|pajak|ppn|vat|gst|service charge|biaya layanan|service)[^\d]*([\d\.,]+)',
            ],
            "discount": [
                r'(?:disc|discount|potongan|hemat|promo|save|diskon|kurang)[^\d]*([\d\.,]+)',
            ],
            "payment_method": {
                "CASH": [r'cash', r'tunai', r'kembali', r'kembalian'],
                "QRIS": [r'qris', r'shopeepay', r'gopay', r'ovo', r'dana', r'linkaja'],
                "CARD": [r'card', r'debit', r'kredit', r'credit', r'visa', r'mastercard', r'bca', r'mandiri', r'bni', r'bri'],
                "TRANSFER": [r'transfer', r'va', r'virtual account']
            }
        }

    def _auto_engine(self) -> str:
        try:
            import psutil
            total = int(psutil.virtual_memory().total)
            if total <= 900 * 1024 * 1024:
                return "tesseract"
        except Exception:
            pass
        return "easyocr"

    @property
    def reader(self):
        if self.engine != "easyocr":
            return None
        if self._reader is None and self.enabled:
            try:
                import easyocr
                self._reader = easyocr.Reader(['id', 'en'], gpu=False, download_enabled=False)
            except Exception as e:
                logger.warning(f"OCR Reader Warning: {e}")
                self._reader = None
        return self._reader

    def process_receipt(self, image_path, low_mem: bool = False):
        if not self.enabled:
            return None
        
        try:
            # 1. Advanced Preprocessing
            prepared_path, should_cleanup = self._prepare_image_advanced(image_path, low_mem=low_mem)

            # 2. Hybrid Extraction (Full Image + Regions)
            # We use full image for better context now that we have advanced preprocessing
            full_text, first_line = self._extract_text(prepared_path, low_mem=low_mem)
            
            # Optional: Fallback to regions if full image text is sparse
            if len(full_text.split()) < 5:
                top_path, top_cleanup = self._crop_image(prepared_path, region="top")
                bottom_path, bottom_cleanup = self._crop_image(prepared_path, region="bottom")
                try:
                    top_text, _ = self._extract_text(top_path, low_mem=low_mem)
                    bottom_text, _ = self._extract_text(bottom_path, low_mem=low_mem)
                    full_text = (top_text + "\n" + full_text + "\n" + bottom_text).strip()
                finally:
                    for pth, cleanup in [(top_path, top_cleanup), (bottom_path, bottom_cleanup)]:
                        if cleanup and os.path.exists(pth): os.remove(pth)

            if should_cleanup and os.path.exists(prepared_path):
                os.remove(prepared_path)

            if not full_text:
                return None

            # 3. Intelligent Entity Extraction
            merchant = self._extract_merchant(first_line, full_text)
            amount = self._extract_amount(full_text)
            tax = self._extract_field(full_text, "tax")
            discount = self._extract_field(full_text, "discount")
            payment_method = self._extract_payment_method(full_text)
            date_str = self._extract_date(full_text)
            items = self._extract_items(full_text)

            # 4. Post-processing Logic & Validation
            # Arithmetic Validation: Total should roughly be Subtotal + Tax - Discount
            validated_amount = self._validate_arithmetic(amount, tax, discount, items)

            result = {
                "amount": validated_amount,
                "tax": tax,
                "discount": discount,
                "merchant": merchant,
                "date": date_str,
                "payment_method": payment_method,
                "items": items,
                "raw_text_length": len(full_text)
            }
            
            # 5. LLM Fallback for High Complexity (if Groq enabled)
            if self.enabled and os.getenv("GROQ_API_KEY"):
                try:
                    from core import premium_ai
                    # Only call LLM if confidence is low (e.g. amount is 0 or very few items)
                    if validated_amount == 0 or not items:
                        llm_result = asyncio.run(premium_ai.process_interaction(0, f"Extract receipt data from this text: {full_text[:2000]}", "System"))
                        if llm_result and llm_result.structured_data:
                            result.update(llm_result.structured_data)
                except Exception:
                    pass

            return result
        except Exception as e:
            logger.error(f"OCR Processing Error: {e}")
            return None
        finally:
            gc.collect()

    def _prepare_image_advanced(self, image_path: str, low_mem: bool = False) -> Tuple[str, bool]:
        """Advanced Preprocessing: Denoising, Contrast, and Thresholding."""
        try:
            import cv2
            img = cv2.imread(image_path)
            if img is None: return image_path, False

            # 1. Resize if too large
            h, w = img.shape[:2]
            max_dim = 1280 if not low_mem else 1024
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

            # 2. Grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 3. Denoising
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

            # 4. Contrast Enhancement (CLAHE)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            contrast = clahe.apply(denoised)

            # 5. Adaptive Thresholding for Binarization
            binary = cv2.adaptiveThreshold(contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

            # 6. Deskewing (Skew Correction)
            coords = np.column_stack(np.where(binary > 0))
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45: angle = -(90 + angle)
            else: angle = -angle
            
            (h, w) = binary.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

            fd, out_path = tempfile.mkstemp(prefix="ocr_adv_", suffix=".jpg")
            os.close(fd)
            cv2.imwrite(out_path, rotated)
            return out_path, True
        except Exception as e:
            logger.warning(f"Advanced Preprocessing Failed: {e}. Using basic.")
            return self._prepare_image(image_path)

    def _extract_field(self, text: str, field_type: str) -> float:
        patterns = self.patterns.get(field_type, [])
        for pattern in patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                return self._clean_amount(matches[-1])
        return 0.0

    def _extract_payment_method(self, text: str) -> str:
        text = text.lower()
        for method, patterns in self.patterns["payment_method"].items():
            if any(re.search(p, text) for p in patterns):
                return method
        return "UNKNOWN"

    def _extract_items(self, text: str) -> List[Dict[str, Any]]:
        """Heuristic item extraction based on lines with prices."""
        items = []
        lines = text.splitlines()
        # Pattern for item line: text followed by price
        # e.g. "IMODIUM 2MG 1S 9300"
        item_pattern = re.compile(r'(.+?)\s+([\d\.,]{3,})$')
        
        for line in lines:
            line = line.strip()
            if len(line) < 5: continue
            
            match = item_pattern.search(line)
            if match:
                name = match.group(1).strip()
                price_str = match.group(2)
                price = self._clean_amount(price_str)
                
                # Filter out noise lines that match pattern (like "TOTAL 173000")
                if price > 0 and not any(kw in name.lower() for kw in ["total", "bayar", "jumlah", "subtotal", "tax", "ppn"]):
                    items.append({"name": name, "price": price})
        
        return items

    def _validate_arithmetic(self, total: float, tax: float, discount: float, items: List[Dict]) -> float:
        """Validates total against sum of items, tax, and discount."""
        item_sum = sum(item["price"] for item in items)
        
        # If total is 0 but we have items, use item sum
        if total == 0 and item_sum > 0:
            return item_sum + tax - discount
            
        # If total exists, check if it matches roughly
        calculated = item_sum + tax - discount
        if total > 0 and calculated > 0:
            # Allow 5% variance for rounding or missed items
            if abs(total - calculated) / max(total, 1) < 0.05:
                return total
            # If large discrepancy, trust the 'TOTAL' label if it exists, else use calculation
            return total
            
        return total

    def _extract_text(self, image_path: str, low_mem: bool = False):
        if self.engine == "easyocr":
            reader = self.reader
            if reader is not None:
                try:
                    import torch
                    torch.set_num_threads(1)
                except Exception:
                    pass

                texts = reader.readtext(image_path, detail=0, batch_size=1, workers=0)
                full_text = " ".join([t for t in texts if isinstance(t, str)]).strip()
                first_line = ""
                for t in texts:
                    if isinstance(t, str) and t.strip():
                        first_line = t.strip()
                        break
                return full_text, first_line

            self.engine = "tesseract"

        return self._tesseract_ocr(image_path, low_mem=low_mem)

    def _crop_image(self, image_path: str, region: str) -> Tuple[str, bool]:
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                if w <= 0 or h <= 0:
                    return image_path, False

                if region == "top":
                    y0 = 0
                    y1 = int(h * 0.30)
                else:
                    y0 = int(h * 0.55)
                    y1 = h

                y0 = max(0, min(y0, h - 1))
                y1 = max(y0 + 1, min(y1, h))
                cropped = img.crop((0, y0, w, y1))

                fd, out_path = tempfile.mkstemp(prefix=f"ocr_{region}_", suffix=".jpg")
                os.close(fd)
                cropped.save(out_path, format="JPEG", quality=70, optimize=True)
                return out_path, True
        except Exception:
            return image_path, False

    def _tesseract_ocr(self, image_path: str, low_mem: bool = False):
        if shutil.which("tesseract") is None:
            return "", ""

        lang = os.getenv("OCR_TESS_LANG", "ind+eng")
        psm_key = "OCR_TESS_PSM_LOW_MEM" if low_mem else "OCR_TESS_PSM"
        timeout_key = "OCR_TIMEOUT_SECONDS_LOW_MEM" if low_mem else "OCR_TIMEOUT_SECONDS"
        psm = str(os.getenv(psm_key, "6"))
        timeout_s = int(os.getenv(timeout_key, "45" if low_mem else "60"))

        args = ["tesseract", image_path, "stdout", "-l", lang, "--oem", "1", "--psm", psm]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
            text = (proc.stdout or "").replace("\x0c", " ").strip()
            first_line = ""
            for line in text.splitlines():
                if line.strip():
                    first_line = line.strip()
                    break
            return text, first_line
        except Exception:
            return "", ""

    def _extract_merchant(self, first_line: str, full_text: str) -> str:
        merchant = (first_line or "").strip()
        if not merchant:
            for line in full_text.splitlines():
                if line.strip():
                    merchant = line.strip()
                    break
        merchant = merchant or "Transaksi"
        noise = {"alamat", "telp", "tgl", "cashier", "nomor", "no:", "table"}
        if merchant.lower() in noise:
            return "Transaksi"
        return merchant[:64]

    def _extract_amount(self, full_text: str) -> float:
        amount_patterns = [
            r'(?:total|bayar|jumlah|amount|grand total|nett|total bayar|harga)[^\d]*([\d\.,]+)',
            r'[\d\.,]+'
        ]

        total_matches = re.findall(amount_patterns[0], full_text.lower())
        amount = 0.0
        if total_matches:
            amount = self._clean_amount(total_matches[-1])

        if amount <= 100:
            all_numbers = re.findall(r'(\d+[\d\.,]*)', full_text)
            cleaned_numbers = []
            for num in all_numbers:
                val = self._clean_amount(num)
                if val > 100:
                    cleaned_numbers.append(val)
            if cleaned_numbers:
                amount = max(cleaned_numbers)

        return amount

    def _extract_date(self, full_text: str):
        date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})|(\d{4}[/-]\d{2}[/-]\d{2})', full_text)
        if date_match:
            return date_match.group(0)
        return None

    def _prepare_image(self, image_path: str, max_dim: int = 1280, jpeg_quality: int = 75):

        try:
            from PIL import Image
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                if max(w, h) <= max_dim:
                    return image_path, False

                img.thumbnail((max_dim, max_dim))
                fd, out_path = tempfile.mkstemp(prefix="ocr_", suffix=".jpg")
                os.close(fd)
                img.save(out_path, format="JPEG", quality=jpeg_quality, optimize=True)
                return out_path, True
        except Exception:
            return image_path, False

    def _clean_amount(self, amount_str):
        # 1. Clean common noise but keep digits, comma and dot
        cleaned = re.sub(r'[^\d,\.]', '', amount_str)
        
        # 2. Heuristic for Indonesian format (dot=thousand, comma=decimal)
        if ',' in cleaned and '.' in cleaned:
            # Both separators present: e.g., 1.250.000,00 or 1,250,000.00
            if cleaned.find('.') < cleaned.find(','):
                # dot is thousand, comma is decimal
                val_str = cleaned.replace('.', '').replace(',', '.')
            else:
                # comma is thousand, dot is decimal
                val_str = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Only comma present
            parts = cleaned.split(',')
            if len(parts[-1]) == 3:
                # Likely thousand separator: 1,250,000
                val_str = cleaned.replace(',', '')
            else:
                # Likely decimal: 50,00
                val_str = cleaned.replace(',', '.')
        elif '.' in cleaned:
            # Only dot present
            parts = cleaned.split('.')
            if len(parts[-1]) == 3:
                # Likely thousand: 50.000
                val_str = cleaned.replace('.', '')
            else:
                # Likely decimal: 50.00
                val_str = cleaned
        else:
            val_str = cleaned

        try:
            return float(val_str)
        except ValueError:
            # Fallback: just digits, but try to handle trailing zeros if they look like decimals
            digits_only = re.sub(r'[^\d]', '', amount_str)
            if digits_only.endswith('00') and len(digits_only) > 4:
                return float(digits_only[:-2])
            try:
                return float(digits_only)
            except:
                return 0.0

async def extract_text_from_image(image_path: str) -> str:
    """
    Extract raw text from an image for general AI processing.
    """
    ocr = OCRProcessor()
    import asyncio
    
    loop = asyncio.get_running_loop()
    
    def _run_ocr():
        try:
            full_text, _ = ocr._extract_text(image_path)
            return full_text
        except Exception as e:
            return f"Error: {e}"

    return await loop.run_in_executor(None, _run_ocr)

def extract_text_from_url(url: str) -> str:
    return ""
