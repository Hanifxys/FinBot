import re

class NLPProcessor:
    def __init__(self):
        # Keywords for categorization - User-centric mapping
        self.category_keywords = {
            "Makanan": [
                "makan", "minum", "resto", "warung", "kopi", "cafe", "food", "dinner", "lunch",
                "ngopi", "gofood", "grabfood", "mixue", "starbucks", "haus", "mie", "bakso", "kenangan"
            ],
            "Transportasi": [
                "gojek", "grab", "bensin", "parkir", "tol", "tiket", "kereta", "bus", 
                "ojol", "maxim", "pertalite", "pertamax", "shell"
            ],
            "Belanja": [
                "beli", "shopee", "tokopedia", "mall", "supermarket", "minimarket", "indo", "alfa",
                "belanja", "tiktok shop", "alfamart", "indomaret", "sayur"
            ],
            "Tagihan": [
                "listrik", "air", "wifi", "internet", "pulsa", "asuransi", "kost", "sewa",
                "pln", "pdam", "indihome", "bpjs", "netflix", "spotify"
            ],
            "Investasi": [
                "saham", "reksadana", "crypto", "emas", "invest", "bibit", "ajaib", "pluang"
            ],
            "Gaji": ["gaji", "salary", "bonus", "transfer masuk", "income", "payroll"]
        }

    def process_text(self, text):
        """
        New minimalist processor for bot.py
        Returns (amount, category, type)
        """
        amount = self._extract_amount(text)
        category = self._detect_category(text)
        
        # Determine type (income if 'gaji' or 'income', otherwise expense)
        type_ = 'income' if category == 'Gaji' else 'expense'
        
        return amount, category, type_

    def parse_message(self, text):
        """
        Parses text to extract amount, category, and intent.
        Example: "makan siang 50rb" -> {amount: 50000, category: "Makanan", intent: "add_transaction"}
        """
        text = text.lower()
        
        # Check for budget query intent
        if any(kw in text for kw in ["sisa", "budget", "anggaran", "limit", "total pengeluaran"]):
            category = self._detect_category(text)
            return {"intent": "query_budget", "category": category}

        # Check for report intent
        if any(kw in text for kw in ["laporan", "report", "rekap"]):
            return {"intent": "get_report"}

        # Check for analysis intent
        if any(kw in text for kw in ["analisis", "saran", "pola", "tips"]):
            return {"intent": "get_analysis"}

        # Check for recommendation intent
        if any(kw in text for kw in ["rekomendasi", "alokasi"]):
            return {"intent": "get_recommendation"}

        # Extract amount
        amount = self._extract_amount(text)
        if amount > 0:
            category = self._detect_category(text)
            return {
                "intent": "add_transaction",
                "amount": amount,
                "category": category,
                "description": text
            }

        return {"intent": "unknown"}

    def _extract_amount(self, text):
        # Matches 50rb, 50k, 50000, 50.000
        # 1. Look for numbers followed by 'rb' or 'k'
        match_rb = re.search(r'(\d+)\s*(rb|k)', text)
        if match_rb:
            return float(match_rb.group(1)) * 1000
        
        # 2. Look for plain numbers with optional dots
        match_num = re.findall(r'(\d+[\d\.]*)', text)
        if match_num:
            # Get the one that looks most like an amount (usually the longest or last)
            for num in reversed(match_num):
                cleaned = num.replace('.', '')
                try:
                    val = float(cleaned)
                    if val > 100: # Filter out small numbers
                        return val
                except:
                    continue
        return 0.0

    def _detect_category(self, text):
        text_lower = text.lower()
        for category, keywords in self.category_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return category
        return "Lain-lain"

    def extract_merchant(self, text):
        """
        Tries to extract merchant name from text.
        Example: "mixue 48rb" -> Mixue
        """
        # 1. Remove amounts
        clean_text = re.sub(r'(\d+)\s*(rb|k|rb|000|000.000)', '', text.lower())
        
        # 2. Remove common transaction verbs/prepositions (Stopwords)
        stopwords = ["beli", "bayar", "untuk", "ke", "di", "makan", "minum", "transaksi", "transfer", "ngopi", "makan"]
        for word in stopwords:
            clean_text = re.sub(r'\b' + word + r'\b', '', clean_text)
            
        # 3. Clean up extra spaces
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        merchant = clean_text.title()
        return merchant if merchant else "Transaksi"
