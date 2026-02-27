import re
import os
import logging
import gc
import difflib
import time
import random
from collections import Counter
from typing import Dict, Any, Tuple, Optional, List, Sequence
from config import GROQ_API_KEY
from modules.amounts import parse_primary_amount_id
from modules.transformer_nlp import TransformerNLPBackend, TransformerNLPConfig

logger = logging.getLogger(__name__)

class NLPProcessor:
    def __init__(self):
        # Initialize Groq
        self._client = None
        self.groq_enabled = bool(GROQ_API_KEY and GROQ_API_KEY.strip())
        self.llm_sentiment_enabled = os.getenv("NLP_ENABLE_LLM_SENTIMENT", "false").lower() in ("1", "true", "yes", "on")
        self.llm_category_enabled = os.getenv("NLP_ENABLE_LLM_CATEGORY", "false").lower() in ("1", "true", "yes", "on")
        self.intent_ensemble_enabled = os.getenv("NLP_ENABLE_INTENT_ENSEMBLE", "true").lower() in ("1", "true", "yes", "on")
        self.explainability_enabled = os.getenv("NLP_ENABLE_EXPLAINABILITY", "true").lower() in ("1", "true", "yes", "on")
        self.confidence_temperature = float(os.getenv("NLP_CONFIDENCE_TEMPERATURE", "0.85"))

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
            "gocar": "taksi", "grabcar": "taksi", "bluebird": "taksi",
            "bsy": "beli", "abis": "habis", "tadi": "", "td": ""
        }

        # Keywords for categorization - User-centric mapping
        self.category_keywords = {
            "Makanan": [
                "makan", "resto", "warung", "food", "dinner", "lunch", "gofood", "grabfood", "shopeefood", 
                "warteg", "padang", "ayam", "nasgor", "steak", "sate", "bakso", "mie", "soto", "bubur", "nasi",
                "bebek", "ikan", "sayur", "buah", "roti", "bakmi", "pecel", "geprek", "penyet", "burger", "pizza",
                "sushi", "ramen", "kfc", "mcd", "hokben", "solaria", "kopi", "cafe", "ngopi"
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
            "split_bill": re.compile(r'\b(split|bagi|patungan|share).*(bill|total|orang|person)\b', re.IGNORECASE),
            "correction": re.compile(r'\b(salah|ralat|bukan|maksudnya|eh)\b', re.IGNORECASE),
            "undo": re.compile(r'\b(undo|batal|cancel|gak jadi|gakjadi|balikin)\b', re.IGNORECASE),
            "executive_mode": re.compile(r'\b(executive|eksekutif|ringkas|tajam|bullet)\b', re.IGNORECASE),
            "elite_analysis": re.compile(r'\b(elite|intel|market|risk|prediksi pasar|investasi|analisis mendalam)\b', re.IGNORECASE),
            "investment_opps": re.compile(r'\b(peluang|opportunity|cuan|beli apa|investasi apa|rekomendasi)\b', re.IGNORECASE),
            "doc_analysis": re.compile(r'\b(analisis file|bedah laporan|parsing|baca laporan)\b', re.IGNORECASE),
            "bulk_transaction": re.compile(r'(\n|,|;|:)', re.IGNORECASE), # Heuristic for multiple items
        }

        # New: Command-like patterns for feedback and control
        self._control_patterns = {
            "STOP_NOTIF": re.compile(r'\b(jangan|janganlah|stop|berhenti|henti|ga usah|gak usah|kurangi|kurangin|matiin|matikan).*(daily|digest|notif|notifikasi|pesan|laporan|sering|digestnya)\b', re.IGNORECASE),
            "ASK_FOR_NOTIF": re.compile(r'\b(kapan|jadwal|jam berapa|aktifin|nyalain|hidupin).*(daily|digest|notif|notifikasi)\b', re.IGNORECASE),
        }

        # Transformer intent descriptions for multilingual zero-shot fallback.
        self._intent_descriptions = {
            "ADD_TRANSACTION": "mencatat transaksi pengeluaran atau pemasukan",
            "SHARING_INFO": "berbagi informasi kondisi keuangan tanpa aksi pencatatan",
            "CHECK_BUDGET": "meminta status budget atau limit",
            "QUERY_SUMMARY": "meminta ringkasan laporan keuangan",
            "SET_BUDGET": "mengatur budget kategori",
            "SET_BUDGET_ALERT": "mengatur pengingat atau batas budget",
            "SET_GAJI": "mengatur nominal gaji atau pendapatan bulanan",
            "CORRECTION": "koreksi transaksi yang sudah disebut",
            "SPLIT_BILL": "membagi total tagihan ke beberapa orang",
            "BULK_TRANSACTION": "mencatat beberapa transaksi sekaligus",
            "SET_MODE": "mengubah gaya asisten",
            "SET_REMINDER": "mengubah pengaturan reminder atau notifikasi",
            "UNDO": "membatalkan aksi terakhir",
            "ROAST_WALLET": "meminta evaluasi gaya belanja secara tegas",
            "EXPORT_DATA": "meminta ekspor data transaksi",
            "WHAT_IF": "simulasi skenario keuangan",
            "DOC_ANALYSIS": "meminta analisis dokumen keuangan",
            "ELITE_ANALYSIS": "meminta analisis finansial mendalam",
            "INVESTMENT_OPPS": "meminta peluang investasi",
            "SMALL_TALK": "percakapan santai non-transaksi",
            "GREETING": "sapaan pembuka",
            "HELP": "permintaan bantuan fitur",
            "UNKNOWN": "tidak jelas atau di luar cakupan",
        }

        # Deep-topic taxonomy for richer contextual understanding.
        self.topic_taxonomy = {
            "investasi": [
                "saham", "reksadana", "obligasi", "yield", "dividen", "portfolio", "risk", "volatilitas",
                "crypto", "dca", "compound", "return", "alpha", "beta", "sharpe"
            ],
            "cashflow": [
                "cashflow", "arus kas", "burn rate", "saldo", "likuiditas", "tagihan", "gaji", "utang",
                "piutang", "cicilan", "budget", "anggaran", "defisit", "surplus"
            ],
            "makro": [
                "inflasi", "suku bunga", "bi rate", "fed", "resesi", "gdp", "pdb", "currency", "usd", "idr",
                "yield curve", "moneter", "fiskal"
            ],
            "risk": [
                "risiko", "anomaly", "fraud", "penipuan", "drawdown", "vaR", "stress test", "hedging",
                "stop loss", "exposure"
            ],
            "operasional": [
                "biaya", "opex", "capex", "efisiensi", "margin", "revenue", "net income", "assets", "liability",
                "reconciliation", "audit"
            ],
        }

        self.transformer_backend = None
        try:
            backend = TransformerNLPBackend(TransformerNLPConfig())
            if backend.is_ready:
                self.transformer_backend = backend
        except Exception as e:
            logger.error(f"Transformer backend init failed: {e}")
            self.transformer_backend = None

    def _calibrate_confidence(self, score: float, *, penalty: float = 0.0, floor: float = 0.0, ceil: float = 0.99) -> float:
        """Lightweight confidence calibration for more stable downstream gating."""
        try:
            s = float(score) - float(penalty)
        except Exception:
            s = 0.0
        s = max(0.0, min(1.0, s))
        # Temperature scaling style compression/expansion around 0.5
        t = max(0.2, min(2.5, self.confidence_temperature))
        z = (s - 0.5) / t + 0.5
        z = max(floor, min(ceil, z))
        return round(float(z), 4)

    def _build_intent_explanation(
        self,
        text: str,
        intent: str,
        source: str,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        if not self.explainability_enabled:
            return ""
        short_text = (text or "").strip()
        if len(short_text) > 80:
            short_text = short_text[:77] + "..."
        candidate_text = ""
        if candidates:
            top = sorted(candidates, key=lambda x: x.get("weighted", 0.0), reverse=True)[:2]
            candidate_text = " | ".join(
                f"{c.get('intent')}={round(float(c.get('weighted', 0.0)), 3)}" for c in top
            )
        if candidate_text:
            return f"intent={intent}; source={source}; top={candidate_text}; text='{short_text}'"
        return f"intent={intent}; source={source}; text='{short_text}'"

    def _detect_language_safe(self, text: str) -> str:
        backend = self.transformer_backend
        if backend and hasattr(backend, "detect_language"):
            try:
                return backend.detect_language(text)
            except Exception:
                pass
        return "unknown"

    def _intent_ensemble_classify(
        self,
        text: str,
        regex_intent: Dict[str, Any],
        transformer_intent: Optional[Dict[str, Any]],
        llm_intent: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Ensemble voting from deterministic + transformer + LLM classifiers."""
        votes: Dict[str, float] = {}
        details: List[Dict[str, Any]] = []

        def add_vote(src: str, payload: Optional[Dict[str, Any]], weight: float):
            if not payload:
                return
            intent = payload.get("intent")
            if not intent:
                return
            raw_conf = float(payload.get("confidence", 0.0))
            weighted = max(0.0, raw_conf) * weight
            votes[intent] = votes.get(intent, 0.0) + weighted
            details.append(
                {
                    "source": src,
                    "intent": intent,
                    "raw_confidence": round(raw_conf, 4),
                    "weighted": round(weighted, 4),
                }
            )

        add_vote("regex", regex_intent, 0.45)
        add_vote("transformer", transformer_intent, 0.4)
        add_vote("llm", llm_intent, 0.15)

        if not votes:
            return {"intent": "UNKNOWN", "confidence": 0.0, "source": "none", "candidates": []}

        best_intent = max(votes, key=votes.get)
        total = sum(votes.values()) or 1e-9
        confidence = votes[best_intent] / total
        confidence = self._calibrate_confidence(confidence, floor=0.0, ceil=0.98)
        return {
            "intent": best_intent,
            "confidence": confidence,
            "source": "ensemble",
            "candidates": details,
            "language": (
                (transformer_intent or {}).get("language")
                or (llm_intent or {}).get("language")
                or self._detect_language_safe(text)
            ),
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

    def process_text(self, text: str):
        """
        Parses amount, category, and transaction type from raw text.
        Returns: (amount, category, type)
        """
        norm_text = self.normalize_text(text)
        
        # 1. Extract Amount
        amounts = re.findall(r'\d+', norm_text)
        amount = float(amounts[0]) if amounts else 0.0
        
        # 2. Detect Category
        category, _ = self._detect_category(norm_text)
        
        # 3. Detect Type
        tx_type = "expense"
        income_keywords = ["gaji", "masuk", "bonus", "terima", "transfer dari"]
        if any(k in norm_text for k in income_keywords):
            tx_type = "income"
            
        return amount, category, tx_type

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
            
        # LLM refinement is optional to keep production latency low.
        if self.groq_enabled and self.llm_sentiment_enabled:
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
        if regex_intent["confidence"] >= 0.96:
            regex_intent["confidence"] = self._calibrate_confidence(regex_intent["confidence"], ceil=0.99)
            regex_intent["sentiment"] = sentiment_data
            regex_intent["source"] = "regex"
            regex_intent["explanation"] = self._build_intent_explanation(text, regex_intent["intent"], "regex")
            return regex_intent

        transformer_intent = None
        llm_intent = None

        # 4. Transformer Path: multilingual zero-shot with contextual understanding.
        if self.transformer_backend and self.transformer_backend.is_ready:
            transformer_intent = self.transformer_backend.classify_intent(
                text=text,
                intent_descriptions=self._intent_descriptions,
            )
            if transformer_intent:
                transformer_intent["confidence"] = self._calibrate_confidence(
                    transformer_intent.get("confidence", 0.0),
                    ceil=0.99
                )
            if transformer_intent and transformer_intent.get("confidence", 0.0) >= 0.83 and not self.intent_ensemble_enabled:
                transformer_intent["sentiment"] = sentiment_data
                transformer_intent["source"] = transformer_intent.get("source") or "transformer"
                transformer_intent["explanation"] = self._build_intent_explanation(
                    text, transformer_intent.get("intent", "UNKNOWN"), transformer_intent["source"]
                )
                return transformer_intent
            
        # 5. Slow Path: LLM Fallback (Priority 3)
        # Only when confidence is still uncertain.
        needs_llm = (
            self.groq_enabled
            and (
                regex_intent.get("confidence", 0.0) < 0.85
                or not transformer_intent
                or transformer_intent.get("confidence", 0.0) < 0.8
            )
        )
        if needs_llm:
            llm_intent = self._llm_classify_intent(text) # Pass original text for better context
            if llm_intent:
                llm_intent["confidence"] = self._calibrate_confidence(llm_intent.get("confidence", 0.0), ceil=0.95)
            if llm_intent and llm_intent.get('confidence', 0) >= 0.78 and not self.intent_ensemble_enabled:
                llm_intent["sentiment"] = sentiment_data
                llm_intent["source"] = "llm"
                llm_intent["explanation"] = self._build_intent_explanation(text, llm_intent["intent"], "llm")
                return llm_intent

        # 5b. Ensemble voting path (regex + transformer + llm)
        if self.intent_ensemble_enabled:
            ensemble = self._intent_ensemble_classify(text, regex_intent, transformer_intent, llm_intent)
            if ensemble.get("confidence", 0.0) >= 0.62:
                ensemble["sentiment"] = sentiment_data
                ensemble["explanation"] = self._build_intent_explanation(
                    text,
                    ensemble.get("intent", "UNKNOWN"),
                    ensemble.get("source", "ensemble"),
                    candidates=ensemble.get("candidates"),
                )
                return ensemble
        
        # 6. Small Talk Fallback (New)
        small_talk_res = self.handle_small_talk(text)
        if small_talk_res:
            return {
                "intent": "SMALL_TALK",
                "response": small_talk_res,
                "confidence": self._calibrate_confidence(1.0, ceil=0.99),
                "sentiment": sentiment_data,
                "source": "small_talk",
                "explanation": self._build_intent_explanation(text, "SMALL_TALK", "small_talk"),
            }

        # 7. Fallback if everything fails
        if regex_intent["confidence"] > 0.0:
            regex_intent["sentiment"] = sentiment_data
            regex_intent["confidence"] = self._calibrate_confidence(regex_intent["confidence"], ceil=0.9)
            regex_intent["source"] = "regex_fallback"
            regex_intent["explanation"] = self._build_intent_explanation(text, regex_intent["intent"], "regex_fallback")
            return regex_intent
            
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "sentiment": sentiment_data,
            "source": "fallback",
            "explanation": self._build_intent_explanation(text, "UNKNOWN", "fallback"),
        }

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

        # Correction (eh salah, bukan 5rb tapi 50rb)
        if self._intents_map["correction"].search(text) and self._extract_amount(text) > 0:
            return {"intent": "CORRECTION", "confidence": 0.9}
            
        # Undo (undo, batal)
        if self._intents_map["undo"].search(text) and len(text.split()) <= 3:
            return {"intent": "UNDO", "confidence": 0.95}
            
        # Executive Mode (ringkas, tajam)
        if self._intents_map["executive_mode"].search(text) and len(text.split()) <= 4:
            return {"intent": "EXECUTIVE_MODE", "confidence": 0.9}
            
        # Elite Analysis (market, risk)
        if self._intents_map["elite_analysis"].search(text):
            return {"intent": "ELITE_ANALYSIS", "confidence": 0.95}
            
        # Investment Opportunities
        if self._intents_map["investment_opps"].search(text):
            return {"intent": "INVESTMENT_OPPS", "confidence": 0.9}
            
        # Document Analysis
        if self._intents_map["doc_analysis"].search(text):
            return {"intent": "DOC_ANALYSIS", "confidence": 0.9}

        # Split Bill (makan bareng total 450rb bagi 3)
        if self._intents_map["split_bill"].search(text) and self._extract_amount(text) > 0:
            return {"intent": "SPLIT_BILL", "confidence": 0.9}

        # Bulk entry check (multiple lines or separators)
        if "\n" in text or (text.count(',') >= 2 and self._extract_amount(text) > 0):
             # High probability of bulk entry
             return {"intent": "BULK_TRANSACTION", "confidence": 0.8}

        # History / Riwayat
        if any(kw in text for kw in ["history", "riwayat", "rekap transaksi", "daftar transaksi", "list transaksi", "tunjukin transaksi"]):
            return {"intent": "HISTORY", "confidence": 0.95}

        # Delete Transaction
        if any(kw in text for kw in ["hapus", "delete", "buang", "ilangin"]) and any(kw in text for kw in ["transaksi", "data", "catatan"]):
            return {"intent": "DELETE_TRANSACTION", "confidence": 0.9}

        # Profile / Gamification
        if any(kw in text for kw in ["profil", "profile", "rank", "level", "xp", "badge", "pencapaian", "skor"]):
            return {"intent": "PROFILE", "confidence": 0.95}

        # Auth / Web Token
        if any(kw in text for kw in ["login", "token", "web", "akses", "masuk ke web"]):
            return {"intent": "AUTH", "confidence": 0.9}

        # Question Answering (Conversational)
        if any(kw in text for kw in ["apa itu", "bagaimana", "gimana", "jelasin", "kenapa", "jelaskan", "mengapa"]) and len(text.split()) >= 3:
            return {"intent": "QUESTION", "confidence": 0.9}

        # Summarization
        if any(kw in text for kw in ["rangkum", "summarize", "rekap poin", "singkatkan", "ringkaskan"]):
            return {"intent": "SUMMARIZE", "confidence": 0.9}

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
        
        # Stricter Help Detection: only if it's a short command or clear help request
        help_keywords = ["help", "tolong", "bantuan", "perintah", "command", "bisa apa"]
        if any(kw == text.strip() for kw in help_keywords) or (any(kw in text for kw in help_keywords) and len(text.split()) <= 3):
            return {"intent": "HELP", "confidence": 1.0}
            
        if self._intents_map["greeting"].search(text):
            return {"intent": "GREETING", "confidence": 1.0}
            
        return {"intent": "UNKNOWN", "confidence": 0.0}

    def _generate_error_message(self, context: str = "transaction") -> str:
        """Generates dynamic and conversational error messages."""
        if context == "transaction":
            variations = [
                "Nominalnya berapa ya? Contoh: 'kopi 25rb' ☕",
                "Aku butuh angka nominalnya nih. Coba ketik 'makan 50k' gitu.",
                "Berapa biayanya? Kasih tau aku ya, misal: 'bensin 100rb' ⛽",
                "Nominalnya jangan lupa ya! Contoh: 'nonton 75rb' 🎬",
                "Eh, nominalnya berapa? Aku belum dapet angkanya nih. 😊"
            ]
            return random.choice(variations)
        return "Aduh, aku bingung. Bisa diulang lebih jelas? 🙏"

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

    async def analyze_financial_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Multi-language Sentiment Analysis with intensity and emotion detection.
        Supports ID, EN, and other common languages.
        """
        if not self.groq_enabled:
            return {
                "language": "unknown",
                "sentiment": "NEUTRAL", 
                "emotion": "CALM",
                "intensity": "LOW",
                "score": 0.0, 
                "reason": "AI client not enabled (fallback)"
            }

        try:
            prompt = f"""
            Analyze the multi-language financial sentiment and emotion of this text.
            Text: "{text}"
            
            Task:
            1. Detect the language.
            2. Classify sentiment as: POSITIVE, NEGATIVE, or NEUTRAL.
            3. Detect specific financial emotion: OPTIMISM, FEAR, GREED, CONCERN, or CALM.
            4. Provide intensity (LOW, MEDIUM, HIGH).
            5. Calculate a score from -1.0 (very negative) to 1.0 (very positive).
            
            Return JSON: 
            {{
                "language": "detected_lang",
                "sentiment": "class", 
                "emotion": "emotion_class",
                "intensity": "intensity_level",
                "score": float, 
                "reason": "brief explanation"
            }}
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            import json
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"Financial sentiment analysis failed: {e}")
            return {
                "language": "unknown",
                "sentiment": "NEUTRAL", 
                "emotion": "CALM",
                "intensity": "LOW",
                "score": 0.0, 
                "reason": f"Error: {str(e)}"
            }

    async def answer_question_with_reasoning(self, question: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Question Answering System with Chain-of-Thought reasoning capabilities.
        """
        if not self.groq_enabled:
            return {
                "answer": "Sistem AI sedang offline. Gunakan mode manual untuk sementara.", 
                "reasoning_steps": ["AI client disabled", "Checking local context", "Returning generic fallback"],
                "confidence": 0.0
            }

        try:
            prompt = f"""
            Answer the following financial question with detailed reasoning (Chain-of-Thought).
            Context (if any): {context or 'General financial knowledge'}
            Question: "{question}"
            
            Instructions:
            1. Think step-by-step to arrive at the answer.
            2. Provide clear, logical reasoning.
            3. Answer in the same language as the question.
            
            Return JSON:
            {{
                "reasoning_steps": ["step 1", "step 2", "..."],
                "answer": "The final concise answer",
                "confidence": 0.0-1.0
            }}
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.2
            )
            import json
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"QA Reasoning failed: {e}")
            return {
                "answer": "Gagal memproses pertanyaan.", 
                "reasoning_steps": [f"Error encountered: {str(e)}"],
                "confidence": 0.0
            }

    async def summarize_text(self, text: str, style: str = "concise") -> Dict[str, Any]:
        """
        Text Summarization with multiple styles: 'executive', 'creative', 'concise'.
        """
        if not self.groq_enabled:
            return {
                "summary": text[:100] + "...", 
                "style_applied": style,
                "key_takeaways": ["AI client disabled"]
            }

        styles_map = {
            "executive": "Professional, data-driven, focus on key metrics and bottom line.",
            "creative": "Engaging, storytelling style, using analogies and emojis.",
            "concise": "Very brief, bullet points only, maximum 3 points."
        }
        
        style_desc = styles_map.get(style, styles_map["concise"])

        try:
            prompt = f"""
            Summarize the following financial text using the specified style.
            Style: {style} ({style_desc})
            Text: "{text}"
            
            Return JSON:
            {{
                "summary": "The formatted summary text",
                "style_applied": "{style}",
                "key_takeaways": ["point 1", "point 2", "..."]
            }}
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.5
            )
            import json
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return {"summary": "Gagal merangkum teks.", "error": str(e)}

    async def extract_financial_entities(self, text: str) -> List[Dict[str, Any]]:
        """
        Financial Named Entity Recognition (NER) for stocks, tickers, currencies, and institutions.
        """
        if not self.groq_enabled:
            return []

        try:
            prompt = f"""
            Extract financial entities from this text (Indonesian or English).
            Text: "{text}"
            
            Identify:
            - TICKER (e.g. BBCA, AAPL)
            - INSTITUTION (e.g. Bank Mandiri, Goldman Sachs)
            - CURRENCY (e.g. IDR, USD)
            - FINANCIAL_INSTRUMENT (e.g. Obligasi, Reksadana, Stocks)
            - AMOUNT (e.g. 5 Miliar, $100)
            
            Return JSON list: [{{"entity": "text", "type": "label", "context": "context"}}]
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            import json
            res = json.loads(chat_completion.choices[0].message.content)
            return res.get("entities", [])
        except Exception as e:
            logger.error(f"Financial NER failed: {e}")
            return []

    def extract_transaction_data(self, text: str) -> Dict[str, Any]:
        """
        Extracts structured financial transaction data.
        Returns JSON-like dict.
        """
        # 0. Check for implicit type from classification
        classification = self.classify_intent(text)
        forced_type = classification.get("type")
        intent = classification.get("intent")

        passthrough_intents = {
            "ROAST_WALLET",
            "EXPORT_DATA",
            "WHAT_IF",
            "SET_MODE",
            "SET_REMINDER",
            "CHECK_BUDGET",
            "SET_GAJI",
            "UNDO",
            "EXECUTIVE_MODE",
            "ELITE_ANALYSIS",
            "INVESTMENT_OPPS",
            "DOC_ANALYSIS",
            "SET_BUDGET",
            "SET_BUDGET_ALERT",
            "QUERY_SUMMARY",
            "SHARING_INFO",
            "GREETING",
            "SMALL_TALK",
            "HELP",
            "STOP_NOTIF",
            "CANCEL",
            "ASK_FOR_NOTIF",
            "EDIT_TRANSACTION",
        }

        # Non-transaction intents should not go through transaction validation.
        if intent in passthrough_intents:
            return classification

        # 1. Handle Bulk Transactions
        if intent == "BULK_TRANSACTION":
            return {
                "intent": "BULK_TRANSACTION",
                "items": self.extract_bulk_transactions(text),
                "confidence": 0.95
            }

        # 2. Handle Split Bill
        if intent == "SPLIT_BILL":
            return self.extract_split_bill(text)

        # 3. Handle Correction
        if intent == "CORRECTION":
            data = self.extract_transaction_data_simple(text, forced_type)
            data["intent"] = "CORRECTION"
            return data

        # 4. Standard Extraction
        data = self.extract_transaction_data_simple(text, forced_type)
        data["intent"] = intent or "ADD_TRANSACTION"
        return data

    def extract_transaction_data_simple(self, text: str, forced_type: str = None) -> Dict[str, Any]:
        """Standard single transaction extraction logic with granular confidence and validation."""
        # 0. Ambiguity & Intent Disambiguation Layer
        ambiguous_keywords = ["transfer", "bayar", "kirim", "masuk", "bayarin"]
        is_ambiguous = any(kw in text.lower() for kw in ambiguous_keywords)

        # 1. Initial parsing
        text_norm = self.normalize_text(text)
        amount = self._extract_amount(text_norm)

        # 2. Advanced Extraction first for complex/ambiguous inputs.
        # Keep this before strict validation so LLM can rescue hard cases.
        if self.groq_enabled and (len(text.split()) > 4 or is_ambiguous):
             llm_data = self._llm_extract_entities(text)
             if llm_data and llm_data.get("amount"):
                 # Post-extraction validation & transformation
                 llm_data["type"] = forced_type or llm_data.get("type", "expense")
                 llm_data["date"] = self._extract_date(text)
                 llm_data["merchant"] = llm_data.get("merchant") or self.extract_merchant(text_norm)
                 llm_data["category"] = llm_data.get("category") or self._detect_category(text_norm)[0]

                 llm_amount = llm_data.get("amount") or 0
                 llm_complete = (
                     llm_amount > 0
                     and llm_data.get("category") != "Lain-lain"
                     and llm_data.get("merchant") != "Transaksi"
                 )
                 llm_data["is_partial"] = not llm_complete

                 # Logic for ambiguous terms
                 if is_ambiguous and llm_data.get("confidence", 0.9) > 0.7:
                     llm_data["needs_disambiguation"] = True
                     llm_data["confidence"] = 0.65
                 else:
                     llm_data["needs_disambiguation"] = is_ambiguous and llm_data.get("category") == "Lain-lain"
                 llm_data["confidence"] = self._calibrate_confidence(
                     llm_data.get("confidence", 0.85),
                     penalty=0.08 if is_ambiguous else 0.0,
                     ceil=0.97
                 )
                 llm_data["source"] = llm_data.get("source") or "llm_entities"
                 if self.explainability_enabled:
                     llm_data["explanation"] = (
                         f"source=llm_entities; ambiguous={is_ambiguous}; "
                         f"category={llm_data.get('category')}; merchant={llm_data.get('merchant')}"
                     )
                 return llm_data

        # 3. Transformer entity extraction for multilingual and context-heavy utterances.
        transformer_hint = None
        if self.transformer_backend and self.transformer_backend.is_ready and (
            amount <= 0 or is_ambiguous or len(text.split()) > 3
        ):
            transformer_hint = self.transformer_backend.extract_entities(
                text,
                categories=list(self.category_keywords.keys()),
            )
            if transformer_hint and transformer_hint.get("amount"):
                amount = float(transformer_hint["amount"])

        # 4. Heuristic Extraction (Standard)
        category, cat_conf = self._detect_category(text_norm)
        merchant = self.extract_merchant(text_norm)
        date = self._extract_date(text)

        if transformer_hint:
            hint_cat = transformer_hint.get("category")
            hint_merchant = transformer_hint.get("merchant")
            hint_conf = float(transformer_hint.get("confidence", 0.6))

            if category == "Lain-lain" and hint_cat and hint_cat != "Lain-lain":
                category = hint_cat
                cat_conf = max(cat_conf, min(0.95, hint_conf))

            if merchant == "Transaksi" and hint_merchant and hint_merchant != "Transaksi":
                merchant = hint_merchant

        # If no amount, keep partial detail (merchant/category) for follow-up merge flow.
        if amount <= 0:
            return {
                "amount": None,
                "type": forced_type,
                "category": category if category != "Lain-lain" else None,
                "merchant": merchant,
                "date": date,
                "confidence": self._calibrate_confidence(0.45 if merchant != "Transaksi" else 0.3, ceil=0.7),
                "is_partial": True,
                "needs_disambiguation": is_ambiguous and category == "Lain-lain",
                "error": self._generate_error_message("transaction"),
                "source": "heuristic_partial",
                "language": self._detect_language_safe(text),
                "explanation": (
                    f"amount_missing; category={category}; merchant={merchant}; "
                    f"transformer_hint={bool(transformer_hint)}"
                ) if self.explainability_enabled else ""
            }

        type_ = forced_type or ("income" if category == "Gaji" else "expense")
        is_complete = amount > 0 and category != "Lain-lain" and merchant != "Transaksi"

        return {
            "amount": amount,
            "type": type_,
            "category": category,
            "merchant": merchant,
            "date": date,
            "confidence": self._calibrate_confidence(
                min(0.95, cat_conf + 0.1) if is_complete else 0.5,
                penalty=0.07 if is_ambiguous else 0.0,
                ceil=0.97
            ),
            "is_partial": not is_complete,
            "needs_disambiguation": is_ambiguous and category == "Lain-lain",
            "source": "heuristic",
            "language": self._detect_language_safe(text),
            "explanation": (
                f"amount={amount}; category_conf={round(cat_conf, 3)}; "
                f"merchant={merchant}; ambiguous={is_ambiguous}; transformer_hint={bool(transformer_hint)}"
            ) if self.explainability_enabled else "",
        }

    def extract_split_bill(self, text: str) -> Dict[str, Any]:
        """Extracts split bill data: total, people count, and per-person share."""
        text_norm = self.normalize_text(text)
        total_amount = self._extract_amount(text_norm)
        
        # Extract number of people
        people_match = re.search(r'(\d+)\s*(?:orang|person|people|org)', text_norm)
        num_people = int(people_match.group(1)) if people_match else 1
        
        if num_people <= 0: num_people = 1
        
        per_person = total_amount / num_people
        category = self._detect_category(text_norm)
        merchant = self.extract_merchant(text_norm)
        date = self._extract_date(text)

        return {
            "intent": "SPLIT_BILL",
            "total_amount": total_amount,
            "num_people": num_people,
            "per_person": per_person,
            "category": category,
            "merchant": merchant,
            "date": date,
            "confidence": 0.95
        }

    def extract_bulk_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Uses LLM to parse multiple transactions from one message."""
        if not self.groq_enabled:
            # Basic fallback: split by newline and parse each
            results = []
            for line in text.split('\n'):
                if line.strip():
                    data = self.extract_transaction_data_simple(line)
                    if data.get("amount"):
                        results.append(data)
            return results

        try:
            prompt = f"""
            Extract all transactions from this message and return as a JSON list.
            Message: "{text}"
            
            JSON structure for each item:
            {{
                "amount": float,
                "category": string (Makanan, Minuman, Jajanan, Transportasi, Belanja, Tagihan, Lain-lain),
                "merchant": string,
                "type": "expense" or "income",
                "date": "YYYY-MM-DD" (Today is {self._extract_date("")})
            }}
            Return ONLY the JSON list.
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            import json
            res = json.loads(chat_completion.choices[0].message.content)
            # Handle different JSON structures from LLM
            if isinstance(res, dict) and "transactions" in res:
                return res["transactions"]
            if isinstance(res, dict) and "items" in res:
                return res["items"]
            if isinstance(res, list):
                return res
            return [res] if isinstance(res, dict) and res.get("amount") else []
        except Exception:
            return []

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
            category, _ = self._detect_category(user_message)
            if category != "Lain-lain":
                return {"new_value": category, "valid": True, "reason": None}
            return {"new_value": None, "valid": False, "reason": "Kategori tidak dikenal"}
            
        return {"new_value": None, "valid": False, "reason": "Field tidak valid"}

    def _detect_category(self, text: str) -> Tuple[str, float]:
        """Smarter category detection with improved keyword matching and confidence scoring"""
        if not text:
            return "Lain-lain", 0.0
            
        text = text.lower()
        
        # 1. Specific Keyword Override (Decision Intelligence)
        # Even if "beli" is present, "bensin" must be Transportasi
        overrides = {
            "bensin": "Transportasi",
            "pertalite": "Transportasi",
            "pertamax": "Transportasi",
            "parkir": "Transportasi",
            "ojol": "Transportasi",
            "listrik": "Tagihan",
            "wifi": "Tagihan",
            "token": "Tagihan",
            "pulsa": "Tagihan",
            "sedekah": "Sosial",
            "zakat": "Sosial",
            "donasi": "Sosial",
            "obat": "Kesehatan",
            "vitamin": "Kesehatan",
            "dokter": "Kesehatan",
            "makan": "Makanan",
            "nasi": "Makanan",
            "ayam": "Makanan",
            "bakso": "Makanan",
            "mie": "Makanan",
            "warung": "Makanan",
            "warteg": "Makanan",
            "padang": "Makanan",
            "nasgor": "Makanan"
        }
        for kw, cat in overrides.items():
            if kw in text:
                return cat, 0.98

        # 2. Exact Regex Match (Highest Confidence)
        for category, pattern in self._compiled_keywords.items():
            if pattern.search(text):
                return category, 0.95
        
        # 3. Heuristic: if text contains "beli" or "bayar" but no category found
        if any(kw in text for kw in ["beli", "bayar", "pesan", "checkout"]):
            return "Belanja", 0.75

        # 3. Fuzzy Match for Typos (e.g. "mkan" -> "makan")
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
                    return keyword_to_cat[matches[0]], 0.7

        # 4. Transformer semantic categorization fallback
        if self.transformer_backend and self.transformer_backend.is_ready:
            guess, tr_conf = self.transformer_backend.classify_category(
                text,
                list(self.category_keywords.keys()),
            )
            if guess != "Lain-lain":
                return guess, tr_conf

        # 5. LLM Deep Categorization Fallback
        if self.groq_enabled and self.llm_category_enabled:
            guess, llm_conf = self._llm_guess_category(text)
            return guess, llm_conf
            
        return "Lain-lain", 0.3

    def _llm_guess_category(self, text: str) -> Tuple[str, float]:
        """Uses LLM to guess category with confidence scoring"""
        try:
            merchant = self.extract_merchant(text)
            prompt = f"""
            Guess the financial category for this merchant: "{merchant}" 
            Choose ONLY ONE from: Makanan, Minuman, Jajanan, Transportasi, Belanja, Tagihan, Kesehatan, Lifestyle, Sosial, Pendidikan, Maintenance, Investasi, Gaji.
            Context: {text}
            Return JSON: {{"category": "name", "confidence": 0.0-1.0}}
            """
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            import json
            res = json.loads(chat_completion.choices[0].message.content)
            guess = res.get("category", "Lain-lain")
            conf = float(res.get("confidence", 0.6))
            if guess in self.category_keywords:
                return guess, conf
        except Exception:
            pass
        return "Lain-lain", 0.5

    def _extract_date(self, text: str) -> str:
        """Extracts date from text, handling relative time expressions."""
        from datetime import datetime, timedelta
        now = datetime.now()
        text = text.lower()
        
        # Relative dates
        if "kemarin" in text:
            target = now - timedelta(days=1)
            return target.strftime("%Y-%m-%d")
        if "lusa" in text:
            target = now + timedelta(days=2)
            return target.strftime("%Y-%m-%d")
        if "tadi" in text or "barusan" in text or "tadi pagi" in text or "tadi siang" in text:
            return now.strftime("%Y-%m-%d")
        if "minggu lalu" in text:
            target = now - timedelta(weeks=1)
            return target.strftime("%Y-%m-%d")
            
        # Regex for "tanggal 15" or "tgl 15"
        tgl_match = re.search(r'(?:tanggal|tgl)\s*(\d{1,2})', text)
        if tgl_match:
            day = int(tgl_match.group(1))
            try:
                # Assume current month, if day > current day, maybe it's last month? 
                # Keep it simple for now: current month
                target = now.replace(day=day)
                return target.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Regex for "2 hari lalu"
        ago_match = re.search(r'(\d+)\s*hari\s*lalu', text)
        if ago_match:
            days = int(ago_match.group(1))
            target = now - timedelta(days=days)
            return target.strftime("%Y-%m-%d")

        return now.strftime("%Y-%m-%d")

    def _extract_amount(self, text: str) -> float:
        val = parse_primary_amount_id(text)
        if val is None:
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    def extract_merchant(self, text: str) -> Optional[str]:
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

    def classify_intent_with_context(
        self,
        text: str,
        context_messages: Optional[Sequence[str]] = None,
        state: str = "IDLE",
    ) -> Dict[str, Any]:
        """Context-aware intent classification using transformer attention when available."""
        # Ensemble with contextual message history for better multi-turn robustness.
        normalized = self.normalize_text(text)
        regex_intent = self._regex_classify(normalized)
        transformer_intent = None
        llm_intent = None
        sentiment = self.analyze_sentiment(text)

        if self.transformer_backend and self.transformer_backend.is_ready:
            transformer_intent = self.transformer_backend.classify_intent(
                text=text,
                intent_descriptions=self._intent_descriptions,
                context_messages=context_messages,
            )
            if transformer_intent:
                transformer_intent["confidence"] = self._calibrate_confidence(
                    transformer_intent.get("confidence", 0.0), ceil=0.98
                )
            # Strong transformer signal can short-circuit to preserve deterministic behavior.
            if transformer_intent and transformer_intent.get("confidence", 0.0) >= 0.9:
                transformer_intent["sentiment"] = sentiment
                transformer_intent["source"] = transformer_intent.get("source") or "transformer_context"
                transformer_intent["explanation"] = self._build_intent_explanation(
                    text, transformer_intent.get("intent", "UNKNOWN"), transformer_intent["source"]
                )
                return transformer_intent

        if self.groq_enabled and self.intent_ensemble_enabled and (
            regex_intent.get("confidence", 0.0) < 0.9
            or (transformer_intent and transformer_intent.get("confidence", 0.0) < 0.85)
        ):
            llm_intent = self._llm_classify_intent(text)
            if llm_intent:
                llm_intent["confidence"] = self._calibrate_confidence(llm_intent.get("confidence", 0.0), ceil=0.95)

        if self.intent_ensemble_enabled:
            ens = self._intent_ensemble_classify(text, regex_intent, transformer_intent, llm_intent)
            if ens.get("confidence", 0.0) >= 0.6:
                ens["sentiment"] = sentiment
                ens["explanation"] = self._build_intent_explanation(
                    text, ens.get("intent", "UNKNOWN"), ens.get("source", "ensemble"), ens.get("candidates")
                )
                return ens

        if transformer_intent and transformer_intent.get("confidence", 0.0) >= 0.72:
            transformer_intent["sentiment"] = sentiment
            transformer_intent["source"] = transformer_intent.get("source") or "transformer_context"
            transformer_intent["explanation"] = self._build_intent_explanation(
                text, transformer_intent.get("intent", "UNKNOWN"), transformer_intent["source"]
            )
            return transformer_intent

        return self.hybrid_classify(text, state)

    def extract_transaction_data_with_context(
        self,
        text: str,
        context_messages: Optional[Sequence[str]] = None,
        forced_type: str = None,
    ) -> Dict[str, Any]:
        """Context-aware transaction extraction for multi-turn conversations."""
        data = self.extract_transaction_data_simple(text, forced_type=forced_type)
        if not context_messages or not data.get("is_partial"):
            return data

        # Merge with short context history to recover omitted fields (e.g. amount on next turn).
        composed_text = " ".join([m for m in context_messages[-2:] if m] + [text]).strip()
        if not composed_text:
            return data
        enriched = self.extract_transaction_data_simple(composed_text, forced_type=forced_type)
        for key in ["amount", "category", "merchant", "date", "type"]:
            if (not data.get(key) or data.get(key) in ("Transaksi", "Lain-lain")) and enriched.get(key):
                data[key] = enriched[key]
        data["confidence"] = max(data.get("confidence", 0.0), enriched.get("confidence", 0.0))
        data["is_partial"] = not (data.get("amount") and data.get("merchant") and data.get("merchant") != "Transaksi")
        if not data["is_partial"]:
            data.pop("error", None)
        return data

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = int(round((pct / 100.0) * (len(ordered) - 1)))
        idx = max(0, min(idx, len(ordered) - 1))
        return float(ordered[idx])

    @staticmethod
    def _is_present(value: Any) -> bool:
        return value is not None and value != "" and value != "Transaksi" and value != "Lain-lain"

    @staticmethod
    def _compute_classification_metrics_fallback(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
        labels = sorted(set(y_true) | set(y_pred))
        label_to_idx = {label: idx for idx, label in enumerate(labels)}
        matrix = [[0 for _ in labels] for _ in labels]

        for t, p in zip(y_true, y_pred):
            matrix[label_to_idx[t]][label_to_idx[p]] += 1

        per_precision = []
        per_recall = []
        per_f1 = []
        correct = 0
        total = len(y_true)

        for i, label in enumerate(labels):
            tp = matrix[i][i]
            fp = sum(row[i] for row in matrix) - tp
            fn = sum(matrix[i]) - tp

            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-9)
            per_precision.append(precision)
            per_recall.append(recall)
            per_f1.append(f1)

        for t, p in zip(y_true, y_pred):
            if t == p:
                correct += 1

        return {
            "labels": labels,
            "confusion_matrix": matrix,
            "accuracy": correct / max(total, 1),
            "macro_precision": sum(per_precision) / max(len(per_precision), 1),
            "macro_recall": sum(per_recall) / max(len(per_recall), 1),
            "macro_f1": sum(per_f1) / max(len(per_f1), 1),
        }

    def evaluate_intent_benchmark(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate intent classification quality with production-oriented metrics.
        Expected sample format: {"text": "...", "intent": "ADD_TRANSACTION"}.
        """
        if not samples:
            return {
                "samples": 0,
                "accuracy": 0.0,
                "macro_precision": 0.0,
                "macro_recall": 0.0,
                "macro_f1": 0.0,
                "latency_p50_ms": 0.0,
                "latency_p95_ms": 0.0,
                "confusion_matrix": [],
                "labels": [],
            }

        y_true: List[str] = []
        y_pred: List[str] = []
        latencies: List[float] = []

        for row in samples:
            text = str(row.get("text", "")).strip()
            expected = str(row.get("intent", "UNKNOWN"))
            context_messages = row.get("context_messages") or row.get("context") or []
            t0 = time.perf_counter()
            pred = self.classify_intent_with_context(text, context_messages=context_messages)
            latencies.append((time.perf_counter() - t0) * 1000.0)
            y_true.append(expected)
            y_pred.append(str(pred.get("intent", "UNKNOWN")))
        try:
            from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

            labels = sorted(set(y_true) | set(y_pred))
            macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
                y_true, y_pred, average="macro", zero_division=0
            )
            accuracy = float(accuracy_score(y_true, y_pred))
            matrix = confusion_matrix(y_true, y_pred, labels=labels).tolist()
        except Exception:
            fallback = self._compute_classification_metrics_fallback(y_true, y_pred)
            labels = fallback["labels"]
            macro_p = fallback["macro_precision"]
            macro_r = fallback["macro_recall"]
            macro_f1 = fallback["macro_f1"]
            accuracy = fallback["accuracy"]
            matrix = fallback["confusion_matrix"]

        return {
            "samples": len(samples),
            "accuracy": round(float(accuracy), 4),
            "macro_precision": round(float(macro_p), 4),
            "macro_recall": round(float(macro_r), 4),
            "macro_f1": round(float(macro_f1), 4),
            "latency_p50_ms": round(self._percentile(latencies, 50.0), 2),
            "latency_p95_ms": round(self._percentile(latencies, 95.0), 2),
            "confusion_matrix": matrix,
            "labels": labels,
        }

    def evaluate_multilingual_robustness(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates intent quality split by language.
        Expected sample format: {"text": "...", "intent": "...", "language": "id|en|..."}.
        """
        if not samples:
            return {"samples": 0, "by_language": {}, "overall_accuracy": 0.0}

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in samples:
            lang = str(row.get("language") or "unknown").lower().strip() or "unknown"
            grouped.setdefault(lang, []).append(row)

        by_language: Dict[str, Any] = {}
        total = 0
        weighted_acc = 0.0
        for lang, rows in grouped.items():
            report = self.evaluate_intent_benchmark(rows)
            by_language[lang] = {
                "samples": report["samples"],
                "accuracy": report["accuracy"],
                "macro_f1": report["macro_f1"],
                "latency_p95_ms": report["latency_p95_ms"],
            }
            total += report["samples"]
            weighted_acc += report["accuracy"] * report["samples"]

        return {
            "samples": total,
            "overall_accuracy": round(weighted_acc / max(total, 1), 4),
            "by_language": by_language,
        }

    def evaluate_transaction_extraction(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate transaction extraction quality.
        Expected format: {"text": "...", "amount": 20000, "category": "...", "merchant": "..."}.
        """
        if not samples:
            return {
                "samples": 0,
                "amount_mae": 0.0,
                "category_accuracy": 0.0,
                "merchant_accuracy": 0.0,
                "field_precision": 0.0,
                "field_recall": 0.0,
                "field_f1": 0.0,
            }

        amount_errors: List[float] = []
        category_total = 0
        category_hits = 0
        merchant_total = 0
        merchant_hits = 0
        tp = 0
        fp = 0
        fn = 0

        for row in samples:
            text = str(row.get("text", "")).strip()
            expected = {
                "amount": row.get("amount"),
                "category": row.get("category"),
                "merchant": row.get("merchant"),
            }
            pred = self.extract_transaction_data(text)

            exp_amount = expected.get("amount")
            pred_amount = pred.get("amount")
            if exp_amount is not None:
                if pred_amount is not None:
                    amount_errors.append(abs(float(exp_amount) - float(pred_amount)))
                else:
                    amount_errors.append(abs(float(exp_amount)))

            if expected.get("category") is not None:
                category_total += 1
                if str(pred.get("category")) == str(expected.get("category")):
                    category_hits += 1

            if expected.get("merchant") is not None:
                merchant_total += 1
                if str(pred.get("merchant", "")).strip().lower() == str(expected.get("merchant", "")).strip().lower():
                    merchant_hits += 1

            for field in ("amount", "category", "merchant"):
                pred_present = self._is_present(pred.get(field))
                exp_present = self._is_present(expected.get(field))
                if pred_present and exp_present:
                    tp += 1
                elif pred_present and not exp_present:
                    fp += 1
                elif (not pred_present) and exp_present:
                    fn += 1

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)

        return {
            "samples": len(samples),
            "amount_mae": round(sum(amount_errors) / max(len(amount_errors), 1), 2),
            "category_accuracy": round(category_hits / max(category_total, 1), 4),
            "merchant_accuracy": round(merchant_hits / max(merchant_total, 1), 4),
            "field_precision": round(precision, 4),
            "field_recall": round(recall, 4),
            "field_f1": round(f1, 4),
        }

    def benchmark_production_inference(self, texts: List[str], rounds: int = 1) -> Dict[str, Any]:
        """Benchmark latency/throughput for production deployment checks."""
        if not texts:
            return {"samples": 0, "classify_p95_ms": 0.0, "extract_p95_ms": 0.0, "throughput_qps": 0.0}

        classify_latencies: List[float] = []
        extract_latencies: List[float] = []
        started = time.perf_counter()
        total_calls = 0

        for _ in range(max(1, rounds)):
            for text in texts:
                t0 = time.perf_counter()
                self.hybrid_classify(text)
                classify_latencies.append((time.perf_counter() - t0) * 1000.0)
                t1 = time.perf_counter()
                self.extract_transaction_data(text)
                extract_latencies.append((time.perf_counter() - t1) * 1000.0)
                total_calls += 2

        elapsed = max(time.perf_counter() - started, 1e-9)
        result = {
            "samples": len(texts) * max(1, rounds),
            "classify_p50_ms": round(self._percentile(classify_latencies, 50.0), 2),
            "classify_p95_ms": round(self._percentile(classify_latencies, 95.0), 2),
            "extract_p50_ms": round(self._percentile(extract_latencies, 50.0), 2),
            "extract_p95_ms": round(self._percentile(extract_latencies, 95.0), 2),
            "throughput_qps": round(total_calls / elapsed, 2),
        }
        if self.transformer_backend and self.transformer_backend.is_ready:
            result["transformer_intent"] = self.transformer_backend.benchmark_intent_latency(
                texts=texts,
                intent_descriptions=self._intent_descriptions,
                rounds=rounds,
            )
        return result

    def audit_nlp_capabilities(self) -> Dict[str, Any]:
        """
        Audit current NLP stack, highlight weaknesses, and provide upgrade priorities.
        """
        features = {
            "regex_intent": True,
            "transformer_backend": bool(self.transformer_backend and self.transformer_backend.is_ready),
            "llm_intent_fallback": bool(self.groq_enabled),
            "ensemble_intent": bool(self.intent_ensemble_enabled),
            "confidence_calibration": True,
            "explainability": bool(self.explainability_enabled),
            "context_understanding": True,
            "multilingual_support": bool(self.transformer_backend and self.transformer_backend.is_ready),
        }

        weaknesses = []
        if not features["transformer_backend"]:
            weaknesses.append("Transformer backend belum aktif; semantic understanding masih terbatas.")
        if not self.groq_enabled:
            weaknesses.append("LLM fallback nonaktif; reasoning untuk pertanyaan kompleks menurun.")
        if not self.llm_category_enabled:
            weaknesses.append("LLM category guessing dimatikan; kasus edge-domain bisa underfit.")
        if not self.intent_ensemble_enabled:
            weaknesses.append("Intent ensemble nonaktif; robust voting lintas model tidak berjalan.")

        priorities = [
            "Aktifkan transformer backend + model multilingual berkualitas.",
            "Bangun fine-tuning set dari data produksi (hard examples + multilingual).",
            "Kalibrasi confidence per intent agar threshold lebih presisi.",
            "Tambahkan offline eval rutin: macro-F1, per-language accuracy, dan latency p95.",
        ]

        return {
            "features": features,
            "weaknesses": weaknesses,
            "improvement_priorities": priorities,
        }

    def _analyze_topic_domains(self, text: str, context_messages: Optional[Sequence[str]] = None) -> Dict[str, float]:
        corpus = " ".join([text] + list(context_messages or [])).lower()
        scores: Dict[str, float] = {}
        for topic, keywords in self.topic_taxonomy.items():
            hits = sum(1 for kw in keywords if kw in corpus)
            if hits > 0:
                scores[topic] = round(min(1.0, hits / max(len(keywords) * 0.25, 1.0)), 4)
        if not scores:
            scores["general_finance"] = 0.2
        return scores

    def _complexity_score(self, text: str, topic_scores: Dict[str, float]) -> float:
        tokens = re.findall(r"\b\w+\b", (text or "").lower())
        long_words = sum(1 for t in tokens if len(t) >= 8)
        numeric_tokens = sum(1 for t in tokens if any(ch.isdigit() for ch in t))
        topic_depth = len([k for k, v in topic_scores.items() if v >= 0.35])
        base = (
            0.15
            + min(0.35, len(tokens) / 80.0)
            + min(0.2, long_words / 25.0)
            + min(0.15, numeric_tokens / 10.0)
            + min(0.25, topic_depth / 5.0)
        )
        if self.transformer_backend:
            attn = self.transformer_backend.attention_summary(text)
            entropy = float((attn or {}).get("attention_entropy", 0.0))
            # High entropy usually indicates broader semantic spread -> slightly more complex.
            base += min(0.12, entropy * 0.12)
        return round(max(0.0, min(1.0, base)), 4)

    def _reasoning_strategy(self, intent: str, complexity: float, confidence: float) -> str:
        if confidence < 0.55:
            return "clarify_first"
        if intent in {"ADD_TRANSACTION", "CORRECTION"} and complexity < 0.45:
            return "direct_execution"
        if complexity >= 0.75:
            return "step_by_step_advisory"
        if intent in {"QUERY_SUMMARY", "CHECK_BUDGET", "ELITE_ANALYSIS", "INVESTMENT_OPPS"}:
            return "analytical_response"
        return "concise_response"

    def deep_understanding_analysis(
        self,
        text: str,
        context_messages: Optional[Sequence[str]] = None,
        state: str = "IDLE",
    ) -> Dict[str, Any]:
        """
        High-level semantic analysis for complex multi-topic user messages.
        Returns intent, transaction extraction, domain map, complexity, and response strategy.
        """
        context_messages = list(context_messages or [])
        intent_data = self.classify_intent_with_context(text, context_messages=context_messages, state=state)
        tx_data = self.extract_transaction_data_with_context(
            text, context_messages=context_messages, forced_type=intent_data.get("type")
        )

        topic_scores = self._analyze_topic_domains(text, context_messages=context_messages)
        complexity = self._complexity_score(text, topic_scores)
        confidence = float(intent_data.get("confidence", 0.0))
        strategy = self._reasoning_strategy(intent_data.get("intent", "UNKNOWN"), complexity, confidence)
        dominant_topics = [k for k, _ in sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)[:3]]

        return {
            "intent": intent_data.get("intent", "UNKNOWN"),
            "intent_confidence": confidence,
            "intent_source": intent_data.get("source", "unknown"),
            "transaction": tx_data,
            "complexity_score": complexity,
            "topic_scores": topic_scores,
            "dominant_topics": dominant_topics,
            "language": intent_data.get("language", self._detect_language_safe(text)),
            "recommended_strategy": strategy,
            "reasoning_trace": {
                "intent_explanation": intent_data.get("explanation", ""),
                "tx_explanation": tx_data.get("explanation", ""),
            },
        }

    def build_finetuning_corpus(
        self,
        samples: List[Dict[str, Any]],
        *,
        include_context: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Prepare fine-tuning corpus format from production samples.
        Input sample fields expected:
        - text
        - intent
        - category (optional)
        - amount (optional)
        - merchant (optional)
        - language (optional)
        - context_messages (optional)
        """
        corpus: List[Dict[str, Any]] = []
        for row in samples:
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            context_messages = row.get("context_messages") or []
            prompt = text
            if include_context and context_messages:
                ctx = " </s> ".join(str(x) for x in context_messages[-3:])
                prompt = f"[CTX] {ctx} [QUERY] {text}"
            completion = {
                "intent": str(row.get("intent", "UNKNOWN")),
                "category": row.get("category"),
                "amount": row.get("amount"),
                "merchant": row.get("merchant"),
                "language": row.get("language") or self._detect_language_safe(text),
            }
            corpus.append({"input": prompt, "output": completion})
        return corpus

    def get_finetuning_recipe(self) -> Dict[str, Any]:
        """
        Returns recommended production-grade fine-tuning recipe.
        """
        return {
            "base_models": {
                "intent_multilingual": "joeddav/xlm-roberta-large-xnli",
                "ner_multilingual": "Davlan/xlm-roberta-base-ner-hrl",
                "embedding_context": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            },
            "training_strategy": {
                "method": "PEFT-LoRA",
                "batch_size": 16,
                "learning_rate": 2e-5,
                "epochs": 3,
                "warmup_ratio": 0.1,
                "max_length": 192,
                "early_stopping_patience": 2,
            },
            "dataset_guidelines": {
                "min_samples": 20000,
                "language_mix": {"id": 0.65, "en": 0.25, "other": 0.10},
                "hard_examples_ratio": 0.3,
                "contextual_samples_ratio": 0.4,
            },
            "evaluation_targets": {
                "intent_macro_f1": 0.9,
                "transaction_field_f1": 0.9,
                "latency_p95_ms_cpu": 180,
            },
        }

    # Compatibility alias for classify_intent
    def classify_intent(self, text: str, state: str = "IDLE") -> Dict[str, Any]:
        return self.hybrid_classify(text, state)
