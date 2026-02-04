from .models import SessionLocal, User, Transaction, Budget, MonthlyIncome, init_db
from datetime import datetime
from sqlalchemy import extract

class DBHandler:
    def __init__(self):
        init_db()
        self.session = SessionLocal()

    def get_all_users(self):
        return self.session.query(User).all()

    def get_daily_transactions(self, user_id, day, month, year):
        return self.session.query(Transaction).filter(
            Transaction.user_id == user_id,
            extract('day', Transaction.date) == day,
            extract('month', Transaction.date) == month,
            extract('year', Transaction.date) == year
        ).all()

    def get_or_create_user(self, telegram_id, username):
        user = self.session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            user = User(telegram_id=telegram_id, username=username)
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
        return user

    def add_transaction(self, user_id, amount, category, description, trans_type='expense'):
        transaction = Transaction(
            user_id=user_id,
            amount=amount,
            category=category,
            description=description,
            type=trans_type
        )
        self.session.add(transaction)
        
        # Update budget if it's an expense
        if trans_type == 'expense':
            self.update_budget_usage(user_id, category, amount)
            
        self.session.commit()
        return transaction

    def set_budget(self, user_id, category, limit_amount):
        now = datetime.now()
        budget = self.session.query(Budget).filter_by(
            user_id=user_id, 
            category=category, 
            month=now.month, 
            year=now.year
        ).first()
        
        if budget:
            budget.limit_amount = limit_amount
        else:
            budget = Budget(
                user_id=user_id,
                category=category,
                limit_amount=limit_amount,
                month=now.month,
                year=now.year
            )
            self.session.add(budget)
        
        self.session.commit()
        return budget

    def update_budget_usage(self, user_id, category, amount):
        now = datetime.now()
        budget = self.session.query(Budget).filter_by(
            user_id=user_id, 
            category=category, 
            month=now.month, 
            year=now.year
        ).first()
        
        if budget:
            budget.current_usage += amount
            self.session.commit()
            return budget
        return None

    def get_user_budgets(self, user_id):
        now = datetime.now()
        return self.session.query(Budget).filter_by(
            user_id=user_id, 
            month=now.month, 
            year=now.year
        ).all()

    def get_monthly_report(self, user_id, month, year):
        return self.session.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.date >= datetime(year, month, 1)
        ).all()

    def add_monthly_income(self, user_id, amount):
        now = datetime.now()
        income = self.session.query(MonthlyIncome).filter_by(
            user_id=user_id,
            month=now.month,
            year=now.year
        ).first()
        
        if income:
            income.amount = amount
        else:
            income = MonthlyIncome(
                user_id=user_id,
                amount=amount,
                month=now.month,
                year=now.year
            )
            self.session.add(income)
        
        self.session.commit()
        return income

    def get_latest_income(self, user_id):
        return self.session.query(MonthlyIncome).filter_by(user_id=user_id).order_by(MonthlyIncome.id.desc()).first()
