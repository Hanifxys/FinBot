import re
import os

class OCRProcessor:
    def __init__(self):
        self.enabled = False
        try:
            import easyocr
            self.reader = easyocr.Reader(['id', 'en'])
            self.enabled = True
        except ImportError:
            print("OCR disabled: easyocr not installed")

    def process_receipt(self, image_path):
        if not self.enabled:
            return 0.0
        
        import easyocr
        results = self.reader.readtext(image_path)
        full_text = " ".join([res[1] for res in results])
        
        # Regex to find currency-like values
        # Matches patterns like 50.000, 50,000, 50000, etc.
        amount_patterns = [
            r'(?:total|bayar|jumlah|amount|grand total)[^\d]*([\d\.,]+)',
            r'[\d\.,]+'
        ]
        
        # Look for total specifically first
        total_matches = re.findall(amount_patterns[0], full_text.lower())
        if total_matches:
            # Take the last match which is usually the grand total
            amount_str = total_matches[-1]
            return self._clean_amount(amount_str)
            
        # Fallback: look for the largest number in the text (often the total)
        all_numbers = re.findall(r'(\d+[\d\.,]*)', full_text)
        cleaned_numbers = []
        for num in all_numbers:
            val = self._clean_amount(num)
            if val > 100: # Filter out small numbers like dates/quantities
                cleaned_numbers.append(val)
        
        if cleaned_numbers:
            return max(cleaned_numbers)
            
        return 0.0

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
