import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Transaction, Budget, MonthlyIncome, SavingGoal
from database.db_handler import DBHandler
from datetime import datetime, timezone

@pytest.fixture
def db_session():
    # Use in-memory SQLite for testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Add a flag to indicate this is a test session to skip migrations
    session.is_mock = True
    yield session
    session.close()

@pytest.fixture
def db_handler(db_session):
    return DBHandler(session=db_session)

def test_get_or_create_user(db_handler):
    # Test creating a new user
    user = db_handler.get_or_create_user(12345, "testuser")
    assert user.telegram_id == 12345
    assert user.username == "testuser"
    
    # Test getting existing user
    user2 = db_handler.get_or_create_user(12345, "updateduser")
    assert user2.id == user.id
    assert user2.username == "updateduser" # Should update username

def test_add_transaction(db_handler):
    user = db_handler.get_or_create_user(12345, "testuser")
    tx = db_handler.add_transaction(user.id, 50000, "Makanan", "Makan siang", "expense")
    
    assert tx.id is not None
    assert tx.amount == 50000
    assert tx.category == "Makanan"
    assert tx.type == "expense"
    
    # Verify in DB
    saved_tx = db_handler.session.query(Transaction).filter_by(id=tx.id).first()
    assert saved_tx is not None
    assert saved_tx.amount == 50000

def test_get_monthly_report(db_handler):
    user = db_handler.get_or_create_user(12345, "testuser")
    now = datetime.now()
    
    db_handler.add_transaction(user.id, 50000, "Makanan", "Makan siang", "expense")
    db_handler.add_transaction(user.id, 20000, "Transport", "Grab", "expense")
    db_handler.add_transaction(user.id, 1000000, "Gaji", "Bonus", "income")
    
    report = db_handler.get_monthly_report(user.id, now.month, now.year)
    assert len(report) == 3
    
    # Test filtering by type
    expenses = [t for t in report if t.type == 'expense']
    assert len(expenses) == 2
    assert sum(t.amount for t in expenses) == 70000

def test_budget_management(db_handler):
    user = db_handler.get_or_create_user(12345, "testuser")
    now = datetime.now()
    
    # Set budget
    budget = db_handler.set_budget(user.id, "Makanan", 1000000)
    assert budget.limit_amount == 1000000
    
    # Get budget
    saved_budget = db_handler.get_budget(user.id, "Makanan")
    assert saved_budget.limit_amount == 1000000
    
def test_undo_transaction(db_handler):
    user = db_handler.get_or_create_user(12345, "testuser")
    tx = db_handler.add_transaction(user.id, 50000, "Makanan", "Makan siang", "expense")
    
    success = db_handler.undo_last_transaction(user.id)
    assert success is True
    
    # Verify it's gone
    saved_tx = db_handler.session.query(Transaction).filter_by(id=tx.id).first()
    assert saved_tx is None

def test_saving_goals(db_handler):
    user = db_handler.get_or_create_user(12345, "testuser")
    
    # Add goal
    goal = db_handler.add_saving_goal(user.id, "Laptop", 10000000)
    assert goal.name == "Laptop"
    assert goal.target_amount == 10000000
    
    # Update progress
    updated_goal = db_handler.update_saving_progress(user.id, goal.id, 500000)
    assert updated_goal.current_amount == 500000
    
    # Get goals
    goals = db_handler.get_user_saving_goals(user.id)
    assert len(goals) == 1
    assert goals[0].name == "Laptop"
