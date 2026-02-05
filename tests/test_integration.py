import pytest
from unittest.mock import MagicMock, patch
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Transaction
from database.db_handler import DBHandler
from modules.ai_engine import AIEngine
from modules.analysis import ExpenseAnalyzer

@pytest.fixture
def db_setup():
    from database.models import init_db
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.is_mock = True # Skip migration
    handler = DBHandler(session=session)
    
    # Create test user
    user = User(telegram_id=12345, username="test_user")
    session.add(user)
    session.commit()
    
    yield handler, user
    
    session.close()
    engine.dispose()

@pytest.fixture
def mock_ai():
    with patch('groq.Groq') as mock_groq:
        ai = AIEngine()
        ai.client.chat.completions.create = MagicMock()
        return ai

def test_full_transaction_flow(db_setup, mock_ai):
    """Test flow: Raw Text -> AI Parsing -> DB Storage -> Analysis"""
    db, user = db_setup
    
    # 1. Simulate AI Parsing
    raw_text = "makan siang nasi padang 35rb"
    mock_ai.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "amount": 35000,
            "category": "Makanan",
            "description": "nasi padang",
            "type": "expense",
            "is_transaction": True
        })))]
    )
    
    parsed_data = mock_ai.parse_transaction(raw_text)
    assert parsed_data["amount"] == 35000
    
    # 2. Store in DB
    tx = Transaction(
        user_id=user.id,
        amount=parsed_data["amount"],
        category=parsed_data["category"],
        description=parsed_data["description"],
        type=parsed_data["type"]
    )
    db.session.add(tx)
    db.session.commit()
    
    # Verify storage
    stored_tx = db.session.query(Transaction).filter_by(user_id=user.id).first()
    assert stored_tx.amount == 35000
    assert stored_tx.category == "Makanan"
    
    # 3. Analysis Insight
    analyzer = ExpenseAnalyzer(db)
    # Mock analysis to return raw data
    raw_insight = analyzer.analyze_patterns(user.id)
    
    # Simulate AI enhancing the insight
    mock_ai.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Wah, nasi padang emang enak tapi jangan sering-sering ya!"))]
    )
    
    final_insight = mock_ai.generate_smart_insight(raw_insight)
    assert "nasi padang" in final_insight or "enak" in final_insight

def test_db_handler_advanced_features(db_setup):
    db, user = db_setup
    
    # 1. Test get_transactions_history with filters
    db.add_transaction(user.id, 50000, "Makanan", "Makan", "expense")
    db.add_transaction(user.id, 100000, "Transport", "Ojek", "expense")
    
    # Test category filter
    history = db.get_transactions_history(user.id, category="Makanan")
    assert len(history) == 1
    assert history[0].category == "Makanan"
    
    # Test min_amount filter
    history = db.get_transactions_history(user.id, min_amount=75000)
    assert len(history) == 1
    assert history[0].amount == 100000
    
    # 2. Test delete_transaction and undo_last_transaction
    tx = db.get_transactions_history(user.id)[0]
    result = db.delete_transaction(user.id, tx.id)
    assert result is True
    assert len(db.get_transactions_history(user.id)) == 1
    
    db.undo_last_transaction(user.id)
    assert len(db.get_transactions_history(user.id)) == 0
    
    # 3. Test get_current_balance
    db.add_monthly_income(user.id, 5000000)
    db.add_transaction(user.id, 50000, "Makanan", "Makan", "expense")
    
    balance = db.get_current_balance(user.id)
    assert balance == 4950000
    
    # 4. Test add_monthly_income update case
    db.add_monthly_income(user.id, 6000000)
    income = db.get_latest_income(user.id)
    assert income.amount == 6000000
    
    # 5. Test saving goals progress failure
    result = db.update_saving_progress(user.id, 999, 1000) # Non-existent goal
    assert result is None
