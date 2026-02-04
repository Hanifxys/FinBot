import re
import logging
from config import GROQ_API_KEY

class NLPProcessor:
    def __init__(self):
        # Initialize Groq
        self.groq_enabled = False
        try:
            from groq import Groq
            self.client = Groq(api_key=GROQ_API_KEY)
            self.groq_enabled = True
        except Exception as e:
            logging.error(f"Groq initialization failed: {e}")
            self.client = None

        # Keywords for categorization - User-centric mapping
        self.category_keywords = {
            "Makanan": [
                "makan", "minum", "resto", "warung", "kopi", "cafe", "food", "dinner", "lunch",
                "ngopi", "gofood", "grabfood", "mixue", "starbucks", "haus", "mie", "bakso", "kenangan",
                "shopeefood", "martabak", "sate", "warteg", "padang", "seblak", "ayam", "nasgor", "steak"
            ],
            "Transportasi": [
                "gojek", "grab", "bensin", "parkir", "tol", "tiket", "kereta", "bus", 
                "ojol", "maxim", "pertalite", "pertamax", "shell", "bluebird", "krl", "mrt", "lrt", "travel"
            ],
            "Belanja": [
                "beli", "shopee", "tokopedia", "mall", "supermarket", "minimarket", "indo", "alfa",
                "belanja", "tiktok shop", "alfamart", "indomaret", "sayur", "pasar", "toko", "baju", "kaos", "celana"
            ],
            "Tagihan": [
                "listrik", "air", "wifi", "internet", "pulsa", "asuransi", "kost", "sewa",
                "pln", "pdam", "indihome", "bpjs", "netflix", "spotify", "pajak", "pbb", "cicilan"
            ],
            "Kesehatan": [
                "obat", "apotek", "rs", "rumah sakit", "dokter", "halodoc", "vitamin", "klinik", "lab", "periksa"
            ],
            "Lifestyle": [
                "bioskop", "xxi", "gym", "salon", "potong rambut", "game", "topup", "skin", "steam", "nonton", "hiburan", "travel"
            ],
            "Sosial": [
                "sedekah", "zakat", "donasi", "kondangan", "kado", "hadiah", "infaq", "transfer", "pinjam", "bayar hutang"
            ],
            "Pendidikan": [
                "kursus", "udemy", "buku", "fotocopy", "spp", "ukt", "sekolah", "kuliah", "pelatihan"
            ],
            "Maintenance": [
                "service", "bengkel", "cuci", "ganti oli", "ban", "renovasi", "perbaikan", "sparepart"
            ],
            "Investasi": [
                "saham", "reksadana", "crypto", "emas", "invest", "bibit", "ajaib", "pluang", "trading"
            ],
            "Gaji": ["gaji", "salary", "bonus", "transfer masuk", "income", "payroll", "pemasukan", "cashback", "refund", "jual"]
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
        
        # 1. Standardize separators: change comma to dot for decimal parsing
        # But only if it looks like a decimal (e.g., 1,5jt)
        text = re.sub(r'(\d+),(\d+)\s*(jt|mio|rb|k|ribu)', r'\1.\2\3', text)
        
        # 2. Normalize Million (jt/mio -> 000000)
        text = re.sub(r'([\d\.]+)\s*(jt|mio|juta)', lambda m: str(int(float(m.group(1)) * 1000000)), text)
        
        # 3. Normalize Thousand (rb/k -> 000)
        text = re.sub(r'([\d\.]+)\s*(rb|k|ribu|rebu)', lambda m: str(int(float(m.group(1)) * 1000)), text)
        
        # 4. Clean common Indonesian currency prefix
        text = text.replace('rp', '').replace('rupiah', '')
        
        return text

    def classify_intent(self, text, state="IDLE"):
        """
        Classifies user message into ONE intent based on text and current state.
        Returns: {"intent": "...", "confidence": 0.0-1.0}
        """
        normalized_text = self.normalize_text(text)
        
        # Handle EDIT states strictly
        if state.startswith("WAITING_EDIT"):
            if any(kw in normalized_text for kw in ["batal", "cancel", "gak jadi", "stop", "abaikan"]):
                return {"intent": "CANCEL", "confidence": 1.0}
            return {"intent": "EDIT_TRANSACTION", "confidence": 0.9}

        # 1. Check for Transaction (Amount + Category)
        amount = self._extract_amount(normalized_text)
        if amount > 0:
            return {"intent": "ADD_TRANSACTION", "confidence": 0.95}

        # 2. Check for Budget Query
        if any(kw in normalized_text for kw in ["sisa", "budget", "anggaran", "limit", "kuota"]):
            return {"intent": "CHECK_BUDGET", "confidence": 0.9}

        # 3. Check for Report/Summary
        if any(kw in normalized_text for kw in ["laporan", "report", "rekap", "summary", "statistik"]):
            return {"intent": "QUERY_SUMMARY", "confidence": 0.9}

        # 4. Check for Help/Command List
        if any(kw in normalized_text for kw in ["help", "tolong", "bantuan", "perintah", "command", "bisa apa"]):
            return {"intent": "HELP", "confidence": 1.0}

        # 5. Check for Greetings
        if any(kw in normalized_text for kw in ["halo", "hi", "hai", "p", "siang", "pagi", "malam"]):
            return {"intent": "GREETING", "confidence": 0.8}

        # 6. LLM Fallback (Groq) for complex queries
        if self.groq_enabled:
            llm_intent = self._llm_classify_intent(text)
            if llm_intent:
                return llm_intent

        return {"intent": "UNKNOWN", "confidence": 0.0}

    def _llm_classify_intent(self, text):
        """
        Uses Groq LLM to classify intent when regex fails.
        """
        try:
            prompt = f"""
            Classify the intent of this financial bot user message: "{text}"
            
            Allowed intents:
            - ADD_TRANSACTION: User wants to record an expense or income (e.g., "beli cilok", "tadi makan 20k")
            - CHECK_BUDGET: User asks about remaining budget or limits
            - QUERY_SUMMARY: User wants to see reports or stats
            - HELP: User needs assistance or command list
            - GREETING: Casual talk
            - UNKNOWN: Anything else
            
            Return ONLY a JSON with "intent" and "confidence" (0.0-1.0).
            Example: {{"intent": "ADD_TRANSACTION", "confidence": 0.85}}
            """
            
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-8b-8192",
                response_format={"type": "json_object"}
            )
            import json
            result = json.loads(chat_completion.choices[0].message.content)
            return result
        except Exception as e:
            logging.error(f"Groq LLM classification failed: {e}")
            return None

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
            "Kesehatan": "Kesehatan",
            "Lifestyle": "Lifestyle",
            "Sosial": "Sosial",
            "Pendidikan": "Pendidikan",
            "Maintenance": "Maintenance",
            "Investasi": "Investasi",
            "Gaji": "Gaji",
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
        # 1. Remove amounts and suffixes
        clean_text = self.normalize_text(text)
        clean_text = re.sub(r'\d+', '', clean_text)
        
        # 2. Remove common transaction verbs/prepositions (Stopwords)
        stopwords = [
            "beli", "bayar", "untuk", "ke", "di", "makan", "minum", "transaksi", "transfer", 
            "ngopi", "buat", "pembayaran", "tagihan", "biaya", "topup", "saldo", "isi", "pemasukan",
            "gaji", "bonus", "duit", "uang"
        ]
        for word in stopwords:
            clean_text = re.sub(r'\b' + word + r'\b', '', clean_text.lower())
            
        # 3. Clean up punctuation and extra spaces
        clean_text = re.sub(r'[^\w\s]', ' ', clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        merchant = clean_text.title()
        return merchant if merchant else "Transaksi"
