import sys
import os
import pytest
from unittest.mock import MagicMock
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.nlp import NLPProcessor
from modules.ocr import OCRProcessor
from modules.rules import RuleEngine
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer

# --- NLP TESTS ---
def test_nlp_process_text():
    nlp = NLPProcessor()
    
    # Test expense
    amount, category, type_ = nlp.process_text("makan siang 50rb")
    assert amount == 50000
    assert category == "Makanan"
    assert type_ == "expense"
    
    # Test income
    amount, category, type_ = nlp.process_text("gaji masuk 5jt")
    assert amount == 5000000
    assert category == "Gaji"
    assert type_ == "income"
    
    # Test variations
    assert nlp.process_text("kopi 25k")[0] == 25000
    assert nlp.process_text("beli sepatu 500.000")[0] == 500000

def test_nlp_extract_merchant():
    nlp = NLPProcessor()
    assert nlp.extract_merchant("ngopi di mixue 48rb") == "Mixue"
    assert nlp.extract_merchant("beli bensin pertamina 100k") == "Pertamina"

# --- OCR TESTS ---
def test_ocr_cleaning():
    ocr = OCRProcessor()
    assert ocr._clean_amount("50.000") == 50000.0
    assert ocr._clean_amount("1.250.000,00") == 1250000.0
    assert ocr._clean_amount("Total: 75,000") == 75000.0

# --- RULE ENGINE TESTS ---
def test_rule_engine():
    rules = RuleEngine()
    
    # Test boros rule
    tags1 = rules.evaluate({"category": "Makanan", "amount": 60000, "hour": 12})
    assert "boros" in tags1
    
    # Test impulsive rule
    tags2 = rules.evaluate({"category": "Belanja", "amount": 10000, "hour": 23})
    assert "impulsive" in tags2
    
    # Test no tags
    tags3 = rules.evaluate({"category": "Transportasi", "amount": 10000, "hour": 12})
    assert tags3 == []

# --- BUDGET MANAGER TESTS ---
def test_budget_recommendation():
    db_mock = MagicMock()
    bm = BudgetManager(db_mock)
    msg, recs = bm.get_allocation_recommendation(10000000)
    
    # Based on 50/20/10/20
    assert recs["Kebutuhan Pokok"] == 5000000
    assert recs["Tabungan"] == 2000000
    assert recs["Investasi"] == 1000000
    assert recs["Hiburan/Fleksibel"] == 2000000

def test_budget_burn_rate():
    db_mock = MagicMock()
    bm = BudgetManager(db_mock)
    
    # Mock budget: 1jt limit, 800rb used on day 1 (very fast)
    budget_mock = MagicMock()
    budget_mock.category = "Makanan"
    budget_mock.limit_amount = 1000000
    budget_mock.current_usage = 800000
    db_mock.get_user_budgets.return_value = [budget_mock]
    
    burn_msg = bm.get_burn_rate(1, "Makanan")
    assert burn_msg is not None
    assert "lebih cepat" in burn_msg

# --- ANALYSIS TESTS ---
def test_health_score():
    db_mock = MagicMock()
    analyzer = ExpenseAnalyzer(db_mock)
    
    # Mock data for healthy user
    db_mock.get_latest_income.return_value = MagicMock(amount=10000000)
    db_mock.get_user_budgets.return_value = [] # No over budget
    db_mock.get_monthly_report.return_value = [] # No impulse tx, no debt
    
    score = analyzer.calculate_health_score(1)
    assert score == 100
    
    # Mock data for impulsive user
    tx_impulse = MagicMock()
    tx_impulse.date = datetime(2026, 2, 4, 23, 0) # 11 PM
    tx_impulse.amount = 100000
    tx_impulse.type = 'expense'
    db_mock.get_monthly_report.return_value = [tx_impulse]
    
    score_low = analyzer.calculate_health_score(1)
    assert score_low < 100
