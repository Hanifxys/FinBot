import pytest
import sys
import os
import json
from unittest.mock import MagicMock, patch

# Setup path
sys.path.append(os.getcwd())

# Mock Groq API Key
os.environ["GROQ_API_KEY"] = "mock_key"

from modules.nlp import NLPProcessor

class TestNLPComprehensive:
    @pytest.fixture
    def nlp(self):
        return NLPProcessor()

    @pytest.fixture
    def mock_groq(self):
        with patch('modules.nlp.Groq') as MockGroq:
            client = MockGroq.return_value
            # Setup mock response for chat.completions.create
            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock()]
            
            def side_effect(*args, **kwargs):
                # Analyze prompt to return relevant mock data
                messages = kwargs.get('messages', [])
                prompt = messages[0]['content']
                
                if "intent" in prompt.lower():
                    # Mock Intent Response
                    return_json = {"intent": "UNKNOWN", "confidence": 0.0}
                    if "tabungan" in prompt or "saldo" in prompt:
                        return_json = {"intent": "SHARING_INFO", "confidence": 0.95}
                    elif "investasi" in prompt:
                        return_json = {"intent": "ADD_TRANSACTION", "confidence": 0.8}
                    
                    mock_completion.choices[0].message.content = json.dumps(return_json)
                
                elif "financial entities" in prompt.lower():
                    # Mock Entity Extraction Response
                    return_json = {
                        "amount": 5000000,
                        "category": "Investasi",
                        "merchant": "Bibit",
                        "type": "expense"
                    }
                    mock_completion.choices[0].message.content = json.dumps(return_json)
                
                return mock_completion

            client.chat.completions.create.side_effect = side_effect
            yield client

    def test_regex_classification_basic(self, nlp):
        """Test standard regex patterns for speed and accuracy"""
        # Transaction
        res = nlp.hybrid_classify("makan 20k")
        assert res["intent"] == "ADD_TRANSACTION"
        
        # Check Budget
        res = nlp.hybrid_classify("cek sisa budget")
        assert res["intent"] == "CHECK_BUDGET"
        
        # Roast
        res = nlp.hybrid_classify("roast wallet gw")
        assert res["intent"] == "ROAST_WALLET"

    def test_slang_normalization(self, nlp):
        """Test if slang is correctly normalized before regex"""
        # "mkn" -> "makan"
        res = nlp.normalize_text("mkn siang 15rb")
        assert "makan" in res
        assert "15000" in res

        # "trf" -> "transfer"
        res = nlp.normalize_text("trf 50k")
        assert "transfer" in res

    def test_declarative_anti_robot(self, nlp):
        """Test if 'I have money' is NOT treated as 'I spent money'"""
        # Should be SHARING_INFO, not ADD_TRANSACTION
        res = nlp.hybrid_classify("saya punya tabungan 10jt")
        assert res["intent"] == "SHARING_INFO"
        
        # But this SHOULD be transaction
        res = nlp.hybrid_classify("tadi isi tabungan 500rb")
        assert res["intent"] == "ADD_TRANSACTION"

    def test_hybrid_fallback_to_llm(self, nlp, mock_groq):
        """Test if complex sentences fallback to LLM"""
        # Regex might fail on "investasi rutin bibit" if no amount explicitly seen as standard format
        # or if we force it to test LLM
        
        # Temporarily disable regex for "investasi" to force LLM or simulate complex query
        # Actually, "investasi" keyword is in category list, so extract_amount might catch it if amount present.
        # Let's try a sentence without clear amount but implies intent
        
        complex_text = "info dong kalau mau investasi saham bagusnya gimana" 
        # This has no amount, so regex ADD_TRANSACTION fails.
        # It's not HELP, not GREETING.
        # It should fall through to LLM.
        
        # Note: In our mock, we need to handle this case.
        # For this test, let's use the mocked "investasi" response
        
        res = nlp.hybrid_classify("saya mau mulai investasi di bibit") 
        # This triggers the mock_groq side_effect for "investasi" -> ADD_TRANSACTION (mocked)
        # In reality, this might be "ADVICE" intent, but for test coverage we check LLM was called.
        
        assert mock_groq.chat.completions.create.called

    def test_entity_extraction_llm(self, nlp, mock_groq):
        """Test detailed entity extraction via LLM"""
        text = "topup bibit 5jt buat dana pensiun"
        data = nlp.extract_transaction_data(text)
        
        # Should return data from LLM mock
        assert data["amount"] == 5000000
        assert data["category"] == "Investasi"
        assert data["merchant"] == "Bibit"

    def test_state_priority(self, nlp):
        """Test that conversation state overrides NLP"""
        # If state is WAITING_EDIT, "batal" should be CANCEL, not normal text
        res = nlp.hybrid_classify("batal", state="WAITING_EDIT_AMOUNT")
        assert res["intent"] == "CANCEL"
        
        # Normal text in EDIT state should be EDIT_TRANSACTION
        res = nlp.hybrid_classify("50000", state="WAITING_EDIT_AMOUNT")
        assert res["intent"] == "EDIT_TRANSACTION"

    def test_category_detection_smart(self, nlp):
        """Test fuzzy and keyword matching"""
        # Exact match
        assert nlp._detect_category("beli bensin") == "Transportasi"
        
        # Fuzzy match (typo)
        assert nlp._detect_category("beli bnsin") == "Transportasi"
        
        # Contextual heuristic
        assert nlp._detect_category("bayar cicilan") == "Tagihan"

if __name__ == "__main__":
    pytest.main([__file__])
