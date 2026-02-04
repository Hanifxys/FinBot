import re
import os

class OCRProcessor:
    def __init__(self):
        self.enabled = True
        try:
            import easyocr
            self.reader = easyocr.Reader(['id', 'en'])
        except Exception as e:
            print(f"OCR Reader Warning: {e}")
            self.reader = None

    def process_receipt(self, image_path):
        if not self.reader:
            return 0.0
            
        results = self.reader.readtext(image_path)
        full_text = " ".join([res[1] for res in results])
        
        # 1. Extract Merchant Name (Usually the first few lines)
        merchant = "Transaksi"
        if len(results) > 0:
            merchant = results[0][1].strip()
            if merchant.lower() in ["alamat", "telp", "tgl", "cashier"]:
                merchant = "Transaksi"

        # 2. Extract Amount
        # Regex to find currency-like values
        amount_patterns = [
            r'(?:total|bayar|jumlah|amount|grand total|nett|total bayar|harga)[^\d]*([\d\.,]+)',
            r'[\d\.,]+'
        ]
        
        # Look for total specifically first
        total_matches = re.findall(amount_patterns[0], full_text.lower())
        amount = 0.0
        if total_matches:
            amount = self._clean_amount(total_matches[-1])
            
        if amount <= 100:
            # Fallback: look for the largest number in the text
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
