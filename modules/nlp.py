import re
import logging
import gc
import difflib
from typing import Dict, Any, Tuple, Optional, List
from config import GROQ_API_KEY
from modules.amounts import parse_primary_amount_id

logger = logging.getLogger(__name__)

class NLPProcessor:
    def __init__(self):
        # Initialize Groq
        self._client = None
        self.groq_enabled = bool(GROQ_API_KEY and GROQ_API_KEY.strip())

        # Slang & Abbreviation Mapping (Indonesian)
        self.slang_map = {
            "mkn": "makan", "mnm": "minum", "bli": "beli", "byr": "bayar",
            "blj": "belanja", "trf": "transfer", "tf": "transfer",
            "k": "ribu", "rb": "ribu", "jt": "juta", "mio": "juta",
            "skul": "sekolah", "klh": "kuliah", "bns": "bensin",
            "parkir": "parkir", "pkr": "parkir", "rt": "rumah tangga",
            "ls": "listrik", "net": "internet", "inet": "internet",
            "pd": "pendidikan", "inv": "investasi", "depo": "deposit",
            "wd": "withdraw", "ccl": "cicilan", "kred": "kredit",
            "lap": "laporan", "cek": "check", "sisa": "sisa",
            "bln": "bulan", "thn": "tahun", "hr": "hari",
            "bsk": "besok", "kmrn": "kemarin", "tgl": "tanggal",
            "gaji": "gaji", "gj": "gaji", "inc": "income", "exp": "expense",
            "gw": "saya", "aku": "saya", "sy": "saya",
            "ga": "tidak", "gk": "tidak", "gak": "tidak",
            "ngopi": "kopi", "sarapan": "makan pagi", "lunch": "makan siang",
            "dinner": "makan malam", "gojek": "ojol", "grab": "ojol",
            "gocar": "taksi", "grabcar": "taksi", "bluebird": "taksi"
        }

        # Keywords for categorization - User-centric mapping
        self.category_keywords = {
            "Makanan": [
                "makan", "resto", "warung", "food", "dinner", "lunch", "gofood", "grabfood", "shopeefood", 
                "warteg", "padang", "ayam", "nasgor", "steak", "sate", "bakso", "mie", "soto", "bubur", "nasi"
            ],
            "Minuman": [
                "minum", "kopi", "cafe", "ngopi", "mixue", "starbucks", "haus", "kenangan", "chatime", "janji jiwa",
                "jus", "susu", "teh", "boba", "coffee", "beer", "wine", "air galon", "aqua"
            ],
            "Jajanan": [
                "jajan", "cemilan", "snack", "ciki", "coklat", "es krim", "roti", "kue", "martabak", 
                "seblak", "cimol", "cilok", "gorengan", "pisang goreng", "keripik", "biskuit"
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
        
        # Pre-compile regex patterns for performance
        self._compiled_keywords = {}
        for cat, keywords in self.category_keywords.items():
            pattern = r'\b(' + '|'.join(map(re.escape, keywords)) + r')\b'
            self._compiled_keywords[cat] = re.compile(pattern, re.IGNORECASE)
            
        # Fast path intent checks (compiled)
        self._intents_map = {
            "query_budget": re.compile(r'\b(sisa|budget|anggaran|limit|total|kuota)\b', re.IGNORECASE),
            "get_report": re.compile(r'\b(laporan|report|rekap|summary|statistik)\b', re.IGNORECASE),
            "roast_wallet": re.compile(r'\b(roast|julid|marah|hujat)\b', re.IGNORECASE),
            "export_data": re.compile(r'\b(export|ekspor|download|backup)\b', re.IGNORECASE),
            "what_if": re.compile(r'\b(what if|simulasi|kalo|misal|kalau|andai|seandainya)\b', re.IGNORECASE),
            "greeting": re.compile(r'\b(halo|hi|hai|siang|pagi|malam|apa kabar|sehat)\b', re.IGNORECASE),
            "set_budget_alert": re.compile(r'\b(ingat|inget|alert|warning|batas|notif|peringatan).*(budget|anggaran)\b', re.IGNORECASE),
            "set_budget": re.compile(r'\b(target|set|atur|ubah|ganti|tambah).*(budget|anggaran|limit)\b', re.IGNORECASE),
            "set_gaji": re.compile(r'\b(set|atur|ubah|ganti|masukkan).*(gaji|pemasukan|income|pendapatan)\b', re.IGNORECASE),
        }

        # New: Command-like patterns for feedback and control
        self._control_patterns = {
            "STOP_NOTIF": re.compile(r'\b(jangan|janganlah|stop|berhenti|henti|ga usah|gak usah|kurangi|kurangin|matiin|matikan).*(daily|digest|notif|notifikasi|pesan|laporan|sering|digestnya)\b', re.IGNORECASE),
            "ASK_FOR_NOTIF": re.compile(r'\b(kapan|jadwal|jam berapa|aktifin|nyalain|hidupin).*(daily|digest|notif|notifikasi)\b', re.IGNORECASE),
        }

    @property
    def client(self):
        """Lazy load Groq client to save memory on startup"""
        if self._client is None and self.groq_enabled:
            try:
                from groq import Groq
                self._client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                logging.error(f"Groq initialization failed: {e}")
                self._client = None
                self.groq_enabled = False
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

    def normalize_text(self, text: str) -> str:
        """
        Normalizes informal text like '2jt' -> '2000000', '50rb' -> '50000', etc.
        Also handles slang and common abbreviations using dictionary mapping.
        """
        if not text:
            return ""
            
        # 0. Basic cleaning: remove extra whitespace, lower case
        text = text.lower().strip()
        
        # 1. Advanced cleaning: remove noise like 'kak', 'bang', 'dong', 'ya', 'nih'
        noise_words = ["kak", "bang", "sis", "bro", "dong", "ya", "nih", "deh", "sih", "kok", "tuh", "lah", "aja", "saja"]
        pattern = r'\b(' + '|'.join(map(re.escape, noise_words)) + r')\b'
        text = re.sub(pattern, '', text)
        
        # 2. Slang Replacement (Token-based)
        tokens = text.split()
        normalized_tokens = []
        for token in tokens:
            # Handle mixed alphanumeric like '50k' or '2jt' first
            if re.match(r'^\d+[a-z]+$', token):
                normalized_tokens.append(token)
                continue
            
            # Use slang map
            normalized_tokens.append(self.slang_map.get(token, token))
            
        text = " ".join(normalized_tokens)

        # 3. Standardize separators: change comma to dot for decimal parsing
        # But only if it looks like a decimal (e.g., 1,5jt or 1.5jt)
        text = re.sub(r'(\d+),(\d+)\s*(jt|mio|rb|k|ribu)', r'\1.\2\3', text)
        
        # 4. Normalize Million (jt/mio -> 000000)
        text = re.sub(r'([\d\.]+)\s*(jt|mio|juta)', lambda m: str(int(float(m.group(1)) * 1000000)), text)
        
        # 5. Normalize Thousand (rb/k -> 000)
        text = re.sub(r'([\d\.]+)\s*(rb|k|ribu|rebu)', lambda m: str(int(float(m.group(1)) * 1000)), text)
        
        # 6. Clean common Indonesian currency prefix and trailing zeros/separators
        text = text.replace('rp', '').replace('rupiah', '')
        
        # 7. Handle cases like 100,000 or 100.000 (treat as 100000)
        text = re.sub(r'(\d{1,3})([,\.]\d{3})+(?!\d)', lambda m: m.group(0).replace(',', '').replace('.', ''), text)
        
        return text.strip()

    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Analyzes user sentiment using LLM or Rule-based fallback.
        Returns: {"sentiment": "POSITIVE|NEGATIVE|NEUTRAL", "mood": "happy|stressed|angry|etc", "score": 0.0-1.0}
        """
        # Rule-based fallback for quick detection
        positive_keywords = ["senang", "bagus", "keren", "mantap", "hebat", "makasih", "thanks", "untung", "naik", "hemat"]
        negative_keywords = ["sedih", "pusing", "stres", "marah", "rugi", "boros", "mahal", "habis", "kosong", "kering"]
        
        text_lower = text.lower()
        pos_count = sum(1 for kw in positive_keywords if kw in text_lower)
        neg_count = sum(1 for kw in negative_keywords if kw in text_lower)
        
        sentiment = "NEUTRAL"
        mood = "neutral"
        score = 0.5
        
        if pos_count > neg_count:
            sentiment = "POSITIVE"
            mood = "happy"
            score = 0.8
        elif neg_count > pos_count:
            sentiment = "NEGATIVE"
            mood = "stressed"
            score = 0.2
            
        # LLM refinement if available
        if self.groq_enabled:
            try:
                prompt = f"""
                Analyze the financial sentiment of this message: "{text}"
                Return JSON: {{"sentiment": "POSITIVE|NEGATIVE|NEUTRAL", "mood": "happy|stressed|angry|hopeful|frustrated", "confidence": 0.0-1.0}}
                """
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="llama-3.3-70b-versatile",
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                import json
                llm_res = json.loads(chat_completion.choices[0].message.content)
                return {
                    "sentiment": llm_res.get("sentiment", sentiment),
                    "mood": llm_res.get("mood", mood),
                    "score": llm_res.get("confidence", score)
                }
            except Exception as e:
                logger.error(f"Sentiment analysis failed: {e}")
                
        return {"sentiment": sentiment, "mood": mood, "score": score}

    def handle_small_talk(self, text: str) -> Optional[str]:
        """
        Handles small talk or casual questions that don't fit into financial intents.
        """
        if not self.groq_enabled:
            return None
            
        text_lower = text.lower()
        # Only handle if it looks like a question or casual greeting not caught by regex
        if any(kw in text_lower for kw in ["siapa", "kamu", "bot", "nama", "pencipta", "buat", "makan", "apa", "cerita"]):
            try:
                prompt = f"""
                You are FinBot, a helpful and friendly financial assistant. 
                Answer this casual message/question concisely: "{text}"
                Keep it short, professional yet friendly. Use Indonesian.
                """
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="llama-3.3-70b-versatile",
                    temperature=0.7
                )
                return chat_completion.choices[0].message.content
            except Exception:
                return None
        return None

    def hybrid_classify(self, text: str, state: str = "IDLE") -> Dict[str, Any]:
        """
        Main entry point for intent classification.
        Uses Hybrid Approach: Fast Regex -> Low Confidence -> Slow LLM.
        """
        normalized_text = self.normalize_text(text)
        
        # 0. Quick Control/Feedback check (High Priority)
        for intent, pattern in self._control_patterns.items():
            if pattern.search(normalized_text):
                return {"intent": intent, "confidence": 1.0}

        # 1. Handle Critical States (Edit/Cancel) - Priority 1
        if state.startswith("WAITING_EDIT"):
            if any(kw in normalized_text for kw in ["batal", "cancel", "gak jadi", "stop", "abaikan"]):
                return {"intent": "CANCEL", "confidence": 1.0}
            return {"intent": "EDIT_TRANSACTION", "confidence": 0.9}

        # 2. Sentiment Context (New)
        sentiment_data = self.analyze_sentiment(text)
        
        # 3. Fast Path: Regex Matching (Priority 2)
        regex_intent = self._regex_classify(normalized_text)
        if regex_intent["confidence"] >= 0.85:
            regex_intent["sentiment"] = sentiment_data
            return regex_intent
            
        # 4. Slow Path: LLM Fallback (Priority 3)
        # Only if regex failed or low confidence AND LLM is enabled
        if self.groq_enabled:
            llm_intent = self._llm_classify_intent(text) # Pass original text for better context
            if llm_intent and llm_intent.get('confidence', 0) >= 0.7:
                llm_intent["sentiment"] = sentiment_data
                return llm_intent
        
        # 5. Small Talk Fallback (New)
        small_talk_res = self.handle_small_talk(text)
        if small_talk_res:
            return {"intent": "SMALL_TALK", "response": small_talk_res, "confidence": 1.0, "sentiment": sentiment_data}

        # 6. Fallback if everything fails
        if regex_intent["confidence"] > 0.0:
            regex_intent["sentiment"] = sentiment_data
            return regex_intent
            
        return {"intent": "UNKNOWN", "confidence": 0.0, "sentiment": sentiment_data}

    def _regex_classify(self, text: str) -> Dict[str, Any]:
        """Internal regex classifier."""
        # Check specific features
        if self._intents_map["roast_wallet"].search(text):
            return {"intent": "ROAST_WALLET", "confidence": 0.95}
        if self._intents_map["export_data"].search(text):
            return {"intent": "EXPORT_DATA", "confidence": 0.95}
        if self._intents_map["what_if"].search(text):
            return {"intent": "WHAT_IF", "confidence": 0.95}
        
        # Income recognition heuristics (Prioritize over ADD_TRANSACTION)
        income_keywords = ["gaji", "bonus", "pemasukan", "income", "payroll", "transfer masuk", "pembayaran dari"]
        if any(re.search(rf"\b{kw}\b", text) for kw in income_keywords) and self._extract_amount(text) > 0:
            return {"intent": "ADD_TRANSACTION", "type": "income", "confidence": 0.95}

        # Anti-Robot Check (Declarative)
        declarative_pattern = r'\b(punya|ada|total|sisa|tabungan|saldo|duit|uang|rekening|dompet|cash|aset).*\d+'
        if re.search(declarative_pattern, text) and not any(kw in text for kw in ["beli", "bayar", "jajan", "keluar", "habis", "tambah", "simpan", "catat"]):
             return {"intent": "SHARING_INFO", "confidence": 0.85}

        # Settings
        if self._intents_map["set_budget_alert"].search(text):
            return {"intent": "SET_BUDGET_ALERT", "confidence": 0.95}
        if self._intents_map["set_gaji"].search(text):
            return {"intent": "SET_GAJI", "confidence": 0.95}
        if self._intents_map["set_budget"].search(text):
            return {"intent": "SET_BUDGET", "confidence": 0.95}

        # Natural Language Settings
        if any(kw in text for kw in ["mode", "ganti mode", "ubah mode"]):
            if any(kw in text for kw in ["coach", "galak", "tegas"]):
                return {"intent": "SET_MODE", "value": "coach", "confidence": 0.9}
            if any(kw in text for kw in ["buddy", "santai", "teman"]):
                return {"intent": "SET_MODE", "value": "buddy", "confidence": 0.9}
            if any(kw in text for kw in ["analyst", "formal", "data"]):
                return {"intent": "SET_MODE", "value": "analyst", "confidence": 0.9}
                
        if any(kw in text for kw in ["reminder", "ingatkan", "notif"]):
            if "on" in text or "nyala" in text or "hidup" in text:
                return {"intent": "SET_REMINDER", "value": "on", "confidence": 0.9}
            if "off" in text or "mati" in text:
                return {"intent": "SET_REMINDER", "value": "off", "confidence": 0.9}

        # Transaction Check
        amount = self._extract_amount(text)
        if amount > 0:
            return {"intent": "ADD_TRANSACTION", "confidence": 0.95}

        # Query Checks
        if self._intents_map["query_budget"].search(text):
            return {"intent": "CHECK_BUDGET", "confidence": 0.9}
        if self._intents_map["get_report"].search(text):
            return {"intent": "QUERY_SUMMARY", "confidence": 0.9}
        if any(kw in text for kw in ["help", "tolong", "bantuan", "perintah", "command", "bisa apa"]):
            return {"intent": "HELP", "confidence": 1.0}
        if self._intents_map["greeting"].search(text):
            return {"intent": "GREETING", "confidence": 1.0}
            
        return {"intent": "UNKNOWN", "confidence": 0.0}

    def _llm_classify_intent(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Uses Groq LLM (Llama 3) as a Transformer-based classifier.
        """
        client = self.client
        if not client:
            return None
            
        try:
            # Optimized Prompt for Intent Classification
            prompt = f"""
            Analyze the user's message and extract the INTENT.
            Message: "{text}"
            
            INTENT LIST:
            - ADD_TRANSACTION: User is spending or receiving money (e.g. "beli makan 20k", "gaji masuk 5jt").
            - SHARING_INFO: User shares status WITHOUT action (e.g. "saldo gw tinggal 50rb", "tabungan ada 10jt").
            - CHECK_BUDGET: Asking about limits/remaining money (e.g. "sisa budget", "cukup ga").
            - QUERY_SUMMARY: Asking for reports (e.g. "laporan bulan ini", "rekap").
            - GREETING: Casual chat (e.g. "halo", "pagi", "thanks").
            - UNKNOWN: Unclear or out of scope.
            
            Return JSON: {{"intent": "INTENT_NAME", "confidence": 0.0-1.0}}
            """
            
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.1 # Low temperature for consistent classification
            )
            import json
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            logging.error(f"LLM Intent Classification Error: {e}")
            return None
        finally:
            gc.collect()

    def extract_transaction_data(self, text: str) -> Dict[str, Any]:
        """
        Extracts structured financial transaction data.
        Returns JSON-like dict.
        """
        # 0. Check for implicit type from classification
        classification = self._regex_classify(text)
        forced_type = classification.get("type")

        # 1. Try LLM Extraction for complex sentences if enabled
        if self.groq_enabled and len(text.split()) > 4:
             llm_data = self._llm_extract_entities(text)
             if llm_data and llm_data.get("amount"):
                 if forced_type:
                     llm_data["type"] = forced_type
                 return llm_data

        # 2. Fallback to Regex/Heuristic (Standard)
        text_norm = self.normalize_text(text)
        amount = self._extract_amount(text_norm)
        category = self._detect_category(text_norm)
        merchant = self.extract_merchant(text_norm)
        
        # Mapping categories
        category_map = {
            "Makanan": "Makanan", "Minuman": "Minuman", "Jajanan": "Jajanan",
            "Transportasi": "Transportasi", "Belanja": "Belanja", "Tagihan": "Tagihan",
            "Kesehatan": "Kesehatan", "Lifestyle": "Lifestyle", "Sosial": "Sosial",
            "Pendidikan": "Pendidikan", "Maintenance": "Maintenance", "Investasi": "Investasi",
            "Gaji": "Gaji", "Lain-lain": "Lain-lain"
        }
        mapped_cat = category_map.get(category, "Lain-lain")
        
        # Determine type
        if forced_type:
            type_ = forced_type
        else:
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

    def _llm_extract_entities(self, text: str) -> Optional[Dict[str, Any]]:
        """Uses LLM to extract NER (Amount, Category, Merchant) from complex text."""
        client = self.client
        if not client: return None
        
        try:
            prompt = f"""
            Extract financial entities from: "{text}"
            
            Return JSON:
            {{
                "amount": float (raw number, e.g. 20000),
                "category": string (Choose: Makanan, Minuman, Jajanan, Transportasi, Belanja, Tagihan, Lain-lain),
                "merchant": string (e.g. "Starbucks", "Indomaret"),
                "type": string ("expense" or "income")
            }}
            """
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.1
            )
            import json
            data = json.loads(chat_completion.choices[0].message.content)
            
            # Post-process amount
            if data.get("amount"):
                data["confidence"] = 0.95
                from datetime import datetime
                data["date"] = datetime.now().strftime("%Y-%m-%d")
                return data
            return None
        except Exception:
            return None

    def validate_edit(self, field: str, user_message: str) -> Dict[str, Any]:
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

    def _detect_category(self, text: str) -> str:
        """Smarter category detection with improved keyword matching using pre-compiled regex and fuzzy match"""
        if not text:
            return "Lain-lain"
            
        text = text.lower()
        
        # 1. Exact Regex Match
        for category, pattern in self._compiled_keywords.items():
            if pattern.search(text):
                return category
        
        # 2. Heuristic: if text contains "beli" or "bayar" but no category found
        if any(kw in text for kw in ["beli", "bayar", "pesan", "checkout"]):
            return "Belanja"

        # 3. Fuzzy Match for Typos (e.g. "mkan" -> "makan")
        # Flatten all keywords
        all_keywords = []
        keyword_to_cat = {}
        for cat, kws in self.category_keywords.items():
            for kw in kws:
                all_keywords.append(kw)
                keyword_to_cat[kw] = cat
        
        words = text.split()
        for word in words:
            if len(word) > 3: # Skip short words
                matches = difflib.get_close_matches(word, all_keywords, n=1, cutoff=0.8)
                if matches:
                    return keyword_to_cat[matches[0]]
            
        return "Lain-lain"

    def _extract_amount(self, text: str) -> float:
        val = parse_primary_amount_id(text)
        if val is None:
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    def extract_merchant(self, text: str) -> str:
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
            "gaji", "bonus", "duit", "uang", "bensin", "kopi", "makan", "sarapan", "lunch", "dinner",
            "pesan", "order", "via", "dari", "sama", "dengan"
        ]
        
        # Build a regex pattern for stopwords to remove them efficiently
        pattern = r'\b(' + '|'.join(map(re.escape, stopwords)) + r')\b'
        clean_text = re.sub(pattern, '', clean_text.lower())
            
        # 3. Clean up punctuation and extra spaces
        clean_text = re.sub(r'[^\w\s]', ' ', clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        # 4. Filter short words (likely conjunctions or typos)
        words = [w for w in clean_text.split() if len(w) > 2]
        clean_text = " ".join(words)
        
        merchant = clean_text.title()
        return merchant if merchant else "Transaksi"

    # Compatibility alias for classify_intent
    def classify_intent(self, text: str, state: str = "IDLE") -> Dict[str, Any]:
        return self.hybrid_classify(text, state)
