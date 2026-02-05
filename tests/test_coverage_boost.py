import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from database.db_handler import DBHandler
from modules.budget import BudgetManager
from modules.ocr import OCRProcessor
from modules.analysis import ExpenseAnalyzer
from modules.rules import RuleEngine
from database.models import Budget, MonthlyIncome, Transaction

@pytest.fixture
def mock_db():
    return MagicMock()

# --- DBHandler Coverage ---

def test_db_effective_date():
    # Pass a mock session to avoid DB connection in constructor
    handler = DBHandler(session=MagicMock())
    handler.cutoff_hour = 4
    
    # 3 AM today should be yesterday
    dt_3am = datetime(2026, 2, 5, 3, 0)
    assert handler.get_effective_date(dt_3am) == datetime(2026, 2, 4).date()
    
    # 5 AM today should be today
    dt_5am = datetime(2026, 2, 5, 5, 0)
    assert handler.get_effective_date(dt_5am) == datetime(2026, 2, 5).date()

# --- BudgetManager Coverage ---

def test_budget_status_thresholds(mock_db):
    bm = BudgetManager(mock_db)
    user_id = 1
    
    # Mock budgets
    b1 = MagicMock(category="Makanan", limit_amount=100000, current_usage=85000) # 85%
    b2 = MagicMock(category="Transport", limit_amount=100000, current_usage=110000) # 110%
    b3 = MagicMock(category="Belanja", limit_amount=100000, current_usage=50000) # 50%
    mock_db.get_user_budgets.return_value = [b1, b2, b3]
    
    # Test 80% warning
    msg1 = bm.check_budget_status(user_id, "Makanan")
    assert "WARNING" in msg1
    assert "85%" in msg1
    
    # Test 100% limit
    msg2 = bm.check_budget_status(user_id, "Transport")
    assert "LIMIT" in msg2
    assert "100%" in msg2
    
    # Test normal
    msg3 = bm.check_budget_status(user_id, "Belanja")
    assert "Sisa budget Belanja" in msg3
    assert "WARNING" not in msg3

def test_budget_report_periods(mock_db):
    bm = BudgetManager(mock_db)
    user_id = 1
    
    # Mock transactions
    t1 = MagicMock(amount=50000, category="Makanan", type="expense")
    mock_db.get_sliding_window_transactions.return_value = [t1]
    mock_db.get_monthly_report.return_value = [t1]
    
    # Test 7 days
    report_7 = bm.generate_report(user_id, period='7days')
    assert "7 Hari Terakhir" in report_7
    mock_db.get_sliding_window_transactions.assert_called_with(user_id, days=7)
    
    # Test 30 days
    report_30 = bm.generate_report(user_id, period='30days')
    assert "30 Hari Terakhir" in report_30
    mock_db.get_sliding_window_transactions.assert_called_with(user_id, days=30)

# --- OCRProcessor Coverage ---

def test_ocr_clean_amount():
    ocr = OCRProcessor()
    
    # Test Indonesian formats
    assert ocr._clean_amount("1.250.000,00") == 1250000.0
    assert ocr._clean_amount("1,250,000.00") == 1250000.0
    assert ocr._clean_amount("50.000") == 50000.0
    assert ocr._clean_amount("Rp 100.000,50") == 100000.5
    assert ocr._clean_amount("10,00") == 10.0

# --- ExpenseAnalyzer Coverage ---

def test_health_score_calculation(mock_db):
    analyzer = ExpenseAnalyzer(mock_db)
    user_id = 1
    
    # Setup state for score 100
    income = MagicMock(amount=10000000)
    mock_db.get_latest_income.return_value = income
    mock_db.get_user_budgets.return_value = []
    mock_db.get_monthly_report.return_value = []
    
    assert analyzer.calculate_health_score(user_id) == 100
    
    # Penalty 1: Over budget
    b1 = MagicMock(category="Makanan", limit_amount=100, current_usage=150)
    mock_db.get_user_budgets.return_value = [b1]
    assert analyzer.calculate_health_score(user_id) == 90 # -10
    
    # Penalty 2: Impulse spending (Night > 50k after 10 PM)
    t_impulse = MagicMock(amount=60000, date=datetime(2026, 2, 5, 23, 0), type="expense")
    mock_db.get_monthly_report.return_value = [t_impulse]
    assert analyzer.calculate_health_score(user_id) == 85 # 100 - 10 (budget) - 5 (impulse)
    
    # Penalty 3: Living beyond means
    t_huge = MagicMock(amount=11000000, date=datetime(2026, 2, 5, 12, 0), type="expense")
    mock_db.get_monthly_report.return_value = [t_huge]
    mock_db.get_user_budgets.return_value = [] # reset
    # 100 - 0 (budget) - 0 (impulse) - 20 (over income)
    assert analyzer.calculate_health_score(user_id) == 80

# --- RuleEngine Coverage ---

def test_rule_engine_tags():
    re = RuleEngine()
    
    # Test Boros
    tags1 = re.evaluate({"category": "Makanan", "amount": 60000})
    assert "boros" in tags1
    
    # Test Impulsive
    tags2 = re.evaluate({"hour": 23, "amount": 10000})
    assert "impulsive" in tags2
    
    # Test Multiple
    tags3 = re.evaluate({"category": "Makanan", "amount": 60000, "hour": 23})
    assert "boros" in tags3
    assert "impulsive" in tags3
    
    # Test None
    tags4 = re.evaluate({"category": "Transport", "amount": 10000, "hour": 12})
    assert tags4 == []
