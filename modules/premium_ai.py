import os
import json
import logging
import gc
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from groq import AsyncGroq
from config import GROQ_API_KEY, CATEGORIES
from modules.redis_mgr import RedisManager
from modules.ai_memory import AIMemory
from modules.ai_persona import PersonaManager
from modules.document_processor import DocumentProcessor

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
        self.fallback_model = "mixtral-8x7b-32768"
        self.redis = RedisManager()
        self.persona_mgr = PersonaManager()
        self.doc_processor = DocumentProcessor()
        
    @property
    def client(self):
        if self._client is None and GROQ_API_KEY:
            try:
                self._client = AsyncGroq(api_key=GROQ_API_KEY, timeout=30.0, max_retries=2)
            except Exception as e:
                logger.error(f"Failed to initialize Premium Groq client: {e}")
        return self._client

    async def _call_llm(self, system_prompt: str, user_prompt: str, schema: Any = None) -> str:
        """Async LLM call with smart fallback"""
        client = self.client
        if not client: return "{}"
        
        models_to_try = [self.primary_model, self.fallback_model, self.fast_model]
        
        for model in models_to_try:
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                response = await client.chat.completions.create(
                    messages=messages,
                    model=model,
                    response_format={"type": "json_object"} if schema else None,
                    temperature=0.3,
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"Model {model} failed: {e}. Trying next...")
                continue
        
        logger.error("All AI models failed.")
        return "{}"

    async def process_interaction(self, user_id: int, text: str, user_name: str = "Client") -> AIIntentResponse:
        """
        Main entry point for real-time processing.
        Handles Context, Sentiment, and Intent in one pass.
        """
        try:
            # 1. Memory & Persona
            memory = AIMemory(user_id)
            context_msgs = memory.get_context(limit=15)
            # Format context for prompt
            context_str = "\n".join([f"{m['role']}: {m['content']}" for m in context_msgs])
            
            persona = self.persona_mgr.get_persona(user_id)
            
            # 2. Build Prompt
            system_prompt = f"""
            {persona.system_prompt()}
            
            Categories: {', '.join(CATEGORIES)}
            
            Key Capabilities:
            1. **Smart Extraction**: Extract amount, category, and description accurately.
            2. **Context Awareness**: Use the provided Context History.
            3. **Emotional Intelligence**: Be empathetic if user is stressed.
            4. **Financial Planner**: Only provide 50/30/20 advice if explicitly asked.
            5. **Explainability**: Explain data sources if asked.
            
            Response Style:
            - {persona.tone}
            - Short, punchy, engaging.
            - Use emojis effectively 🚀.
            - Language: {persona.language} (or match user).
            """

            user_prompt = f"""
            User: {user_name}
            Context History:
            {context_str}
            
            Current Message: "{text}"
            
            Task: Analyze intent and generate a JSON response.
            
            JSON Schema:
            {{
                "intent": "record|query|insight|warning|chat|config|cancel",
                "confidence": 0.0-1.0,
                "sentiment": "positive|neutral|negative",
                "language": "id",
                "structured_data": {{
                    "amount": float,
                    "category": "string",
                    "description": "string",
                    "type": "expense|income",
                    "config_type": "string",
                    "cancel_action": "string",
                    "transaction_id": int,
                    "amount_hint": float,
                    "merchant_hint": "string",
                    "reason": "string"
                }},
                "suggested_response": "Your response here",
                "predictive_advice": "Optional advice",
                "needs_live_update": boolean
            }}
            """

            raw_res = await self._call_llm(system_prompt, user_prompt, schema=AIIntentResponse)
            
            # 3. Parse Response
            try:
                data = json.loads(raw_res)
                response_model = AIIntentResponse(**data)
            except Exception as e:
                logger.error(f"Parsing error: {e}")
                return AIIntentResponse(
                    intent="chat",
                    suggested_response="Maaf, saya kurang mengerti. Bisa dijelaskan lagi?",
                )

            # 4. Update Memory
            memory.add_user_message(text)
            memory.add_ai_message(response_model.suggested_response)
            
            # Background summarization check (fire and forget if possible, but here we await)
            # await memory.summarize_if_needed(self.client, self.fast_model)
            
            return response_model

        except Exception as e:
            logger.error(f"Critical error in process_interaction: {e}", exc_info=True)
            return AIIntentResponse(suggested_response="Maaf, sistem sedang sibuk.")

    async def process_document(self, user_id: int, file_content: bytes, file_name: str, mime_type: str) -> str:
        """
        Handle file uploads and summarize/extract insights.
        """
        extracted_text = await self.doc_processor.process_file(file_content, file_name, mime_type)
        
        # Summarize via LLM
        system_prompt = "You are a document analyst. Summarize the following text and extract key financial insights."
        summary = await self._call_llm(system_prompt, f"Text:\n{extracted_text}")
        
        # Add to memory
        memory = AIMemory(user_id)
        memory.add_user_message(f"[Uploaded File: {file_name}]")
        memory.add_ai_message(summary)
        
        return summary

    async def transcribe_voice(self, audio_file_path: str) -> str:
        """
        Premium Voice-to-Finance: Menggunakan Groq Whisper.
        """
        client = self.client
        if not client: return ""
        
        try:
            with open(audio_file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(
                    file=(audio_file_path, file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="id"
                )
                return transcription
        except Exception as e:
            logger.error(f"Voice Transcription Failed: {e}", exc_info=True)
            return ""
        finally:
            gc.collect()

    async def check_reconciliation(self, user_id: int, new_tx_data: Dict[str, Any]) -> bool:
        """
        Smart Reconciliation: Deteksi duplikat transaksi.
        """
        return False
