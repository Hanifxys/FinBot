import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from groq import AsyncGroq

from config import CATEGORIES, GROQ_API_KEY
from modules.amounts import parse_primary_amount_id
from modules.transformer_nlp import TransformerNLPBackend, TransformerNLPConfig

try:
    from modules.redis_mgr import RedisManager
except Exception:
    class RedisManager:  # type: ignore
        def __init__(self):
            self.client = None

logger = logging.getLogger(__name__)


class AIEngine:
    """
    Production AI Engine with:
    - adaptive model routing (quality vs latency),
    - circuit breaker + retry/backoff,
    - transformer-assisted multilingual understanding,
    - context prioritization + attention hints,
    - strict schema coercion/validation,
    - benchmark and evaluation utilities.
    """

    QUALITY_MODEL = "llama-3.3-70b-versatile"
    FAST_MODEL = "llama-3.1-8b-instant"
    MAX_RETRIES = 2
    TIMEOUT = 20
    CONFIDENCE_THRESHOLD = 0.65
    CIRCUIT_BREAK_LIMIT = 5
    CIRCUIT_OPEN_SECONDS = 60
    CACHE_TTL = 120
    MAX_CONTEXT_MESSAGES = 6

    def __init__(self):
        self._client = None
        self.redis = RedisManager()
        self.failure_count = 0
        self.circuit_open_until = 0
        self.transformer_backend = None
        try:
            backend = TransformerNLPBackend(TransformerNLPConfig())
            if backend.is_ready:
                self.transformer_backend = backend
        except Exception as e:
            logger.error(f"Transformer backend init failed in AIEngine: {e}")

    # -----------------------------------
    # CLIENT INIT
    # -----------------------------------

    @property
    def client(self):
        if self._client is None and GROQ_API_KEY:
            try:
                self._client = AsyncGroq(
                    api_key=GROQ_API_KEY,
                    timeout=self.TIMEOUT,
                    max_retries=0,
                )
            except Exception as e:
                logger.error(f"Groq init failed: {e}")
                self._client = None
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

    # -----------------------------------
    # CIRCUIT BREAKER
    # -----------------------------------

    def _is_circuit_open(self):
        return time.time() < self.circuit_open_until

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.CIRCUIT_BREAK_LIMIT:
            self.circuit_open_until = time.time() + self.CIRCUIT_OPEN_SECONDS
            logger.warning(f"AI circuit breaker opened for {self.CIRCUIT_OPEN_SECONDS} seconds")

    def _record_success(self):
        self.failure_count = 0

    # -----------------------------------
    # MODEL + CONTEXT
    # -----------------------------------

    def _select_model(self, task: str, prefer_speed: bool = False) -> str:
        if prefer_speed:
            return self.FAST_MODEL
        if task in {"chat", "insight"}:
            return self.QUALITY_MODEL
        if task in {"parse", "intent"}:
            return self.FAST_MODEL
        return self.QUALITY_MODEL

    @staticmethod
    def _stable_hash(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:20]

    def _get_language(self, text: str) -> str:
        if self.transformer_backend:
            return self.transformer_backend.detect_language(text or "")
        text_l = (text or "").lower()
        if re.search(r"\b(saya|aku|kamu|uang|makan|budget|laporan)\b", text_l):
            return "id"
        if re.search(r"\b(i|you|money|expense|budget|report)\b", text_l):
            return "en"
        return "unknown"

    def _build_attention_hint(self, text: str) -> str:
        if not self.transformer_backend:
            return ""
        attn = self.transformer_backend.attention_summary(text)
        if not attn or not attn.get("top_tokens"):
            return ""
        tokens = ", ".join(t["token"] for t in attn["top_tokens"][:5])
        return f"Focus tokens: {tokens}"

    def _pack_context(self, context_messages: Optional[Sequence[str]]) -> str:
        if not context_messages:
            return ""
        trimmed = [m.strip() for m in context_messages if m and m.strip()][-self.MAX_CONTEXT_MESSAGES :]
        if not trimmed:
            return ""
        lines = [f"- {msg}" for msg in trimmed]
        return "\n".join(lines)

    def _build_messages(
        self,
        *,
        task: str,
        prompt: str,
        language: str = "id",
        context_messages: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, str]]:
        context_block = self._pack_context(context_messages)
        attention_hint = self._build_attention_hint(prompt)
        system = (
            "You are FinBot, a multilingual financial AI assistant. "
            "Give precise, safe, structured responses. "
            "Prioritize factual extraction over speculation."
        )
        if language == "id":
            system += " Utamakan bahasa Indonesia kecuali user memakai bahasa lain."
        elif language == "en":
            system += " Prefer English unless the user message is in another language."

        user_content = prompt
        if context_block:
            user_content += f"\n\nConversation context:\n{context_block}"
        if attention_hint:
            user_content += f"\n\n{attention_hint}"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    # -----------------------------------
    # SAFE CALL
    # -----------------------------------

    async def _safe_ai_call(
        self,
        prompt: str,
        response_format=None,
        *,
        task: str = "general",
        prefer_speed: bool = False,
        context_messages: Optional[Sequence[str]] = None,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ):
        if not self.client or self._is_circuit_open():
            return None

        model = self._select_model(task, prefer_speed=prefer_speed)
        lang = self._get_language(prompt)
        messages = self._build_messages(
            task=task,
            prompt=prompt,
            language=lang,
            context_messages=context_messages,
        )

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                params = {
                    "model": model,
                    "messages": messages,
                    "temperature": max(0.0, min(1.0, temperature)),
                    "max_tokens": max(80, int(max_tokens)),
                }
                if response_format:
                    params["response_format"] = response_format

                response = await asyncio.wait_for(
                    self.client.chat.completions.create(**params),
                    timeout=self.TIMEOUT,
                )

                self._record_success()
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"AI error task={task} attempt={attempt + 1}: {e}")
                self._record_failure()
                await asyncio.sleep(0.5 * (attempt + 1))

        return None

    # -----------------------------------
    # CACHE LAYER
    # -----------------------------------

    def _get_cache(self, key: str):
        if not self.redis.client:
            return None
        cached = self.redis.client.get(key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                return None
        return None

    def _set_cache(self, key: str, value: Dict):
        if not self.redis.client:
            return
        try:
            self.redis.client.setex(key, self.CACHE_TTL, json.dumps(value))
        except Exception:
            pass

    # -----------------------------------
    # TRANSACTION PARSER
    # -----------------------------------

    def _rule_based_parse(self, text: str) -> Dict[str, Any]:
        text_l = (text or "").lower()
        amount = parse_primary_amount_id(text_l) or 0.0

        category = None
        for c in CATEGORIES:
            if c.lower() in text_l:
                category = c
                break
        if not category:
            if any(k in text_l for k in ("makan", "bakso", "nasi", "warteg", "resto")):
                category = "Makanan"
            elif any(k in text_l for k in ("kopi", "minum", "boba", "teh")):
                category = "Minuman"
            elif any(k in text_l for k in ("bensin", "ojol", "grab", "gojek", "tol")):
                category = "Transportasi"
            elif any(k in text_l for k in ("gaji", "salary", "income", "bonus")):
                category = "Gaji"

        trans_type = "income" if (category == "Gaji" or "gaji" in text_l or "income" in text_l) else "expense"
        description = re.sub(r"\s+", " ", re.sub(r"\d+[.,]?\d*", " ", text_l)).strip()[:96] or "Transaksi"

        return {
            "amount": float(amount),
            "category": category,
            "description": description,
            "type": trans_type if amount > 0 else None,
            "is_transaction": bool(amount and amount > 0),
        }

    def _coerce_transaction_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        amount = data.get("amount", 0)
        try:
            amount = float(amount)
        except Exception:
            amount = 0.0

        category = data.get("category")
        if category and category not in CATEGORIES:
            category = category.strip().title()
            if category not in CATEGORIES:
                category = None

        desc = data.get("description") or data.get("merchant") or data.get("note") or "Transaksi"
        desc = str(desc).strip()[:140]

        ttype = str(data.get("type") or "").lower().strip()
        if ttype not in {"expense", "income"}:
            ttype = "income" if category == "Gaji" else "expense"

        return {
            "amount": amount if amount > 0 else 0.0,
            "category": category,
            "description": desc,
            "type": ttype if amount > 0 else None,
            "is_transaction": bool(amount > 0),
        }

    async def parse_transaction(self, text: str, context_messages: Optional[Sequence[str]] = None) -> Optional[Dict]:
        cache_key = f"ai:parse:{self._stable_hash(text)}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        transformer_hint = None
        if self.transformer_backend:
            transformer_hint = self.transformer_backend.extract_entities(text, categories=CATEGORIES)

        prompt = self._build_transaction_prompt(text)
        content = await self._safe_ai_call(
            prompt,
            response_format={"type": "json_object"},
            task="parse",
            prefer_speed=True,
            context_messages=context_messages,
            temperature=0.0,
            max_tokens=350,
        )

        if not content:
            fallback = self._fallback_parse()
            rule = self._rule_based_parse(text)
            fallback.update({k: v for k, v in rule.items() if v is not None})
            if transformer_hint:
                fallback["amount"] = fallback.get("amount") or transformer_hint.get("amount") or 0.0
                fallback["category"] = fallback.get("category") or transformer_hint.get("category")
                fallback["description"] = fallback.get("description") or transformer_hint.get("merchant") or "Transaksi"
                fallback["is_transaction"] = bool(fallback.get("amount", 0) > 0)
                fallback["type"] = fallback.get("type") or ("income" if fallback.get("category") == "Gaji" else "expense")
            self._set_cache(cache_key, fallback)
            return fallback

        try:
            result = self._coerce_transaction_schema(json.loads(content))
            if transformer_hint:
                if result.get("amount", 0) <= 0 and transformer_hint.get("amount"):
                    result["amount"] = float(transformer_hint["amount"])
                if not result.get("category") and transformer_hint.get("category"):
                    result["category"] = transformer_hint.get("category")
                if (not result.get("description") or result["description"] == "Transaksi") and transformer_hint.get("merchant"):
                    result["description"] = transformer_hint.get("merchant")
                result["is_transaction"] = bool(result.get("amount", 0) > 0)
                if result["is_transaction"] and not result.get("type"):
                    result["type"] = "income" if result.get("category") == "Gaji" else "expense"

            if not self._validate_transaction_schema(result):
                return self._fallback_parse()

            self._set_cache(cache_key, result)
            return result
        except Exception:
            return self._fallback_parse()

    # -----------------------------------
    # AUTONOMOUS INTENT
    # -----------------------------------

    @staticmethod
    def _intent_map_from_transformer(intent_name: str) -> Optional[str]:
        mapping = {
            "ADD_TRANSACTION": "record",
            "CHECK_BUDGET": "query_budget",
            "QUERY_SUMMARY": "need_insight",
            "SHARING_INFO": "need_insight",
            "GREETING": "general_chat",
            "SMALL_TALK": "general_chat",
            "UNKNOWN": "general_chat",
        }
        return mapping.get(intent_name)

    def _coerce_intent_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        intent = str(data.get("intent") or "general_chat")
        confidence = data.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = 0.0
        structured_data = data.get("structured_data")
        if not isinstance(structured_data, dict):
            structured_data = {}
        suggested_response = str(data.get("suggested_response") or "").strip()
        if not suggested_response:
            suggested_response = "Aku belum yakin maksudnya apa. Bisa jelasin lagi?"
        needs_live_update = bool(data.get("needs_live_update", False))
        return {
            "intent": intent,
            "confidence": confidence,
            "structured_data": structured_data,
            "suggested_response": suggested_response,
            "needs_live_update": needs_live_update,
        }

    async def detect_autonomous_intent(
        self,
        text: str,
        user_context=None,
        context_messages: Optional[Sequence[str]] = None,
    ):
        if self.transformer_backend:
            t_res = self.transformer_backend.classify_intent(
                text=text,
                intent_descriptions={
                    "ADD_TRANSACTION": "mencatat transaksi uang masuk/keluar",
                    "CHECK_BUDGET": "menanyakan status anggaran",
                    "QUERY_SUMMARY": "meminta ringkasan laporan",
                    "SHARING_INFO": "memberi informasi finansial",
                    "SMALL_TALK": "obrolan santai",
                    "UNKNOWN": "tidak jelas",
                },
                context_messages=context_messages,
            )
            if t_res and t_res.get("confidence", 0) >= max(self.CONFIDENCE_THRESHOLD, 0.7):
                mapped = self._intent_map_from_transformer(t_res.get("intent", "UNKNOWN")) or "general_chat"
                return {
                    "intent": mapped,
                    "confidence": float(t_res["confidence"]),
                    "structured_data": {},
                    "suggested_response": "Siap, aku tangkap maksudmu.",
                    "needs_live_update": mapped in {"record", "query_budget"},
                    "language": t_res.get("language", "unknown"),
                    "attention": t_res.get("attention"),
                    "source": "transformer",
                }

        prompt = self._build_autonomous_prompt(text, user_context)
        content = await self._safe_ai_call(
            prompt,
            response_format={"type": "json_object"},
            task="intent",
            prefer_speed=True,
            context_messages=context_messages,
            temperature=0.0,
            max_tokens=350,
        )

        if not content:
            return self._fallback_intent()

        try:
            result = self._coerce_intent_schema(json.loads(content))
            if result.get("confidence", 0) < self.CONFIDENCE_THRESHOLD:
                return self._fallback_intent()
            return result
        except Exception:
            return self._fallback_intent()

    # -----------------------------------
    # CHAT RESPONSE
    # -----------------------------------

    async def chat_response(
        self,
        text: str,
        user_name: str = "Teman",
        context_messages: Optional[Sequence[str]] = None,
    ):
        lang = self._get_language(text)
        lang_note = (
            "Gunakan bahasa Indonesia yang natural."
            if lang in {"id", "unknown"}
            else "Respond naturally in the user's language."
        )
        prompt = f"""
        Kamu adalah FinBot, asisten keuangan pribadi yang cerdas dan suportif.
        Nama user: {user_name}
        Pesan user: "{text}"
        {lang_note}

        Instruksi:
        1. Berikan jawaban terstruktur (paragraf pendek).
        2. Gunakan bullet points untuk list/tips.
        3. Nada profesional, ramah, dan actionable.
        4. Maksimal 180 kata agar nyaman di Telegram.
        """

        response = await self._safe_ai_call(
            prompt,
            task="chat",
            context_messages=context_messages,
            temperature=0.4,
            max_tokens=420,
        )
        return response or f"Halo {user_name}! FinBot siap bantu urusan keuanganmu hari ini."

    # -----------------------------------
    # SMART INSIGHT
    # -----------------------------------

    async def generate_smart_insight(self, raw_summary: str, context_messages: Optional[Sequence[str]] = None):
        prompt = f"""
        Analisa data berikut dan beri 3 insight yang actionable.
        Fokus: pola pengeluaran, risiko cashflow, dan next best action.

        Data:
        {raw_summary}
        """
        response = await self._safe_ai_call(
            prompt,
            task="insight",
            context_messages=context_messages,
            temperature=0.2,
            max_tokens=500,
        )
        return response or "Belum cukup data untuk insight. Yuk catat lagi!"

    # -----------------------------------
    # PROMPT BUILDERS
    # -----------------------------------

    def _build_transaction_prompt(self, text: str):
        return f"""
        Extract structured transaction from:
        "{text}"

        Categories: {', '.join(CATEGORIES)}

        Return JSON ONLY:
        {{
            "amount": float,
            "category": string,
            "description": string,
            "type": "expense" | "income",
            "is_transaction": boolean
        }}
        """

    def _build_autonomous_prompt(self, text, context):
        return f"""
        User: "{text}"
        Context: {context}

        Classify intent:
        - record
        - query_budget
        - need_insight
        - predictive_warning
        - general_chat

        Return JSON ONLY:
        {{
            "intent": string,
            "confidence": 0-1,
            "structured_data": {{}},
            "suggested_response": string,
            "needs_live_update": boolean
        }}
        """

    # -----------------------------------
    # VALIDATION
    # -----------------------------------

    def _validate_transaction_schema(self, data: Dict) -> bool:
        required = {"amount", "category", "description", "type", "is_transaction"}
        if not required.issubset(data.keys()):
            return False
        try:
            amount = float(data.get("amount", 0))
        except Exception:
            return False
        if amount <= 0:
            return bool(data.get("is_transaction") is False)
        if data.get("type") not in {"expense", "income"}:
            return False
        return True

    # -----------------------------------
    # EVALUATION + BENCHMARK
    # -----------------------------------

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = int(round((pct / 100.0) * (len(ordered) - 1)))
        idx = max(0, min(idx, len(ordered) - 1))
        return float(ordered[idx])

    @staticmethod
    def _classification_metrics_fallback(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
        labels = sorted(set(y_true) | set(y_pred))
        l2i = {label: i for i, label in enumerate(labels)}
        matrix = [[0 for _ in labels] for _ in labels]
        for t, p in zip(y_true, y_pred):
            matrix[l2i[t]][l2i[p]] += 1

        tp_total = 0
        total = len(y_true)
        p_macro = 0.0
        r_macro = 0.0
        f_macro = 0.0
        for i in range(len(labels)):
            tp = matrix[i][i]
            fp = sum(row[i] for row in matrix) - tp
            fn = sum(matrix[i]) - tp
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-9)
            p_macro += precision
            r_macro += recall
            f_macro += f1
            tp_total += tp

        n = max(len(labels), 1)
        return {
            "labels": labels,
            "confusion_matrix": matrix,
            "accuracy": tp_total / max(total, 1),
            "macro_precision": p_macro / n,
            "macro_recall": r_macro / n,
            "macro_f1": f_macro / n,
        }

    async def evaluate_intent_model(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not samples:
            return {
                "samples": 0,
                "accuracy": 0.0,
                "macro_precision": 0.0,
                "macro_recall": 0.0,
                "macro_f1": 0.0,
                "latency_p95_ms": 0.0,
            }

        y_true: List[str] = []
        y_pred: List[str] = []
        latencies: List[float] = []

        for row in samples:
            text = str(row.get("text", ""))
            expected = str(row.get("intent", "general_chat"))
            t0 = time.perf_counter()
            pred = await self.detect_autonomous_intent(text, user_context=row.get("context"))
            latencies.append((time.perf_counter() - t0) * 1000.0)
            y_true.append(expected)
            y_pred.append(str(pred.get("intent", "general_chat")))

        try:
            from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

            labels = sorted(set(y_true) | set(y_pred))
            macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
                y_true, y_pred, average="macro", zero_division=0
            )
            accuracy = float(accuracy_score(y_true, y_pred))
            matrix = confusion_matrix(y_true, y_pred, labels=labels).tolist()
        except Exception:
            fb = self._classification_metrics_fallback(y_true, y_pred)
            labels = fb["labels"]
            macro_p = fb["macro_precision"]
            macro_r = fb["macro_recall"]
            macro_f1 = fb["macro_f1"]
            accuracy = fb["accuracy"]
            matrix = fb["confusion_matrix"]

        return {
            "samples": len(samples),
            "accuracy": round(float(accuracy), 4),
            "macro_precision": round(float(macro_p), 4),
            "macro_recall": round(float(macro_r), 4),
            "macro_f1": round(float(macro_f1), 4),
            "latency_p50_ms": round(self._percentile(latencies, 50.0), 2),
            "latency_p95_ms": round(self._percentile(latencies, 95.0), 2),
            "labels": labels,
            "confusion_matrix": matrix,
        }

    async def evaluate_transaction_parser(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not samples:
            return {
                "samples": 0,
                "amount_mae": 0.0,
                "category_accuracy": 0.0,
                "transaction_f1": 0.0,
                "latency_p95_ms": 0.0,
            }

        amount_errors: List[float] = []
        cat_total = 0
        cat_hits = 0
        tp = 0
        fp = 0
        fn = 0
        latencies: List[float] = []

        for row in samples:
            text = str(row.get("text", ""))
            expected_amount = row.get("amount")
            expected_cat = row.get("category")
            expected_tx = bool(row.get("is_transaction", True))

            t0 = time.perf_counter()
            pred = await self.parse_transaction(text)
            latencies.append((time.perf_counter() - t0) * 1000.0)

            pred_amount = float(pred.get("amount", 0) or 0)
            pred_tx = bool(pred.get("is_transaction", False))
            pred_cat = pred.get("category")

            if expected_amount is not None:
                amount_errors.append(abs(float(expected_amount) - pred_amount))
            if expected_cat is not None:
                cat_total += 1
                if str(pred_cat) == str(expected_cat):
                    cat_hits += 1

            if pred_tx and expected_tx:
                tp += 1
            elif pred_tx and not expected_tx:
                fp += 1
            elif (not pred_tx) and expected_tx:
                fn += 1

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)

        return {
            "samples": len(samples),
            "amount_mae": round(sum(amount_errors) / max(len(amount_errors), 1), 2),
            "category_accuracy": round(cat_hits / max(cat_total, 1), 4),
            "transaction_precision": round(precision, 4),
            "transaction_recall": round(recall, 4),
            "transaction_f1": round(f1, 4),
            "latency_p50_ms": round(self._percentile(latencies, 50.0), 2),
            "latency_p95_ms": round(self._percentile(latencies, 95.0), 2),
        }

    async def benchmark_production(
        self,
        texts: List[str],
        *,
        rounds: int = 1,
        context_messages: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        if not texts:
            return {"samples": 0, "throughput_qps": 0.0}

        parse_lat = []
        intent_lat = []
        chat_lat = []
        calls = 0
        started = time.perf_counter()

        for _ in range(max(1, rounds)):
            for text in texts:
                t0 = time.perf_counter()
                await self.parse_transaction(text, context_messages=context_messages)
                parse_lat.append((time.perf_counter() - t0) * 1000.0)

                t1 = time.perf_counter()
                await self.detect_autonomous_intent(text, context_messages=context_messages)
                intent_lat.append((time.perf_counter() - t1) * 1000.0)

                t2 = time.perf_counter()
                await self.chat_response(text, context_messages=context_messages)
                chat_lat.append((time.perf_counter() - t2) * 1000.0)
                calls += 3

        elapsed = max(time.perf_counter() - started, 1e-9)
        return {
            "samples": len(texts) * max(1, rounds),
            "parse_p95_ms": round(self._percentile(parse_lat, 95.0), 2),
            "intent_p95_ms": round(self._percentile(intent_lat, 95.0), 2),
            "chat_p95_ms": round(self._percentile(chat_lat, 95.0), 2),
            "throughput_qps": round(calls / elapsed, 2),
            "transformer_enabled": bool(self.transformer_backend),
        }

    # -----------------------------------
    # FALLBACKS
    # -----------------------------------

    def _fallback_parse(self):
        return {
            "amount": 0,
            "category": None,
            "description": None,
            "type": None,
            "is_transaction": False,
        }

    def _fallback_intent(self):
        return {
            "intent": "general_chat",
            "confidence": 0.0,
            "structured_data": {},
            "suggested_response": "Aku belum yakin maksudnya apa. Bisa jelasin lagi?",
            "needs_live_update": False,
        }
