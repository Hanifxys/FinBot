import os
import json
from groq import Groq
from config import GROQ_API_KEY, CATEGORIES

class AIEngine:
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        self.model = "llama3-8b-8192"

    def parse_transaction(self, text):
        """
        Parses natural language text into a structured transaction JSON using Groq.
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

        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Groq Parsing Error: {e}")
            return None

    def generate_smart_insight(self, analysis_data):
        """
        Generates a human-like financial advice based on raw analysis data.
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

        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating AI insight: {e}"
