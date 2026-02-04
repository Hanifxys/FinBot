from .models import SessionLocal, User, Transaction, Budget, MonthlyIncome, init_db
from datetime import datetime, timedelta
from sqlalchemy import extract, and_

class DBHandler:
    def __init__(self):
        init_db()
        self.session = SessionLocal()
        self._migrate_db()
        # Principle 3.1: User-defined day cutoff (Default 04:00 AM)
        self.cutoff_hour = 4

    def _migrate_db(self):
        """
        Simple migration to add missing columns.
        init_db() only creates tables, it doesn't add new columns to existing tables.
        """
        try:
            from sqlalchemy import text
            # Check if pinned_message_id exists in users table
            self.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pinned_message_id INTEGER"))
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            print(f"Migration Error: {e}")

    def get_effective_date(self, dt=None):
        """
        Returns the effective accounting date based on the cutoff hour.
        Transactions before 04:00 AM are counted as the previous day.
        """
        if dt is None:
            dt = datetime.now()
        
        if dt.hour < self.cutoff_hour:
            return (dt - timedelta(days=1)).date()
        return dt.date()

    def get_all_users(self):
        return self.session.query(User).all()

    def get_daily_transactions(self, user_id, date_obj):
        # Using effective date for filtering
        return self.session.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.date >= datetime.combine(date_obj, datetime.min.time()),
            Transaction.date <= datetime.combine(date_obj, datetime.max.time())
        ).all()

    def get_or_create_user(self, telegram_id, username):
        user = self.session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            user = User(telegram_id=telegram_id, username=username)
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
        return user

    def add_transaction(self, user_id, amount, category, description, trans_type='expense', trans_date=None):
        if trans_date is None:
            # Principle 3.1: Apply cutoff logic
            now = datetime.now()
            eff_date = self.get_effective_date(now)
            # Store with current time but we use eff_date for reporting
            trans_date = now

        transaction = Transaction(
            user_id=user_id,
            amount=amount,
            category=category,
            description=description,
            type=trans_type,
            date=trans_date
        )
        self.session.add(transaction)
        
        # Update budget if it's an expense
        if trans_type == 'expense':
            self.update_budget_usage(user_id, category, amount)
            
        self.session.commit()
        return transaction

    def get_sliding_window_transactions(self, user_id, days=7):
        """
        Principle 3.2: Sliding window summary (Last N days)
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        return self.session.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date
        ).all()

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
