import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from modules.nlp import NLPProcessor
from modules.ocr import OCRProcessor
from modules.rules import RuleEngine
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer
from database.db_handler import DBHandler

# 1. Comprehensive NLP Tests
def test_nlp_indonesian_variations():
    nlp = NLPProcessor()
    
    # Test currency suffixes
    assert nlp.process_text("makan 50 rebu")[0] == 50000
    assert nlp.process_text("beli kopi 25 k")[0] == 25000
    assert nlp.process_text("gaji 10jt")[0] == 10000000
    assert nlp.process_text("bonus 2mio")[0] == 2000000
    
    # Test decimal/comma handling
    assert nlp.process_text("belanja 150.500")[0] == 150500
    assert nlp.process_text("bensin 100,000")[0] == 100000

    # Test category mapping
    assert nlp.process_text("obat pusing 50rb")[1] == "Kesehatan"
    assert nlp.process_text("bayar spp sekolah 1jt")[1] == "Pendidikan"
    assert nlp.process_text("sedekah jumat 100rb")[1] == "Sosial"
    assert nlp.process_text("ganti oli motor 200rb")[1] == "Maintenance"

# 2. Comprehensive OCR Tests
def test_ocr_data_extraction_edge_cases():
    ocr = OCRProcessor()
    
    # Test cleaning amount with various formats
    assert ocr._clean_amount("Rp. 50.000,00") == 50000.0
    assert ocr._clean_amount("Total 1,250,000") == 1250000.0
    assert ocr._clean_amount("No Amount Here") == 0.0

# 3. Comprehensive Budget Manager Tests
def test_budget_manager_burn_rate_scenarios():
    db_mock = MagicMock()
    bm = BudgetManager(db_mock)
    
    # Case: Normal spending
    budget_normal = MagicMock(category="Makanan", limit_amount=1000000, current_usage=100000)
    db_mock.get_user_budgets.return_value = [budget_normal]
    assert "aman" in bm.get_burn_rate(1, "Makanan").lower()
    
    # Case: Critical spending (over budget)
    budget_critical = MagicMock(category="Lifestyle", limit_amount=1000000, current_usage=1100000)
    db_mock.get_user_budgets.return_value = [budget_critical]
    assert "melebihi" in bm.get_burn_rate(1, "Lifestyle").lower()

# 4. Comprehensive Expense Analyzer Tests
def test_analyzer_insights_and_health():
    db_mock = MagicMock()
    analyzer = ExpenseAnalyzer(db_mock)
    
    # Mock transactions for night spending pattern
    t1 = MagicMock(amount=100000, category="Makanan", date=datetime(2026, 2, 5, 20, 0), type="expense")
    t2 = MagicMock(amount=50000, category="Transportasi", date=datetime(2026, 2, 5, 12, 0), type="expense")
    db_mock.get_monthly_report.return_value = [t1, t2]
    
    insight = analyzer.analyze_patterns(1)
    assert "malam hari" in insight
    
    # Test health score
    db_mock.get_latest_income.return_value = MagicMock(amount=5000000)
    db_mock.get_user_budgets.return_value = [] # No over budget
    score = analyzer.calculate_health_score(1)
    assert score >= 80

# 5. DB Handler Preventive Migration Test
def test_db_handler_migration_logic(mocker):
    # Mock init_db to prevent table creation
    mocker.patch('database.db_handler.init_db')
    # Mock SessionLocal
    mock_session = MagicMock()
    mocker.patch('database.db_handler.SessionLocal', return_value=mock_session)
    
    from database.db_handler import DBHandler
    db = DBHandler()
    
    # Verify migration logic was called
    assert mock_session.execute.called
    # Check if ALTER TABLE was part of the calls
    call_args = mock_session.execute.call_args_list
    has_alter = any("ALTER TABLE" in str(arg) for arg in call_args)
    assert has_alter
