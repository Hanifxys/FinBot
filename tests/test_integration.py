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
    
    return handler, user

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
