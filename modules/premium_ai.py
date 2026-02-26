import os
import json
import logging
import gc
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from groq import AsyncGroq
from config import GROQ_API_KEY, CATEGORIES
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

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

class PremiumAIEngine:
    """
    Enterprise-Grade AI Engine:
    - Multi-model Support (Transformer based)
    - Context-Aware Memory via Redis
    - High-throughput Async Architecture
    - Multi-language & Sentiment Analysis
    """
    def __init__(self):
        self._client = None
        self.primary_model = "llama-3.3-70b-versatile"
        self.fast_model = "llama3-8b-8192"
        self.redis = RedisManager()
        self.max_history = 10

    @property
    def client(self):
        if self._client is None and GROQ_API_KEY:
            try:
                self._client = AsyncGroq(api_key=GROQ_API_KEY, timeout=30.0, max_retries=2)
            except Exception as e:
                logger.error(f"Failed to initialize Premium Groq client: {e}")
        return self._client

    async def _call_llm(self, system_prompt: str, user_prompt: str, schema: Any = None) -> str:
        """Async LLM call with low latency optimization"""
        client = self.client
        if not client: return "{}"
        
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            response = await client.chat.completions.create(
                messages=messages,
                model=self.primary_model,
                response_format={"type": "json_object"} if schema else None,
                temperature=0.3, # Precision for premium output
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Premium AI Call Failed: {e}", exc_info=True)
            return "{}"
        finally:
            gc.collect()

    async def process_interaction(self, user_id: int, text: str, user_name: str = "Client") -> AIIntentResponse:
        """
        Main entry point for real-time processing.
        Handles Context, Sentiment, and Intent in one pass.
        """
        try:
            # 1. Fetch Context from Redis (Long-term Memory)
            history = self.redis.client.lrange(f"history:{user_id}", 0, self.max_history)
            context_str = "\n".join(history) if history else "New Session"

            system_prompt = f"""
            You are FinBot Pro, a highly intelligent and witty AI Financial Sidekick.
            
            Persona:
            - Friendly, supportive, but financially strict when needed.
            - Uses natural, conversational Indonesian (with a touch of modern slang/Gen-Z style if appropriate).
            - Not just a recorder; you are an ADVISOR. Always add a tiny relevant comment to transactions.
            
            Categories: {', '.join(CATEGORIES)}
            
            Key Capabilities:
            1. **Smart Extraction**: Extract amount, category, and description accurately.
            2. **Context Awareness**: Look at the "Context History". If user buys coffee often, tease them gently.
            3. **Emotional Intelligence**: If user seems stressed (e.g., "boros banget gue"), be empathetic.
            4. **Duplicate Detection**: If the transaction looks exactly like the last one, warn them in the response.
            
            Response Style:
            - Short, punchy, and engaging.
            - Use emojis effectively 🚀.
            - Example: "Oke, 50rb buat Kopi Kenangan tercatat! ☕️ Jangan kebanyakan gula ya kak!"
            """

            user_prompt = f"""
            User: {user_name}
            Context: {context_str}
            Message: "{text}"
            
            Task: Analyze intent and generate a JSON response.
            
            JSON Schema:
            {{
                "intent": "record|query|insight|warning|chat",
                "confidence": 0.0-1.0,
                "sentiment": "positive|neutral|negative",
                "language": "id",
                "structured_data": {{
                    "amount": float,
                    "category": "string",
                    "description": "string",
                    "type": "expense|income"
                }},
                "suggested_response": "Your witty and helpful response here",
                "predictive_advice": "Optional short advice if pattern detected",
                "needs_live_update": true
            }}
            """

            raw_res = await self._call_llm(system_prompt, user_prompt, schema=AIIntentResponse)
            if not raw_res or raw_res == "{}":
                logger.warning(f"Empty response from LLM for user {user_id}")
                return AIIntentResponse(
                    intent="chat",
                    confidence=0.0,
                    suggested_response="Maaf, server AI sedang sibuk. Bisa diulangi lagi nanti?",
                    needs_live_update=False
                )

            try:
                data = json.loads(raw_res)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from LLM: {raw_res}")
                return AIIntentResponse(
                    intent="chat", 
                    confidence=0.0,
                    suggested_response="Maaf, saya gagal memproses permintaanmu. Coba gunakan format yang lebih sederhana.",
                    needs_live_update=False
                )
            
            # Validate with Pydantic model (and handle validation errors gracefully)
            try:
                response_model = AIIntentResponse(**data)
            except Exception as e:
                logger.error(f"Validation error for AI response: {e}")
                # Fallback to chat intent if structured data fails
                return AIIntentResponse(
                    intent="chat",
                    confidence=0.5,
                    suggested_response=data.get("suggested_response", "Maaf, saya kurang mengerti. Bisa dijelaskan lagi?"),
                    needs_live_update=False
                )

            # 2. Update Memory (Redis)
            try:
                self.redis.client.lpush(f"history:{user_id}", f"User: {text} | AI: {data.get('intent')}")
                self.redis.client.ltrim(f"history:{user_id}", 0, self.max_history)
            except Exception as e:
                logger.error(f"Redis write error: {e}")
            
            return response_model

        except Exception as e:
            logger.error(f"Critical error in process_interaction: {e}", exc_info=True)
            return AIIntentResponse(
                intent="chat",
                confidence=0.0,
                suggested_response="Maaf, terjadi kesalahan internal pada sistem AI. Tim teknis sedang memperbaikinya.",
                needs_live_update=False
            )

    async def transcribe_voice(self, audio_file_path: str) -> str:
        """
        Premium Voice-to-Finance: Menggunakan Groq Whisper untuk transkripsi instan.
        """
        client = self.client
        if not client: return ""
        
        try:
            with open(audio_file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(
                    file=(audio_file_path, file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="id" # Optimize for Indonesian
                )
                return transcription
        except Exception as e:
            logger.error(f"Voice Transcription Failed: {e}", exc_info=True)
            return ""
        finally:
            gc.collect()

    async def check_reconciliation(self, user_id: int, new_tx_data: Dict[str, Any]) -> bool:
        """
        Smart Reconciliation: Deteksi duplikat transaksi dalam 1 jam terakhir.
        """
        # 1. Get recent transactions (last 1 hour)
        recent_tx = self.redis.client.get(f"recent_tx:{user_id}")
        recent_tx_list = []

        if recent_tx:
            try:
                recent_tx_list = json.loads(recent_tx)
            except:
                pass
        
        if not recent_tx_list:
            # If not in redis, check DB for last 3 tx
            from core import db
            # Need to resolve DB ID from Telegram ID
            user = db.get_user(user_id)
            if user:
                recent_tx_list = db.get_transactions_history(user.id, limit=3)
            else:
                recent_tx_list = []

        # 2. AI-based similarity check
        new_amount = new_tx_data.get('amount', 0)
        new_category = new_tx_data.get('category')

        for tx in recent_tx_list:
            # Normalize data access (dict vs object)
            if isinstance(tx, dict):
                amount = tx.get('amount', 0)
                category = tx.get('category')
            else:
                amount = getattr(tx, 'amount', 0)
                category = getattr(tx, 'category', None)

            # Simple but effective check for now: same amount and similar category
            if abs(amount - new_amount) < 1.0 and category == new_category:
                return True # Potential duplicate
        
        return False
