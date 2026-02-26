import sys
import os
import json
from unittest.mock import MagicMock, patch

# Setup path
sys.path.append(os.getcwd())

# Mock Groq API Key
os.environ["GROQ_API_KEY"] = "mock_key"

from modules.nlp import NLPProcessor

def test_nlp_comprehensive():
    print("Running NLP Comprehensive Tests...")
    
    nlp = NLPProcessor()
    
    # --- MOCK GROQ CLIENT ---
    # We mock where it is IMPORTED, not where it is defined
    # Since nlp.py does 'from groq import Groq' inside the property, we need to mock sys.modules or patch the class
    
    # Simpler approach: Set the client property directly with a Mock
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    
    def side_effect(*args, **kwargs):
        messages = kwargs.get('messages', [])
        prompt = messages[0]['content']
        
        if "intent" in prompt.lower():
            return_json = {"intent": "UNKNOWN", "confidence": 0.0}
            if "tabungan" in prompt or "saldo" in prompt:
                return_json = {"intent": "SHARING_INFO", "confidence": 0.95}
            elif "investasi" in prompt:
                return_json = {"intent": "ADD_TRANSACTION", "confidence": 0.8}
            
            mock_completion.choices[0].message.content = json.dumps(return_json)
        
        elif "financial entities" in prompt.lower():
            return_json = {
                "amount": 5000000,
                "category": "Investasi",
                "merchant": "Bibit",
                "type": "expense"
            }
            mock_completion.choices[0].message.content = json.dumps(return_json)
        
        return mock_completion

    mock_client.chat.completions.create.side_effect = side_effect
    nlp.client = mock_client # Inject mock directly
    nlp.groq_enabled = True # Force enable

    # --- TEST 1: Regex Basic ---
    print("\n[1] Testing Regex Classification...")
    res = nlp.hybrid_classify("makan 20k")
    if res["intent"] == "ADD_TRANSACTION": print("PASS: 'makan 20k'")
    else: print(f"FAIL: 'makan 20k' -> {res}")

    res = nlp.hybrid_classify("cek sisa budget")
    if res["intent"] == "CHECK_BUDGET": print("PASS: 'cek sisa budget'")
    else: print(f"FAIL: 'cek sisa budget' -> {res}")

    # --- TEST 2: Slang Normalization ---
    print("\n[2] Testing Slang Normalization...")
    norm = nlp.normalize_text("mkn siang 15rb")
    if "makan" in norm and "15000" in norm: print("PASS: 'mkn siang 15rb'")
    else: print(f"FAIL: {norm}")

    # --- TEST 3: Anti-Robot / Declarative ---
    print("\n[3] Testing Declarative Awareness...")
    res = nlp.hybrid_classify("saya punya tabungan 10jt")
    if res["intent"] == "SHARING_INFO": print("PASS: 'punya tabungan 10jt'")
    else: print(f"FAIL: {res}")

    # --- TEST 4: Hybrid Fallback (LLM) ---
    print("\n[4] Testing LLM Fallback...")
    res = nlp.hybrid_classify("saya mau mulai investasi di bibit")
    if res["intent"] == "ADD_TRANSACTION": print("PASS: LLM Fallback (Mocked)") # Mock returns ADD_TX for 'investasi'
    else: print(f"FAIL: {res}")

    # --- TEST 5: Entity Extraction ---
    print("\n[5] Testing Entity Extraction...")
    text = "topup bibit 5jt buat dana pensiun"
    data = nlp.extract_transaction_data(text)
    if data["amount"] == 5000000 and data["merchant"] == "Bibit": print("PASS: Extraction")
    else: print(f"FAIL: {data}")

    # --- TEST 6: Category Detection ---
    print("\n[6] Testing Category Detection...")
    if nlp._detect_category("beli bensin") == "Transportasi": print("PASS: Exact Match")
    else: print("FAIL: Exact Match")
    
    if nlp._detect_category("beli bnsin") == "Transportasi": print("PASS: Fuzzy Match")
    else: print("FAIL: Fuzzy Match")

if __name__ == "__main__":
    try:
        test_nlp_comprehensive()
        print("\nAll tests finished.")
    except Exception as e:
        print(f"\nTest Error: {e}")
