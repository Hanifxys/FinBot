import pytest
import os

def test_environment_vars():
    """Test if config variables can be loaded (using defaults)"""
    # Import config here to avoid issues with missing env vars during test
    from config import DATABASE_URL, GROQ_API_KEY
    assert DATABASE_URL is not None
    assert GROQ_API_KEY is not None

def test_nlp_processor():
    """Test basic NLP initialization"""
    from modules.nlp import NLPProcessor
    nlp = NLPProcessor()
    assert nlp is not None
    
    # Test normalization
    norm = nlp.normalize_text("2jt")
    assert "2000000" in norm
