import pytest
import os
import json
import csv
from unittest.mock import MagicMock, patch
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Transaction, SavingGoal
from database.db_handler import DBHandler
from modules.ai_engine import AIEngine

# --- FIXTURES ---

@pytest.fixture
def db_session():
    """Create a fresh in-memory database for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def db_handler(db_session):
    """DBHandler with mocked session."""
    handler = DBHandler()
    handler.session = db_session
    return handler

@pytest.fixture
def ai_engine():
    """AIEngine with mocked Groq client."""
    with patch('groq.Groq') as mock_groq:
        engine = AIEngine()
        # Mock the completions.create method
        engine.client.chat.completions.create = MagicMock()
        return engine

# --- AI ENGINE TESTS ---

def test_ai_parse_transaction(ai_engine):
    # Mock successful JSON response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "amount": 50000,
            "category": "Makanan",
            "description": "makan sate",
            "type": "expense",
            "is_transaction": True
        })))
    ]
    ai_engine.client.chat.completions.create.return_value = mock_response

    result = ai_engine.parse_transaction("tadi makan sate 50rb")
    
    assert result["amount"] == 50000
    assert result["category"] == "Makanan"
    assert result["is_transaction"] is True
    ai_engine.client.chat.completions.create.assert_called_once()

def test_ai_generate_insight(ai_engine):
    # Mock AI insight response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Wah kamu boros banget di makanan!"))
    ]
    ai_engine.client.chat.completions.create.return_value = mock_response

    insight = ai_engine.generate_smart_insight("Data: Pengeluaran makanan 1jt")
    
    assert "boros" in insight
    ai_engine.client.chat.completions.create.assert_called_once()

# --- SAVING GOALS TESTS ---

def test_saving_goals_crud(db_handler, db_session):
    # Setup user
    user = User(telegram_id=123, username="testuser")
    db_session.add(user)
    db_session.commit()

    # 1. Add Goal
    goal = db_handler.add_saving_goal(user.id, "Laptop", 10000000)
    assert goal.id is not None
    assert goal.name == "Laptop"
    assert goal.target_amount == 10000000
    assert goal.current_amount == 0

    # 2. Get Goals
    goals = db_handler.get_user_saving_goals(user.id)
    assert len(goals) == 1
    assert goals[0].name == "Laptop"

    # 3. Update Progress
    updated_goal = db_handler.update_saving_progress(user.id, goal.id, 500000)
    assert updated_goal.current_amount == 500000
    assert updated_goal.is_active == 1

    # 4. Complete Goal
    completed_goal = db_handler.update_saving_progress(user.id, goal.id, 9500000)
    assert completed_goal.current_amount == 10000000
    assert completed_goal.is_active == 0

# --- EXPORT TESTS ---

def test_export_csv(db_handler, db_session):
    # Setup user and transactions
    user = User(telegram_id=123, username="testuser")
    db_session.add(user)
    db_session.commit()

    tx1 = Transaction(user_id=user.id, amount=50000, category="Makanan", type="expense", description="kopi")
    tx2 = Transaction(user_id=user.id, amount=100000, category="Gaji", type="income", description="bonus")
    db_session.add_all([tx1, tx2])
    db_session.commit()

    # Export
    filepath = "test_export.csv"
    db_handler.export_transactions_to_csv(user.id, filepath)

    assert os.path.exists(filepath)
    
    # Verify content
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
        assert len(rows) == 3 # Header + 2 data rows
        assert rows[0] == ['ID', 'Tanggal', 'Kategori', 'Nominal', 'Tipe', 'Deskripsi']
        # Check if amounts are present (row 1 is newest tx due to order_by desc)
        amounts = [row[3] for row in rows[1:]]
        assert "100000.0" in amounts
        assert "50000.0" in amounts

    # Cleanup
    os.remove(filepath)
