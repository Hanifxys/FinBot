import re
import os
import gc
import tempfile
import shutil
import subprocess
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

class OCRProcessor:
    def __init__(self):
        self.enabled = True
        self._reader = None
        self.engine = (os.getenv("OCR_ENGINE", "auto") or "auto").lower()
        if self.engine == "auto":
            self.engine = self._auto_engine()

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
            max_dim_key = "OCR_MAX_DIM_LOW_MEM" if low_mem else "OCR_MAX_DIM"
            quality_key = "OCR_JPEG_QUALITY_LOW_MEM" if low_mem else "OCR_JPEG_QUALITY"
            max_dim_default = "1024" if low_mem else "1280"
            quality_default = "65" if low_mem else "75"

            max_dim = int(os.getenv(max_dim_key, max_dim_default))
            jpeg_quality = int(os.getenv(quality_key, quality_default))

            prepared_path, should_cleanup = self._prepare_image(image_path, max_dim=max_dim, jpeg_quality=jpeg_quality)

            top_path, top_cleanup = self._crop_image(prepared_path, region="top")
            bottom_path, bottom_cleanup = self._crop_image(prepared_path, region="bottom")

            try:
                top_text, first_line = self._extract_text(top_path, low_mem=low_mem)
                bottom_text, _ = self._extract_text(bottom_path, low_mem=low_mem)
                full_text = (top_text + "\n" + bottom_text).strip()
            finally:
                for pth, cleanup in [(top_path, top_cleanup), (bottom_path, bottom_cleanup)]:
                    if cleanup and os.path.exists(pth):
                        os.remove(pth)
                if should_cleanup and os.path.exists(prepared_path):
                    os.remove(prepared_path)

            if not full_text:
                return None

            merchant = self._extract_merchant(first_line, full_text)
            amount = self._extract_amount(full_text)
            date_str = self._extract_date(full_text)

            result = {
                "amount": amount,
                "merchant": merchant,
                "date": date_str
            }
            return result
        except Exception as e:
            logger.error(f"OCR Processing Error: {e}")
            return None
        finally:
            gc.collect()

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
