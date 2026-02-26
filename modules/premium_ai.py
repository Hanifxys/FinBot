"""
premium_ai.py — FinBot Pro AI Engine
Refactored for reliability, performance, and maintainability.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from groq import AsyncGroq
from pydantic import BaseModel, Field, field_validator, model_validator

from config import CATEGORIES, GROQ_API_KEY
from modules.ai_memory import AIMemory
from modules.ai_persona import PersonaManager
from modules.document_processor import DocumentProcessor
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums — typed constants replace raw string literals
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    RECORD = "record"
    QUERY = "query"
    INSIGHT = "insight"
    WARNING = "warning"
    CHAT = "chat"
    CONFIG = "config"
    CANCEL = "cancel"
    LIMIT = "limit"

class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TransactionModel(BaseModel):
    amount: float = Field(..., gt=0, description="Transaction amount (must be positive)")
    category: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., max_length=255)
    type: str = Field(..., pattern="^(expense|income)$")
    is_transaction: bool


class AIIntentResponse(BaseModel):
    intent: str = Field(default=Intent.CHAT.value)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    sentiment: str = Field(default=Sentiment.NEUTRAL.value)
    language: str = Field(default="id")
    structured_data: Dict[str, Any] = Field(default_factory=dict)
    suggested_response: str = Field(
        default="Maaf, saya sedang mengalami gangguan koneksi. Bisa diulangi?"
    )
    predictive_advice: Optional[str] = None
    needs_live_update: bool = Field(default=False)

    @field_validator("structured_data", mode="before")
    @classmethod
    def coerce_none_to_dict(cls, v):
        return v or {}

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v):
        """Guard against models returning out-of-range values."""
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Circuit breaker (self-contained, easily unit-testable)
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    limit: int = 5
    reset_seconds: int = 60
    _failures: int = field(default=0, init=False, repr=False)
    _open_until: float = field(default=0.0, init=False, repr=False)

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.limit:
            self._open_until = time.monotonic() + self.reset_seconds
            logger.warning(
                "Circuit opened after %d failures — pausing AI for %ds",
                self._failures, self.reset_seconds,
            )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _stable_hash(text: str) -> str:
    """Deterministic, collision-resistant hash (replaces Python's unstable `hash()`)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class PremiumAIEngine:
    """
    Async AI engine with:
    - Model fallback hierarchy
    - Per-user daily budget enforcement
    - Redis caching with stable keys
    - Circuit breaker for upstream failures
    - Structured Pydantic responses
    """

    PRIMARY_MODEL = "llama-3.3-70b-versatile"
    FALLBACK_MODEL = "mixtral-8x7b-32768"
    FAST_MODEL = "llama3-8b-8192"

    TIMEOUT = 20
    MAX_RETRIES = 2
    CONFIDENCE_THRESHOLD = 0.6
    CACHE_TTL = 120
    DAILY_AI_LIMIT = 200
    DOCUMENT_MAX_CHARS = 8_000

    # Schema sent to LLM so it knows the exact shape to return
    _RESPONSE_SCHEMA = json.dumps(
        {
            "intent": "record|query|insight|warning|chat|config|cancel",
            "confidence": "float 0-1",
            "sentiment": "positive|neutral|negative",
            "language": "id",
            "structured_data": {},
            "suggested_response": "string",
            "predictive_advice": "string or null",
            "needs_live_update": "boolean",
        },
        indent=2,
    )

    def __init__(
        self,
        redis: Optional[RedisManager] = None,
        persona_mgr: Optional[PersonaManager] = None,
        doc_processor: Optional[DocumentProcessor] = None,
    ) -> None:
        self._client: Optional[AsyncGroq] = None
        self.redis = redis or RedisManager()
        self.persona_mgr = persona_mgr or PersonaManager()
        self.doc_processor = doc_processor or DocumentProcessor()
        self._circuit = CircuitBreaker()

    # ------------------------------------------------------------------
    # Client (lazy-init, idempotent)
    # ------------------------------------------------------------------

    @property
    def client(self) -> Optional[AsyncGroq]:
        if self._client is None and GROQ_API_KEY:
            try:
                self._client = AsyncGroq(
                    api_key=GROQ_API_KEY,
                    timeout=self.TIMEOUT,
                    max_retries=0,  # We handle retries manually
                )
                logger.info("Groq client initialised (model=%s)", self.PRIMARY_MODEL)
            except Exception as exc:
                logger.error("Groq client init failed: %s", exc)
        return self._client

    # ------------------------------------------------------------------
    # Daily budget
    # ------------------------------------------------------------------

    def _check_ai_budget(self, user_id: int) -> bool:
        """
        Returns True if the user is within daily budget.
        Falls back to True (permissive) when Redis is unavailable so AI
        still works in degraded mode.
        """
        if not self.redis.client:
            logger.debug("Redis unavailable — skipping budget check for user %d", user_id)
            return True

        key = f"user:{user_id}:ai_daily"
        try:
            count = int(self.redis.client.get(key) or 0)
            if count >= self.DAILY_AI_LIMIT:
                logger.info("User %d hit daily AI limit (%d)", user_id, self.DAILY_AI_LIMIT)
                return False
            pipe = self.redis.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 86_400)
            pipe.execute()
            return True
        except Exception as exc:
            logger.warning("Budget check failed for user %d: %s — allowing request", user_id, exc)
            return True

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.redis.client:
            return None
        try:
            raw = self.redis.client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("Cache read error key=%s: %s", key, exc)
            return None

    def _cache_set(self, key: str, value: Any) -> None:
        if not self.redis.client:
            return
        try:
            self.redis.client.setex(key, self.CACHE_TTL, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            logger.debug("Cache write error key=%s: %s", key, exc)

    # ------------------------------------------------------------------
    # LLM call (retries + circuit breaker)
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        *,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Call the LLM with retries and circuit-breaker protection.
        Returns raw string content, or None on failure.
        """
        if not self.client or self._circuit.is_open:
            logger.debug("LLM call skipped: client=%s circuit_open=%s", bool(self.client), self._circuit.is_open)
            return None

        if use_cache:
            cache_key = f"llm:{model}:{_stable_hash(system_prompt + user_prompt)}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                logger.debug("LLM cache hit model=%s", model)
                return cached

        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        response_format={"type": "json_object"},
                    ),
                    timeout=self.TIMEOUT,
                )
                content = response.choices[0].message.content
                self._circuit.record_success()

                if use_cache:
                    self._cache_set(cache_key, content)

                return content

            except asyncio.TimeoutError as exc:
                last_exc = exc
                logger.warning("LLM timeout model=%s attempt=%d/%d", model, attempt + 1, self.MAX_RETRIES + 1)
                self._circuit.record_failure()
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM error model=%s attempt=%d: %s", model, attempt + 1, exc)
                self._circuit.record_failure()

            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))  # simple back-off

        logger.error("All attempts failed for model=%s last_error=%s", model, last_exc)
        return None

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self, user_id: int) -> str:
        persona = self.persona_mgr.get_persona(user_id)
        categories = ", ".join(CATEGORIES)
        return (
            f"{persona.system_prompt()}\n"
            f"Available categories: {categories}\n"
            "Rules: respond ONLY in valid JSON. Be concise. Use provided context carefully."
        )

    def _build_user_prompt(self, user_name: str, context_str: str, text: str) -> str:
        return (
            f"User: {user_name}\n\n"
            f"Conversation context:\n{context_str or '(none)'}\n\n"
            f'Current message: "{text}"\n\n'
            f"Return JSON strictly matching this schema:\n{self._RESPONSE_SCHEMA}"
        )

    # ------------------------------------------------------------------
    # Main interaction
    # ------------------------------------------------------------------

    async def process_interaction(
        self,
        user_id: int,
        text: str,
        user_name: str = "Client",
    ) -> AIIntentResponse:
        """
        Process a user message and return a structured AI response.
        Implements: budget check → cache → model fallback → memory save.
        """
        if not self._check_ai_budget(user_id):
            return AIIntentResponse(
                intent=Intent.LIMIT.value,
                suggested_response="Limit AI harian kamu sudah tercapai. Coba lagi besok ya 🙏",
                confidence=1.0,
            )

        # Interaction-level cache (keyed on user + text, NOT user-specific per-model)
        interaction_cache_key = f"ai:v3:{user_id}:{_stable_hash(text)}"
        cached = self._cache_get(interaction_cache_key)
        if cached:
            logger.debug("Interaction cache hit user=%d", user_id)
            return AIIntentResponse(**cached)

        memory = AIMemory(user_id)
        context_msgs: List[Dict[str, str]] = memory.get_context(limit=10)
        context_str = "\n".join(f"{m['role']}: {m['content']}" for m in context_msgs)

        system_prompt = self._build_system_prompt(user_id)
        user_prompt = self._build_user_prompt(user_name, context_str, text)

        for model in (self.PRIMARY_MODEL, self.FALLBACK_MODEL, self.FAST_MODEL):
            raw = await self._call_llm(system_prompt, user_prompt, model)
            if raw is None:
                continue

            response = self._parse_ai_response(raw, model)
            if response is None:
                continue

            if response.confidence < self.CONFIDENCE_THRESHOLD:
                logger.debug("Low confidence %.2f from model=%s — trying next", response.confidence, model)
                continue

            # Persist successful response
            self._cache_set(interaction_cache_key, response.model_dump())
            memory.add_user_message(text)
            memory.add_ai_message(response.suggested_response)

            logger.info(
                "AI response: user=%d model=%s intent=%s confidence=%.2f",
                user_id, model, response.intent, response.confidence,
            )
            return response

        logger.warning("All models failed or low-confidence for user=%d", user_id)
        return AIIntentResponse(
            intent=Intent.CHAT.value,
            suggested_response="Aku belum yakin maksudnya. Bisa jelasin lagi ya?",
            confidence=0.0,
        )

    def _parse_ai_response(self, raw: str, model: str) -> Optional[AIIntentResponse]:
        """Parse and validate raw LLM output. Returns None on any parse failure."""
        try:
            data = json.loads(raw)
            return AIIntentResponse(**data)
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode error model=%s: %s | raw=%r", model, exc, raw[:200])
        except Exception as exc:
            logger.warning("Schema validation error model=%s: %s", model, exc)
        return None

    # ------------------------------------------------------------------
    # Document processing
    # ------------------------------------------------------------------

    async def process_document(
        self,
        user_id: int,
        file_content: bytes,
        file_name: str,
        mime_type: str,
    ) -> str:
        """Extract and summarise a financial document."""
        try:
            extracted: str = await self.doc_processor.process_file(
                file_content, file_name, mime_type
            )
        except Exception as exc:
            logger.error("Document extraction failed file=%s: %s", file_name, exc)
            return "Gagal memproses dokumen."

        if not extracted:
            return "Dokumen kosong atau tidak dapat dibaca."

        summary = await self._call_llm(
            "Summarize the key financial insights clearly and concisely in Indonesian.",
            extracted[: self.DOCUMENT_MAX_CHARS],
            self.FAST_MODEL,
        )

        result = summary or "Tidak dapat menganalisis dokumen."

        memory = AIMemory(user_id)
        memory.add_user_message(f"[Uploaded: {file_name}]")
        memory.add_ai_message(result)

        return result

    # ------------------------------------------------------------------
    # Voice transcription
    # ------------------------------------------------------------------

    async def transcribe_voice(self, audio_file_path: str) -> str:
        """Transcribe an audio file via Whisper. Returns empty string on failure."""
        if not self.client:
            logger.warning("transcribe_voice called but Groq client is not available")
            return ""

        try:
            with open(audio_file_path, "rb") as f:
                audio_bytes = f.read()

            transcription = await asyncio.wait_for(
                self.client.audio.transcriptions.create(
                    file=(audio_file_path, audio_bytes),
                    model="whisper-large-v3",
                    response_format="text",
                    language="id",
                ),
                timeout=30,
            )
            return transcription or ""

        except FileNotFoundError:
            logger.error("Audio file not found: %s", audio_file_path)
        except asyncio.TimeoutError:
            logger.error("Voice transcription timed out for %s", audio_file_path)
        except Exception as exc:
            logger.error("Voice transcription error: %s", exc)

        return ""

    # ------------------------------------------------------------------
    # Duplicate transaction detection
    # ------------------------------------------------------------------

    async def check_reconciliation(
        self, user_id: int, new_tx_data: Dict[str, Any]
    ) -> bool:
        """
        Returns True if this transaction looks like a duplicate within the last 60 s.
        Uses a stable hash (not Python's non-deterministic `hash()`).
        """
        if not self.redis.client:
            return False

        tx_hash = _stable_hash(json.dumps(new_tx_data, sort_keys=True))
        key = f"user:{user_id}:last_tx_hash"

        try:
            last_hash = self.redis.client.get(key)
            if last_hash and last_hash.decode() == tx_hash:
                logger.info("Duplicate transaction detected for user=%d", user_id)
                return True

            self.redis.client.setex(key, 60, tx_hash)
            return False

        except Exception as exc:
            logger.warning("Reconciliation check failed user=%d: %s", user_id, exc)
            return False

    # ------------------------------------------------------------------
    # Reminder generation
    # ------------------------------------------------------------------

    async def generate_reminder(self, user_id: int) -> str:
        """Generate a short, personalised expense-tracking reminder."""
        persona = self.persona_mgr.get_persona(user_id)
        system_prompt = (
            f"{persona.system_prompt()}\n"
            "Task: Write a single friendly sentence reminding the user to track their expenses. "
            "The user has not interacted in 24 hours. Use exactly 1 emoji. "
            "Return JSON: {\"reminder\": \"<text>\"}"
        )

        raw = await self._call_llm(
            system_prompt,
            '{"task": "generate_reminder"}',
            self.FAST_MODEL,
            use_cache=False,  # reminders should feel fresh each time
        )

        if not raw:
            return ""

        try:
            return json.loads(raw).get("reminder", "").strip()
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.warning("Reminder parse failed: %s | raw=%r", exc, raw[:100])
            return ""

    # ------------------------------------------------------------------
    # Diagnostics (used by /stats endpoint)
    # ------------------------------------------------------------------

    def generate_comprehensive_test_report(self) -> Dict[str, Any]:
        return {
            "models": {
                "primary": self.PRIMARY_MODEL,
                "fallback": self.FALLBACK_MODEL,
                "fast": self.FAST_MODEL,
            },
            "circuit_breaker": {
                "is_open": self._circuit.is_open,
                "failures": self._circuit._failures,
                "open_until": self._circuit._open_until,
            },
            "limits": {
                "daily_ai_per_user": self.DAILY_AI_LIMIT,
                "cache_ttl_seconds": self.CACHE_TTL,
                "confidence_threshold": self.CONFIDENCE_THRESHOLD,
            },
            "redis": "connected" if self.redis.client else "disconnected",
            "groq_client": "ready" if self._client else "not_initialised",
        }