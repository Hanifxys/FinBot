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

    def normalize_text(self, text):
        """
        Normalizes informal text like '2jt' -> '2000000', '50rb' -> '50000', etc.
        Also handles slang and common abbreviations.
        """
        text = text.lower().strip()
        
        # 1. Normalize Million (jt -> 000000)
        text = re.sub(r'(\d+)\s*jt', lambda m: str(int(m.group(1)) * 1000000), text)
        
        # 2. Normalize Thousand (rb/k -> 000)
        text = re.sub(r'(\d+)\s*(rb|k)', lambda m: str(int(m.group(1)) * 1000), text)
        
        # 3. Handle 'setengah' or 'set' for fractions (optional, but good for AI feel)
        text = text.replace('setengah', '0.5').replace('set ', '0.5 ')
        
        return text

    def classify_intent(self, text, state="IDLE"):
        """
        Classifies user message into ONE intent based on text and current state.
        Returns: {"intent": "...", "confidence": 0.0-1.0}
        """
        text = self.normalize_text(text)
        
        # If in EDIT MODE, the only valid intent is processing the edit or cancelling
        if state.startswith("WAITING_EDIT"):
            if any(kw in text for kw in ["batal", "cancel", "gak jadi", "stop"]):
                return {"intent": "CANCEL", "confidence": 1.0}
            return {"intent": "EDIT_TRANSACTION", "confidence": 0.9}

        # CHECK_BUDGET
        if any(kw in text for kw in ["sisa", "budget", "anggaran", "limit", "sisa saldo"]):
            return {"intent": "CHECK_BUDGET", "confidence": 0.9}

        # QUERY_SUMMARY / REPORT
        if any(kw in text for kw in ["laporan", "report", "rekap", "summary", "pengeluaran saya"]):
            return {"intent": "QUERY_SUMMARY", "confidence": 0.9}

        # SET_SALARY
        if text.startswith("/setgaji") or "gaji saya" in text:
            return {"intent": "SET_SALARY", "confidence": 1.0}

        # SET_BUDGET
        if text.startswith("/setbudget") or "atur budget" in text:
            return {"intent": "SET_BUDGET", "confidence": 1.0}

        # ADD_TRANSACTION (has amount)
        amount = self._extract_amount(text)
        if amount > 0:
            return {"intent": "ADD_TRANSACTION", "confidence": 0.9}

        return {"intent": "UNKNOWN", "confidence": 0.0}

    def extract_transaction_data(self, text):
        """
        Extracts structured financial transaction data.
        Returns JSON-like dict.
        """
        text = self.normalize_text(text)
        amount = self._extract_amount(text)
        category = self._detect_category(text)
        merchant = self.extract_merchant(text)
        
        # Mapping categories to allowed list
        category_map = {
            "Makanan": "Makan",
            "Transportasi": "Transport",
            "Belanja": "Belanja",
            "Tagihan": "Tagihan",
            "Gaji": "Gaji",
            "Investasi": "Investasi",
            "Lain-lain": "Lainnya"
        }
        mapped_cat = category_map.get(category, "Lainnya")
        
        # Determine type
        type_ = "income" if mapped_cat == "Gaji" else "expense"
        
        from datetime import datetime
        
        return {
            "amount": amount if amount > 0 else None,
            "type": type_ if amount > 0 else None,
            "category": mapped_cat if amount > 0 else None,
            "merchant": merchant if merchant != "Transaksi" else None,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "confidence": 0.9 if amount > 0 else 0.0
        }

    def validate_edit(self, field, user_message):
        """
        Validates input for EDIT MODE.
        """
        user_message = self.normalize_text(user_message)
        
        if field == "amount":
            amount = self._extract_amount(user_message)
            if amount > 0:
                return {"new_value": amount, "valid": True, "reason": None}
            return {"new_value": None, "valid": False, "reason": "Nominal tidak valid"}
            
        if field == "category":
            category = self._detect_category(user_message)
            if category != "Lain-lain":
                return {"new_value": category, "valid": True, "reason": None}
            return {"new_value": None, "valid": False, "reason": "Kategori tidak dikenal"}
            
        return {"new_value": None, "valid": False, "reason": "Field tidak valid"}

    def _extract_amount(self, text):
        # 1. Normalize first to handle jt, rb, k
        normalized = self.normalize_text(text)
        
        # 2. Look for numbers (including those with dots like 2.000.000)
        match_num = re.findall(r'(\d+[\d\.]*)', normalized)
        if match_num:
            for num in reversed(match_num):
                cleaned = num.replace('.', '')
                try:
                    val = float(cleaned)
                    if val >= 100: # Standard threshold
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
