import os
import json
import logging
import time
from groq import Groq
from config import GROQ_API_KEY, CATEGORIES

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        # Updated to llama-3.3-70b-versatile as llama3-8b-8192 is decommissioned
        self.model = "llama-3.3-70b-versatile"

    def parse_transaction(self, text, retries=2):
        """
        Parses natural language text into a structured transaction JSON using Groq with retry logic.
        """
        if not self.client:
            return None

        prompt = f"""
        Extract transaction details from this text: "{text}"
        Categories available: {', '.join(CATEGORIES)}
        
        Return ONLY a JSON object with:
        - "amount": (float)
        - "category": (string from available categories)
        - "description": (string, brief)
        - "type": ("expense" or "income")
        - "is_transaction": (boolean, false if text is just a chat)

        If the text is about salary or receiving money, type is "income" and category is "Gaji".
        If no amount is found, "is_transaction" should be false.
        
        Example: "beli sate 50rb" -> {{"amount": 50000, "category": "Makanan", "description": "beli sate", "type": "expense", "is_transaction": true}}
        """

        for attempt in range(retries + 1):
            try:
                response = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                    response_format={"type": "json_object"}
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:
                logger.error(f"Groq Parsing Error (attempt {attempt+1}): {e}")
                if attempt == retries:
                    return None
                time.sleep(1)
        return None

    def generate_smart_insight(self, analysis_data, retries=2):
        """
        Generates a human-like financial advice based on raw analysis data with retry logic.
        """
        if not self.client:
            return "AI Key tidak ditemukan. Gunakan analisis standar."

        prompt = f"""
        Kamu adalah FinBot, asisten keuangan pribadi yang jujur, cerdas, dan sedikit humoris (ala Gen-Z Indonesia).
        Berdasarkan data berikut, berikan insight singkat (max 3-4 bullet points) dan saran yang tajam.
        
        Data:
        {analysis_data}
        
        Gunakan bahasa Indonesia yang santai tapi profesional. Berikan apresiasi jika bagus, dan tegur dengan sopan jika boros.
        """

        for attempt in range(retries + 1):
            try:
                response = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Error generating AI insight (attempt {attempt+1}): {e}")
                if attempt == retries:
                    return f"Aduh, AI-nya lagi capek nih (Error: {e}). Coba lagi nanti ya!"
                time.sleep(1)
        return "Aduh, AI-nya lagi capek nih. Coba lagi nanti ya!"

    def chat_response(self, text, user_name="Teman"):
        """
        Handles general chat messages using Groq AI with a friendly, Gen-Z persona.
        """
        if not self.client:
            return f"Halo {user_name}! Aku FinBot. Ada yang bisa kubantu catat hari ini?"

        prompt = f"""
        Kamu adalah FinBot, asisten keuangan pribadi yang super friendly, cerdas, dan asik diajak ngobrol (ala Gen-Z Indonesia).
        User saat ini menyapamu/bertanya: "{text}"
        Nama user: {user_name}

        Tugasmu:
        1. Balas dengan ramah dan nyambung dengan konteks chat user.
        2. Gunakan bahasa gaul Jakarta/Gen-Z yang sopan (pake 'kamu', 'aku', 'kak', 'oke', 'sip', dll).
        3. Selipkan sedikit motivasi keuangan jika memungkinkan, tapi jangan menggurui.
        4. Jika user hanya menyapa, balas dengan ceria dan tawarkan bantuan untuk mencatat pengeluaran.
        5. Selalu akhiri jawaban dengan pertanyaan pancingan atau ajakan agar user terus berinteraksi (contoh: "Ada lagi yang mau dicatat hari ini?", "Mau cek budget kamu nggak?", "Gimana kabar dompet hari ini?").
        6. Jaga jawaban tetap singkat dan padat (max 2-3 kalimat).
        """

        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error in AI chat response: {e}")
            return f"Halo {user_name}! Ada yang bisa aku bantu catat hari ini? 💸"
