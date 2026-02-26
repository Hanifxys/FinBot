import os
import json
import logging
import time
import gc
from groq import Groq
from config import GROQ_API_KEY, CATEGORIES

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self):
        self._client = None
        # Updated to llama-3.3-70b-versatile for high quality and speed
        self.model = "llama-3.3-70b-versatile"

    @property
    def client(self):
        """Lazy load Groq client to save memory on startup"""
        if self._client is None and GROQ_API_KEY:
            try:
                self._client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
                self._client = None
        return self._client

    def _safe_ai_call(self, prompt, response_format=None, retries=2):
        """Helper to handle AI calls with retry logic and error handling"""
        client = self.client
        if not client:
            return None

        for attempt in range(retries + 1):
            try:
                params = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.model,
                }
                if response_format:
                    params["response_format"] = response_format

                response = client.chat.completions.create(**params)
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Groq API Error (attempt {attempt+1}): {e}")
                if attempt == retries:
                    return None
                time.sleep(1)
            finally:
                gc.collect()
        return None

    def parse_transaction(self, text):
        """
        Parses natural language text into a structured transaction JSON.
        """
        prompt = f"""
        Extract transaction details from this text: "{text}"
        Categories available: {', '.join(CATEGORIES)}
        
        Return ONLY a JSON object with:
        - "amount": (float)
        - "category": (string from available categories)
        - "description": (string, brief)
        - "type": ("expense" or "income")
        - "is_transaction": (boolean, false if text is just a chat)

        Rules:
        - Salary/receiving money -> type: "income", category: "Gaji"
        - No amount found -> "is_transaction": false
        - Example: "beli sate 50rb" -> {{"amount": 50000, "category": "Makanan", "description": "beli sate", "type": "expense", "is_transaction": true}}
        """
        
        content = self._safe_ai_call(prompt, response_format={"type": "json_object"})
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.error("Failed to decode AI JSON response")
        return None

    def detect_autonomous_intent(self, text, user_context=None):
        """
        Autonomous Intent Engine: Mendeteksi keinginan user tanpa command eksplisit.
        """
        prompt = f"""
        User Message: "{text}"
        User History Context: {user_context if user_context else "No previous context"}
        
        Analyze User Intent:
        1. Classify: "record", "query_budget", "need_insight", "predictive_warning", or "general_chat".
        2. If "record", provide structured data.
        3. If user is confused, provide proactive advice.
        
        Return ONLY a JSON object:
        {{
            "intent": "string",
            "confidence": 0.0-1.0,
            "structured_data": {{}},
            "suggested_response": "string (Professional Gen-Z Jakarta style)",
            "needs_live_update": boolean
        }}
        """

        content = self._safe_ai_call(prompt, response_format={"type": "json_object"})
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.error("Failed to decode Intent JSON response")
        
        return {"intent": "chat", "confidence": 0.0, "suggested_response": "Aduh, otak AI-ku lagi nge-lag nih. Coba lagi ya!"}

    def chat_response(self, text, user_name="Teman"):
        """
        Handles general chat messages with a friendly Gen-Z persona.
        """
        prompt = f"""
        Kamu adalah FinBot, asisten keuangan pribadi yang super friendly, cerdas, dan asik (Gen-Z Indonesia).
        User: "{text}"
        Nama: {user_name}

        Rules:
        1. Ramah, sopan, dan nyambung konteks.
        2. Bahasa gaul Jakarta yang profesional (aku, kamu, kak, sip).
        3. Singkat (max 3 kalimat).
        4. Selalu akhiri dengan pertanyaan pancingan/ajakan interaksi.
        """

        response = self._safe_ai_call(prompt)
        return response if response else f"Halo {user_name}! Ada yang bisa aku bantu catat hari ini? 💸"
