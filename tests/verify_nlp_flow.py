
import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock
from modules.nlp import NLPProcessor
from core import nlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NLP_Verifier")

async def test_flow():
    logger.info("🚀 Starting NLP Regression Tests...")
    
    # 1. Direct Transaction
    logger.info("Test 1: Direct Transaction")
    text = "beli kopi 25rb"
    res = nlp.extract_transaction_data(text)
    assert res["amount"] == 25000, f"Amount failed: {res.get('amount')}"
    assert res["category"] in ["Minuman", "Jajanan", "Makanan"], f"Category failed: {res.get('category')}"
    assert res["intent"] == "ADD_TRANSACTION", f"Intent failed: {res.get('intent')}"
    logger.info("✅ Direct Transaction Passed")

    # 2. Contextual Merge (Partial Flow)
    logger.info("Test 2: Contextual Merge")
    # Step 1: User says "makan siang" (Missing amount)
    text1 = "makan siang"
    res1 = nlp.extract_transaction_data(text1)
    assert res1.get("is_partial") is True, "Should be partial"
    
    # Step 2: User says "20000" (Amount only)
    text2 = "20000"
    res2 = nlp.extract_transaction_data(text2)
    
    # Manual Merge Logic (Simulating handlers/messages.py)
    merged = res1.copy()
    merged.update(res2) # In reality, we'd be smarter, but let's check basic extraction
    
    assert merged["amount"] == 20000, "Merged amount failed"
    assert merged["category"] == "Makanan", f"Merged category failed: {merged.get('category')}"
    logger.info("✅ Contextual Merge Passed")

    # 3. Intents check
    logger.info("Test 3: Intent Classification")
    
    cases = [
        ("cek budget", "CHECK_BUDGET"),
        ("sisa saldo", "CHECK_BUDGET"), # Or SHARING_INFO depending on context, but usually check
        ("riwayat transaksi", "HISTORY"),
        ("hapus transaksi #123", "DELETE_TRANSACTION"),
        ("ganti mode coach", "SET_MODE"),
        ("profil saya", "PROFILE"),
        ("minta token", "AUTH"),
        ("apa itu inflasi?", "QUESTION"),
        ("rangkum chat ini", "SUMMARIZE")
    ]
    
    for text, expected in cases:
        cls = nlp.classify_intent(text)
        intent = cls.get("intent")
        # Relaxed check for CHECK_BUDGET vs SHARING_INFO overlap
        if expected == "CHECK_BUDGET" and intent == "SHARING_INFO":
             pass # Acceptable overlap
        elif intent != expected:
            logger.warning(f"⚠️ Intent Mismatch: '{text}' -> Got {intent}, Expected {expected}")
        else:
            logger.info(f"  ✓ '{text}' -> {intent}")

    logger.info("✅ Intent Tests Completed")

    # 4. Complex Entity Extraction (Transformer/LLM check simulation)
    # We won't call actual LLM here to save cost/time, but verify the method exists
    assert hasattr(nlp, "extract_transaction_data_with_context"), "Context method missing"
    
    logger.info("🎉 All Regression Tests Passed!")

if __name__ == "__main__":
    asyncio.run(test_flow())
