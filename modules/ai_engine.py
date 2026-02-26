import json
import logging
import asyncio
import time
from typing import Optional, Dict, Any
from groq import AsyncGroq
from config import GROQ_API_KEY, CATEGORIES
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


class AIEngine:
    """
    Fintech-Grade AI Engine

    Features:
    - Circuit Breaker
    - Timeout Control
    - JSON Schema Validation
    - Confidence Gating
    - Redis Caching
    - Cost Protection
    - Deterministic Fallback
    """

    MODEL = "llama-3.3-70b-versatile"
    MAX_RETRIES = 2
    TIMEOUT = 20
    CONFIDENCE_THRESHOLD = 0.65
    CIRCUIT_BREAK_LIMIT = 5
    CACHE_TTL = 120  # seconds

    def __init__(self):
        self._client = None
        self.redis = RedisManager()
        self.failure_count = 0
        self.circuit_open_until = 0

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
                    max_retries=0
                )
            except Exception as e:
                logger.error(f"Groq init failed: {e}")
                self._client = None
        return self._client

    # -----------------------------------
    # CIRCUIT BREAKER
    # -----------------------------------

    def _is_circuit_open(self):
        return time.time() < self.circuit_open_until

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.CIRCUIT_BREAK_LIMIT:
            self.circuit_open_until = time.time() + 60
            logger.warning("AI Circuit breaker opened for 60 seconds")

    def _record_success(self):
        self.failure_count = 0

    # -----------------------------------
    # SAFE CALL
    # -----------------------------------

    async def _safe_ai_call(self, prompt: str, response_format=None):
        if not self.client or self._is_circuit_open():
            return None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                params = {
                    "model": self.MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if response_format:
                    params["response_format"] = response_format

                response = await asyncio.wait_for(
                    self.client.chat.completions.create(**params),
                    timeout=self.TIMEOUT
                )

                self._record_success()
                return response.choices[0].message.content

            except Exception as e:
                logger.error(f"AI Error attempt {attempt+1}: {e}")
                self._record_failure()
                await asyncio.sleep(1)

        return None

    # -----------------------------------
    # CACHE LAYER
    # -----------------------------------

    def _get_cache(self, key: str):
        if not self.redis.client:
            return None
        cached = self.redis.client.get(key)
        if cached:
            return json.loads(cached)
        return None

    def _set_cache(self, key: str, value: Dict):
        if not self.redis.client:
            return
        self.redis.client.setex(key, self.CACHE_TTL, json.dumps(value))

    # -----------------------------------
    # TRANSACTION PARSER
    # -----------------------------------

    async def parse_transaction(self, text: str) -> Optional[Dict]:
        cache_key = f"ai:parse:{text}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        prompt = self._build_transaction_prompt(text)

        content = await self._safe_ai_call(
            prompt,
            response_format={"type": "json_object"}
        )

        if not content:
            return self._fallback_parse()

        try:
            result = json.loads(content)

            if not self._validate_transaction_schema(result):
                return self._fallback_parse()

            self._set_cache(cache_key, result)
            return result

        except Exception:
            return self._fallback_parse()

    # -----------------------------------
    # AUTONOMOUS INTENT
    # -----------------------------------

    async def detect_autonomous_intent(self, text: str, user_context=None):
        prompt = self._build_autonomous_prompt(text, user_context)

        content = await self._safe_ai_call(
            prompt,
            response_format={"type": "json_object"}
        )

        if not content:
            return self._fallback_intent()

        try:
            result = json.loads(content)

            if result.get("confidence", 0) < self.CONFIDENCE_THRESHOLD:
                return self._fallback_intent()

            return result

        except Exception:
            return self._fallback_intent()

    # -----------------------------------
    # CHAT RESPONSE
    # -----------------------------------

    async def chat_response(self, text: str, user_name="Teman"):
        prompt = f"""
        Kamu adalah FinBot. Friendly, cerdas, profesional.
        User: "{text}"
        Nama: {user_name}
        Jawab max 3 kalimat.
        """

        response = await self._safe_ai_call(prompt)
        return response or f"Halo {user_name}! Mau catat pengeluaran apa hari ini? 💸"

    # -----------------------------------
    # SMART INSIGHT
    # -----------------------------------

    async def generate_smart_insight(self, raw_summary: str):
        prompt = f"""
        Analisa data berikut dan beri 3 insight actionable:
        {raw_summary}
        """

        response = await self._safe_ai_call(prompt)
        return response or "Belum cukup data untuk insight. Yuk catat lagi!"

    # -----------------------------------
    # PROMPT BUILDERS
    # -----------------------------------

    def _build_transaction_prompt(self, text: str):
        return f"""
        Extract structured transaction from:
        "{text}"

        Categories: {', '.join(CATEGORIES)}

        Return JSON:
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

        Return JSON:
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
        return required.issubset(data.keys())

    # -----------------------------------
    # FALLBACKS
    # -----------------------------------

    def _fallback_parse(self):
        return {
            "amount": 0,
            "category": None,
            "description": None,
            "type": None,
            "is_transaction": False
        }

    def _fallback_intent(self):
        return {
            "intent": "general_chat",
            "confidence": 0.0,
            "structured_data": {},
            "suggested_response": "Aku belum yakin maksudnya apa. Bisa jelasin lagi?",
            "needs_live_update": False
        }