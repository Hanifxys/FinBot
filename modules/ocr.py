import re
import os
import gc

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
                # We expect models to be pre-downloaded or cached
                self._reader = easyocr.Reader(['id', 'en'], gpu=False, download_enabled=True)
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
            results = reader.readtext(image_path)
            full_text = " ".join([res[1] for res in results])
            
            # 1. Extract Merchant Name (Usually the first few lines)
            merchant = "Transaksi"
            if len(results) > 0:
                merchant = results[0][1].strip()
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

            return {
                "amount": amount,
                "merchant": merchant,
                "date": date_str
            }
        finally:
            # Clean up after processing
            gc.collect()

    def _clean_amount(self, amount_str):
        # Remove dots and commas, but keep decimal if it exists
        # In Indonesia, dot is thousands separator, comma is decimal
        # We'll normalize it to float
        cleaned = amount_str.replace('.', '').replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            # Try removing any non-numeric chars
            cleaned = re.sub(r'[^\d]', '', amount_str)
            try:
                return float(cleaned)
            except:
                return 0.0
