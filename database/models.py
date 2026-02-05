from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, create_engine, extract
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from datetime import datetime, timezone
import sys
import os

# Add project root to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_URL

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    pinned_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
class MonthlyIncome(Base):
    __tablename__ = 'monthly_incomes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Float, nullable=False)
    month = Column(Integer)
    year = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Float, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String)
    type = Column(String) # 'expense' or 'income'
    date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    user = relationship("User", back_populates="transactions")

User.transactions = relationship("Transaction", order_by=Transaction.id, back_populates="user")

class Budget(Base):
    __tablename__ = 'budgets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    category = Column(String, nullable=False)
    limit_amount = Column(Float, nullable=False)
    current_usage = Column(Float, default=0.0)
    month = Column(Integer) # 1-12
    year = Column(Integer)

class SavingGoal(Base):
    __tablename__ = 'saving_goals'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0)
    target_date = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=1) # 1 for active, 0 for completed/cancelled
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Create engine and SessionLocal
# Allow overriding for tests
engine = None
SessionLocal = None

def get_engine():
    global engine
    if engine is None:
        engine = create_engine(DATABASE_URL)
    return engine

def get_session():
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return SessionLocal()

def init_db(target_engine=None):
    if target_engine is None:
        target_engine = get_engine()
    Base.metadata.create_all(bind=target_engine)
