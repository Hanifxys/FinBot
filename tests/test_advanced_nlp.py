
import unittest
import asyncio
from modules.nlp import NLPProcessor

class TestAdvancedNLPFeatures(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.nlp = NLPProcessor()

    async def test_multi_lang_sentiment(self):
        # Test Indonesian
        res_id = await self.nlp.analyze_financial_sentiment("Pasar saham sedang sangat bergairah hari ini!")
        self.assertIn(res_id["sentiment"], ["POSITIVE", "NEUTRAL", "NEGATIVE"])
        self.assertIn("language", res_id)
        
        # Test English
        res_en = await self.nlp.analyze_financial_sentiment("The market is crashing due to high inflation.")
        self.assertEqual(res_en["sentiment"], "NEGATIVE")

    async def test_qa_reasoning(self):
        question = "Apa dampak kenaikan suku bunga terhadap cicilan KPR?"
        res = await self.nlp.answer_question_with_reasoning(question)
        self.assertIn("answer", res)
        self.assertIn("reasoning_steps", res)
        self.assertGreater(len(res["reasoning_steps"]), 0)

    async def test_summarization_styles(self):
        text = """
        Bank Indonesia memutuskan untuk menahan suku bunga acuan BI 7-Day Reverse Repo Rate (BI7DRR) sebesar 6,00%. 
        Keputusan ini konsisten dengan kebijakan moneter yang pre-emptive dan forward looking untuk memastikan inflasi tetap terkendali dalam sasaran 2,5±1% pada 2024.
        """
        # Test Executive
        res_exec = await self.nlp.summarize_text(text, style="executive")
        self.assertIn("summary", res_exec)
        self.assertEqual(res_exec["style_applied"], "executive")
        
        # Test Concise
        res_conc = await self.nlp.summarize_text(text, style="concise")
        self.assertLess(len(res_conc["key_takeaways"]), 5)

if __name__ == "__main__":
    unittest.main()
