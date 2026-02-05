import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
import pandas as pd
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
    assert nlp._extract_amount("makan 50 rebu") == 50000
    assert nlp._extract_amount("beli kopi 25 k") == 25000
    assert nlp._extract_amount("gaji 10jt") == 10000000
    assert nlp._extract_amount("bonus 2mio") == 2000000
    
    # Test decimal/comma handling
    assert nlp._extract_amount("belanja 150.500") == 150500
    # Note: current implementation replaces comma with dot for decimals in normalize_text
    assert nlp._extract_amount("bensin 100,000") == 100000

    # Test category mapping
    assert nlp._detect_category("obat pusing 50rb") == "Kesehatan"
    assert nlp._detect_category("bayar spp sekolah 1jt") == "Pendidikan"
    assert nlp._detect_category("sedekah jumat 100rb") == "Sosial"
    assert nlp._detect_category("ganti oli motor 200rb") == "Maintenance"

def test_nlp_intent_classification():
    nlp = NLPProcessor()
    assert nlp.classify_intent("makan 50rb")["intent"] == "ADD_TRANSACTION"
    assert nlp.classify_intent("sisa budget")["intent"] == "CHECK_BUDGET"
    assert nlp.classify_intent("halo bot")["intent"] == "GREETING"
    assert nlp.classify_intent("help")["intent"] == "HELP"
    assert nlp.classify_intent("laporan bulan ini")["intent"] == "QUERY_SUMMARY"
    assert nlp.classify_intent("batal", state="WAITING_EDIT_AMOUNT")["intent"] == "CANCEL"
    assert nlp.classify_intent("ganti nominal", state="WAITING_EDIT_AMOUNT")["intent"] == "EDIT_TRANSACTION"

def test_nlp_parsing_full():
    nlp = NLPProcessor()
    
    # Test process_text
    amt, cat, typ = nlp.process_text("makan 50rb")
    assert amt == 50000
    assert cat == "Makanan"
    assert typ == "expense"

    amt2, cat2, typ2 = nlp.process_text("gaji 10jt")
    assert amt2 == 10000000
    assert cat2 == "Gaji"
    assert typ2 == "income"

    # Test parse_message
    res = nlp.parse_message("sisa budget makan")
    assert res["intent"] == "query_budget"
    assert res["category"] == "Makanan"

    res_report = nlp.parse_message("minta laporan")
    assert res_report["intent"] == "get_report"

    res_unknown = nlp.parse_message("apa ya")
    assert res_unknown["intent"] == "unknown"

    # Test extract_transaction_data
    data = nlp.extract_transaction_data("beli kopi 25k")
    assert data["amount"] == 25000
    assert data["category"] == "Makan"
    assert data["type"] == "expense"
    
    # Test validate_edit
    assert nlp.validate_edit("amount", "50rb")["valid"] is True
    assert nlp.validate_edit("category", "makan")["valid"] is True
    assert nlp.validate_edit("invalid", "something")["valid"] is False

def test_nlp_llm_mock():
    nlp = NLPProcessor()
    nlp.groq_enabled = True
    nlp.client = MagicMock()
    
    # Mock LLM response
    mock_choice = MagicMock()
    mock_choice.message.content = '{"intent": "ADD_TRANSACTION", "confidence": 0.85}'
    nlp.client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    
    result = nlp.classify_intent("beli sesuatu yang aneh")
    assert result["intent"] == "ADD_TRANSACTION"

def test_nlp_merchant_extraction():
    nlp = NLPProcessor()
    assert nlp.extract_merchant("beli mixue 15rb") == "Mixue"
    assert nlp.extract_merchant("bayar indihome 400k") == "Indihome"
    assert nlp.extract_merchant("gaji kantor") == "Kantor"

# 2. Comprehensive OCR Tests
def test_ocr_logic():
    ocr = OCRProcessor()
    
    # Test cleaning amount with various formats
    assert ocr._clean_amount("Rp. 50.000,00") == 50000.0
    assert ocr._clean_amount("Total 1,250,000") == 1250000.0
    assert ocr._clean_amount("No Amount Here") == 0.0

    # Test process_receipt logic with mocks
    with patch.object(OCRProcessor, 'reader', new_callable=PropertyMock) as mock_reader:
        mock_instance = MagicMock()
        mock_reader.return_value = mock_instance
        
        # Mock easyocr result format: [([coord], text, prob), ...]
        mock_instance.readtext.return_value = [
            ([0,0], "WARUNG NASI", 0.9),
            ([0,1], "25/12/2025", 0.9),
            ([0,2], "TOTAL 50000", 0.9)
        ]
        
        result = ocr.process_receipt("dummy_path")
        assert result["amount"] == 50000.0
        assert result["merchant"] == "WARUNG NASI"
        assert result["date"] == "25/12/2025"

# 3. Comprehensive Budget Manager Tests
def test_budget_manager_logic():
    db_mock = MagicMock()
    bm = BudgetManager(db_mock)
    
    # Mock budget status
    budget = MagicMock(category="Makanan", limit_amount=1000000, current_usage=850000)
    db_mock.get_user_budgets.return_value = [budget]
    
    status = bm.check_budget_status(1, "Makanan")
    assert "WARNING" in status
    assert "85%" in status

    # Test 100% usage
    budget_full = MagicMock(category="Makanan", limit_amount=1000000, current_usage=1000000)
    db_mock.get_user_budgets.return_value = [budget_full]
    status_full = bm.check_budget_status(1, "Makanan")
    assert "LIMIT" in status_full

    # Test detailed status
    detailed = bm.get_detailed_budget_status(1, "Makanan")
    assert "Limit: Rp 1,000,000" in detailed
    
    # Test detailed status empty
    db_mock.get_user_budgets.return_value = []
    detailed_empty = bm.get_detailed_budget_status(1, "Hiburan")
    assert "Limit: Rp 0" in detailed_empty

    # Test report generation
    t1 = MagicMock(amount=50000, category="Makan", type="expense")
    t2 = MagicMock(amount=100000, category="Gaji", type="income")
    db_mock.get_monthly_report.return_value = [t1, t2]
    report = bm.generate_report(1, "monthly")
    assert "Laporan Keuangan" in report
    assert "Makan: Rp 50,000" in report
    assert "Gaji: Rp 100,000" in report

    # Test report 7days and 30days
    db_mock.get_sliding_window_transactions.return_value = [t1]
    report_7d = bm.generate_report(1, "7days")
    assert "7 Hari Terakhir" in report_7d
    report_30d = bm.generate_report(1, "30days")
    assert "30 Hari Terakhir" in report_30d
    
    # Test empty report
    db_mock.get_monthly_report.return_value = []
    report_empty = bm.generate_report(1, "monthly")
    assert "Belum ada transaksi" in report_empty

    # Mock allocation recommendation
    msg, alloc = bm.get_allocation_recommendation(10000000)
    assert alloc["Kebutuhan Pokok"] == 5000000
    assert alloc["Tabungan"] == 2000000

    # Test burn rate
    # Set current day to 15th (50% of month)
    with patch('modules.budget.datetime') as mock_date:
        mock_date.now.return_value = datetime(2026, 2, 15)
        mock_date.combine = datetime.combine
        # Usage 70% at day 15 (expected 50%) -> diff 20% > 10%
        budget_fast = MagicMock(category="Makanan", limit_amount=1000000, current_usage=700000)
        db_mock.get_user_budgets.return_value = [budget_fast]
        burn_msg = bm.get_burn_rate(1, "Makanan")
        assert "lebih cepat" in burn_msg
        
        # Test burn rate normal
        budget_normal = MagicMock(category="Makanan", limit_amount=1000000, current_usage=400000)
        db_mock.get_user_budgets.return_value = [budget_normal]
        assert bm.get_burn_rate(1, "Makanan") is None

        # Test burn rate no budget
        db_mock.get_user_budgets.return_value = []
        assert bm.get_burn_rate(1, "Makanan") is None

# 4. Comprehensive Expense Analyzer Tests
def test_analyzer_insights_and_health():
    db_mock = MagicMock()
    analyzer = ExpenseAnalyzer(db_mock)
    
    # Test patterns empty
    db_mock.get_monthly_report.return_value = []
    assert analyzer.analyze_patterns(1) == ""

    # Mock transactions for patterns
    # 60% spending at night
    t1 = MagicMock(amount=60000, category="Makanan", date=datetime(2026, 2, 5, 20, 0), type="expense")
    t2 = MagicMock(amount=40000, category="Transportasi", date=datetime(2026, 2, 5, 12, 0), type="expense")
    db_mock.get_monthly_report.return_value = [t1, t2]
    
    insight = analyzer.analyze_patterns(1)
    assert "malam hari" in insight
    assert "60%" in insight
    
    # Test health score
    db_mock.get_latest_income.return_value = MagicMock(amount=5000000)
    db_mock.get_user_budgets.return_value = [] # No over budget
    db_mock.get_monthly_report.return_value = []
    score = analyzer.calculate_health_score(1)
    assert score == 100 # Perfect score for no over budget and no impulse

    # Test health score with issues
    # Over budget (-10)
    b1 = MagicMock(category="Makanan", limit_amount=1000, current_usage=2000)
    db_mock.get_user_budgets.return_value = [b1]
    # Impulse spending at night (-5 each)
    t_impulse = MagicMock(amount=60000, category="Makanan", date=datetime(2026, 2, 5, 23, 0), type="expense")
    db_mock.get_monthly_report.return_value = [t_impulse]
    # Total expense > income (-20)
    db_mock.get_latest_income.return_value = MagicMock(amount=10000)
    
    score_low = analyzer.calculate_health_score(1)
    assert score_low < 100
    
    # Test health score no income
    db_mock.get_latest_income.return_value = None
    assert analyzer.calculate_health_score(1) == 50

def test_analyzer_anomaly_detection():
    db_mock = MagicMock()
    analyzer = ExpenseAnalyzer(db_mock)
    
    # 1. Test large transaction detection
    t_large = MagicMock(amount=5000000, category="Hiburan", type="expense")
    db_mock.get_monthly_report.return_value = [t_large]
    
    insight = analyzer.analyze_patterns(1)
    assert "TRANSAKSI BESAR" in insight
    assert "Rp5,000,000" in insight

    # 2. Test frequency detection
    t1 = MagicMock(amount=20000, category="Makanan", date=datetime.now(), type="expense")
    t2 = MagicMock(amount=20000, category="Makanan", date=datetime.now(), type="expense")
    t3 = MagicMock(amount=20000, category="Makanan", date=datetime.now(), type="expense")
    db_mock.get_monthly_report.return_value = [t1, t2, t3]
    
    insight_freq = analyzer.analyze_patterns(1)
    assert "FREKUENSI TINGGI" in insight_freq
    assert "Makanan" in insight_freq

# 5. DB Handler Tests
def test_db_handler_full():
    # Use SQLite memory for real testing
    with patch('database.db_handler.init_db'):
        with patch('database.db_handler.SessionLocal') as mock_session_local:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from database.models import Base
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            mock_session_local.return_value = session
            
            db = DBHandler()
            
            # Test User operations
            user = db.get_or_create_user(12345, "testuser")
            assert user.telegram_id == 12345
            assert db.get_user(12345).username == "testuser"
            assert len(db.get_all_users()) == 1
            
            # Test Budget operations (Set first so transaction can update it)
            db.set_budget(user.id, "Makanan", 1000000)
            budgets = db.get_user_budgets(user.id)
            assert len(budgets) == 1
            assert budgets[0].limit_amount == 1000000
            
            # Test Transaction operations
            tx = db.add_transaction(user.id, 50000, "Makanan", "makan siang")
            assert tx.amount == 50000
            assert len(db.get_daily_transactions(user.id, tx.date.date())) == 1
            assert len(db.get_sliding_window_transactions(user.id)) == 1
            
            # Check budget usage (should be 50000 from transaction)
            assert db.get_user_budgets(user.id)[0].current_usage == 50000
            
            db.update_budget_usage(user.id, "Makanan", 50000)
            assert db.get_user_budgets(user.id)[0].current_usage == 100000
            
            # Test Income operations
            db.add_monthly_income(user.id, 10000000)
            assert db.get_latest_income(user.id).amount == 10000000
            
            # Test effective date cutoff (4 AM)
            assert db.get_effective_date(datetime(2026, 2, 5, 3, 0)) == datetime(2026, 2, 4).date()
            assert db.get_effective_date(datetime(2026, 2, 5, 5, 0)) == datetime(2026, 2, 5).date()
            
            # Test Report
            report = db.get_monthly_report(user.id, datetime.now().month, datetime.now().year)
            assert len(report) == 1

# 6. Rule Engine Tests
def test_rule_engine():
    rules = RuleEngine()
    # "category == 'Makanan' and amount > 50000" -> "boros"
    tags = rules.evaluate({"category": "Makanan", "amount": 60000})
    assert "boros" in tags
    
    # "hour >= 22" -> "impulsive"
    tags_night = rules.evaluate({"category": "Transport", "amount": 10000, "hour": 23})
    assert "impulsive" in tags_night
