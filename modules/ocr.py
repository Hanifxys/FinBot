import re
import os
import gc
import tempfile

class OCRProcessor:
    def __init__(self):
        self.enabled = True
        self._reader = None

    @property
    def reader(self):
        """Lazy load the reader to save memory on startup"""
        if self._reader is None and self.enabled:
            try:
                import easyocr
                # Disable downloading inside the instance to prevent OOM
                # We pre-downloaded models in Dockerfile
                self._reader = easyocr.Reader(['id', 'en'], gpu=False, download_enabled=False)
                print("OCR Reader initialized (CPU mode)")
            except Exception as e:
                print(f"OCR Reader Warning: {e}")
                self._reader = None
        return self._reader

    def process_receipt(self, image_path):
        reader = self.reader
        if not reader:
            return None
        
        try:
            try:
                import torch
                torch.set_num_threads(1)
            except Exception:
                pass

            prepared_path, should_cleanup = self._prepare_image(image_path)
            try:
                results = reader.readtext(prepared_path, detail=0, batch_size=1, workers=0)
            finally:
                if should_cleanup and os.path.exists(prepared_path):
                    os.remove(prepared_path)

            full_text = " ".join([t for t in results if isinstance(t, str)])
            
            # 1. Extract Merchant Name (Usually the first few lines)
            merchant = "Transaksi"
            if len(results) > 0:
                merchant = results[0].strip() if isinstance(results[0], str) else "Transaksi"
                # Simple heuristic: if merchant looks like common noise, skip
                if merchant.lower() in ["alamat", "telp", "tgl", "cashier", "nomor", "no:"]:
                    merchant = "Transaksi"

            # 2. Extract Amount
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
                    
            # 3. Extract Date
            date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})|(\d{4}[/-]\d{2}[/-]\d{2})', full_text)
            date_str = None
            if date_match:
                date_str = date_match.group(0)

            result = {
                "amount": amount,
                "merchant": merchant,
                "date": date_str
            }
            
            # Memory safety: Clear reader after intensive OCR if on low-memory env
            # This is optional but can help if Koyeb instance is very tight
            # self._reader = None 
            
            return result
        except Exception as e:
            print(f"OCR Processing Error: {e}")
            return None
        finally:
            # Clean up after processing
            gc.collect()

    def _prepare_image(self, image_path: str):
        max_dim = int(os.getenv("OCR_MAX_DIM", "1280"))
        jpeg_quality = int(os.getenv("OCR_JPEG_QUALITY", "75"))

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
