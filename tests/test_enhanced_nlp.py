import pytest
from modules.nlp import NLPProcessor

@pytest.fixture
def nlp():
    return NLPProcessor()

def test_feedback_intent(nlp):
    # Test UI feedback detection
    res = nlp.classify_intent_with_context("kok uinya jelek si")
    # Should either be SMALL_TALK (from handle_small_talk) or FEEDBACK (from _control_patterns)
    assert res["intent"] in ["SMALL_TALK", "FEEDBACK", "UNKNOWN"]
    # It definitely should NOT be ADD_TRANSACTION
    assert res["intent"] != "ADD_TRANSACTION"

def test_general_question(nlp):
    # Test general knowledge question
    res = nlp.classify_intent_with_context("siapa presiden indonesia")
    assert res["intent"] in ["SMALL_TALK", "QUESTION", "UNKNOWN"]
    
def test_transaction_stricter(nlp):
    # Test if plain numbers without context are still transactions but with lower confidence if complex
    res = nlp.classify_intent_with_context("100000")
    assert res["intent"] == "ADD_TRANSACTION"
    
    # "beli 50rb" should be high confidence
    res2 = nlp.classify_intent_with_context("beli 50rb")
    assert res2["intent"] == "ADD_TRANSACTION"
    assert res2["confidence"] >= 0.9

def test_greeting(nlp):
    res = nlp.classify_intent_with_context("halo finbot")
    assert res["intent"] == "GREETING"
