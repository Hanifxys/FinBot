import json
import logging
import asyncio
import time
from typing import Dict, Any, Optional
from pydantic import ValidationError, BaseModel, Field, validator
from groq import AsyncGroq
from config import GROQ_API_KEY, CATEGORIES
from modules.redis_mgr import RedisManager
from modules.ai_memory import AIMemory
from modules.ai_persona import PersonaManager
from modules.document_processor import DocumentProcessor

class TransactionModel(BaseModel):
    amount: float = Field(..., description="The transaction amount")
    category: str = Field(..., description="Financial category")
    description: str = Field(..., description="Brief transaction description")
    type: str = Field(..., pattern="^(expense|income)$")
    is_transaction: bool = Field(..., description="Whether this is a valid transaction")

class AIIntentResponse(BaseModel):
    intent: str = Field(default="chat")
    confidence: float = Field(default=0.0)
    sentiment: str = Field(default="neutral")
    language: str = Field(default="id")
    structured_data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    suggested_response: str = Field(default="Maaf, saya sedang mengalami gangguan koneksi. Bisa diulangi?")
    predictive_advice: Optional[str] = None
    needs_live_update: bool = Field(default=False)

    @validator('structured_data', pre=True, always=True)
    def set_structured_data(cls, v):
        return v or {}

logger = logging.getLogger(__name__)


class PremiumAIEngine:

    PRIMARY_MODEL = "llama-3.3-70b-versatile"
    FALLBACK_MODEL = "mixtral-8x7b-32768"
    FAST_MODEL = "llama3-8b-8192"

    TIMEOUT = 20
    MAX_RETRIES = 2
    CONFIDENCE_THRESHOLD = 0.6
    CIRCUIT_LIMIT = 5
    CACHE_TTL = 120
    DAILY_AI_LIMIT = 200  # per user safeguard

    def __init__(self):
        self._client = None
        self.redis = RedisManager()
        self.persona_mgr = PersonaManager()
        self.doc_processor = DocumentProcessor()
        self.failure_count = 0
        self.circuit_open_until = 0

    # ------------------------------------
    # CLIENT INIT
    # ------------------------------------

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

    # ------------------------------------
    # CIRCUIT BREAKER
    # ------------------------------------

    def _circuit_open(self):
        return time.time() < self.circuit_open_until

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.CIRCUIT_LIMIT:
            self.circuit_open_until = time.time() + 60
            logger.warning("AI circuit opened for 60s")

    def _record_success(self):
        self.failure_count = 0

    # ------------------------------------
    # USER AI BUDGET PROTECTION
    # ------------------------------------

    def _check_ai_budget(self, user_id: int) -> bool:
        if not self.redis.client:
            return True

        key = f"user:{user_id}:ai_daily"
        count = int(self.redis.client.get(key) or 0)

        if count >= self.DAILY_AI_LIMIT:
            return False

        pipe = self.redis.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)
        pipe.execute()

        return True

    # ------------------------------------
    # CACHE
    # ------------------------------------

    def _cache_get(self, key: str):
        if not self.redis.client:
            return None
        data = self.redis.client.get(key)
        return json.loads(data) if data else None

    def _cache_set(self, key: str, value: Dict):
        if not self.redis.client:
            return
        self.redis.client.setex(key, self.CACHE_TTL, json.dumps(value))

    # ------------------------------------
    # SAFE LLM CALL
    # ------------------------------------

    async def _call_llm(self, system_prompt, user_prompt, model):
        if not self.client or self._circuit_open():
            return None

        # Cache key based on prompts and model
        cache_key = f"llm:{model}:{hash(system_prompt + user_prompt)}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        for _ in range(self.MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        response_format={"type": "json_object"}
                    ),
                    timeout=self.TIMEOUT
                )
                self._record_success()
                result = response.choices[0].message.content
                
                # Cache successful response
                self._cache_set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"Model {model} failed: {e}")
                self._record_failure()
                await asyncio.sleep(0.5)

        return None

    # ------------------------------------
    # MAIN PROCESS
    # ------------------------------------

    async def process_interaction(self, user_id: int, text: str, user_name="Client") -> AIIntentResponse:

        if not self._check_ai_budget(user_id):
            return AIIntentResponse(
                intent="limit",
                suggested_response="Limit AI harian kamu sudah tercapai. Coba lagi besok ya 🙏",
                confidence=1.0
            )

        cache_key = f"ai:v2:{user_id}:{text}"
        cached = self._cache_get(cache_key)
        if cached:
            return AIIntentResponse(**cached)

        memory = AIMemory(user_id)
        context_msgs = memory.get_context(limit=10)
        context_str = "\n".join([f"{m['role']}: {m['content']}" for m in context_msgs])

        persona = self.persona_mgr.get_persona(user_id)

        system_prompt = f"""
        {persona.system_prompt()}
        Categories: {', '.join(CATEGORIES)}
        Use context carefully.
        Be concise and structured.
        """

        user_prompt = f"""
        User: {user_name}
        Context:
        {context_str}

        Message: "{text}"

        Return JSON schema strictly:
        {{
            "intent": "record|query|insight|warning|chat|config|cancel",
            "confidence": float,
            "sentiment": "positive|neutral|negative",
            "language": "id",
            "structured_data": {{}},
            "suggested_response": string,
            "predictive_advice": string,
            "needs_live_update": boolean
        }}
        """

        # Model fallback hierarchy
        for model in [self.PRIMARY_MODEL, self.FALLBACK_MODEL, self.FAST_MODEL]:
            raw = await self._call_llm(system_prompt, user_prompt, model)
            if not raw:
                continue

            try:
                data = json.loads(raw)
                response = AIIntentResponse(**data)

                if response.confidence < self.CONFIDENCE_THRESHOLD:
                    continue

                self._cache_set(cache_key, data)

                memory.add_user_message(text)
                memory.add_ai_message(response.suggested_response)

                return response

            except (json.JSONDecodeError, ValidationError):
                continue

        return AIIntentResponse(
            intent="chat",
            suggested_response="Aku belum yakin maksudnya. Bisa jelasin lagi ya?",
            confidence=0.0
        )

    # ------------------------------------
    # DOCUMENT PROCESSING
    # ------------------------------------

    async def process_document(self, user_id, file_content, file_name, mime_type):

        extracted = await self.doc_processor.process_file(
            file_content, file_name, mime_type
        )

        summary = await self._call_llm(
            "Summarize financial insights clearly.",
            extracted[:8000],
            self.FAST_MODEL
        )

        memory = AIMemory(user_id)
        memory.add_user_message(f"[Uploaded: {file_name}]")
        memory.add_ai_message(summary or "Tidak dapat menganalisis dokumen.")

        return summary or "Gagal menganalisis dokumen."

    # ------------------------------------
    # VOICE TRANSCRIPTION
    # ------------------------------------

    async def transcribe_voice(self, audio_file_path):

        if not self.client:
            return ""

        try:
            with open(audio_file_path, "rb") as file:
                transcription = await asyncio.wait_for(
                    self.client.audio.transcriptions.create(
                        file=(audio_file_path, file.read()),
                        model="whisper-large-v3",
                        response_format="text",
                        language="id"
                    ),
                    timeout=30
                )
                return transcription
        except Exception as e:
            logger.error(f"Voice error: {e}")
            return ""

    # ------------------------------------
    # RECONCILIATION
    # ------------------------------------

    async def check_reconciliation(self, user_id: int, new_tx_data: Dict[str, Any]):

        key = f"user:{user_id}:last_tx_hash"

        tx_hash = hash(json.dumps(new_tx_data, sort_keys=True))

        last_hash = self.redis.client.get(key)

        if last_hash and int(last_hash) == tx_hash:
            return True

        self.redis.client.setex(key, 60, tx_hash)
        return False

    async def generate_reminder(self, user_id: int) -> str:
        """
        Generates a personalized, non-intrusive reminder.
        """
        try:
            persona = self.persona_mgr.get_persona(user_id)
            system_prompt = f"""
            {persona.system_prompt()}
            Task: Generate a friendly, short (1 sentence) reminder for the user to track expenses.
            Context: User hasn't interacted for 24 hours.
            Style: Engaging, not annoying. Use 1 emoji.
            """
            
            reminder = await self._call_llm(system_prompt, "Generate reminder")
            return reminder.strip('"')
        except:
            return ""