from .models import get_session, User, Transaction, Budget, MonthlyIncome, SavingGoal, init_db
from datetime import datetime, timedelta
from sqlalchemy import extract, and_

class DBHandler:
    def __init__(self, session=None):
        if session:
            self.session = session
        else:
            init_db()
            self.session = get_session()
        
        # Only migrate if it's not a mock/test session (simple check)
        if not hasattr(self.session, 'is_mock'):
            self._migrate_db()
        # Principle 3.1: User-defined day cutoff (Default 04:00 AM)
        self.cutoff_hour = 4

    def _migrate_db(self):
        """
        Comprehensive migration to ensure all columns from models exist in the database.
        This is a preventive measure to handle cases where models change but database doesn't.
        """
        try:
            from sqlalchemy import text
            import logging
            
            # List of all required columns across all tables
            migrations = [
                # Users table
                ("users", "telegram_id", "BIGINT"), # Use BIGINT for safety with telegram IDs
                ("users", "username", "VARCHAR"),
                ("users", "pinned_message_id", "INTEGER"),
                ("users", "created_at", "TIMESTAMP"),
                
                # Transactions table
                ("transactions", "user_id", "INTEGER"),
                ("transactions", "amount", "FLOAT"),
                ("transactions", "category", "VARCHAR"),
                ("transactions", "description", "VARCHAR"),
                ("transactions", "type", "VARCHAR"),
                ("transactions", "date", "TIMESTAMP"),
                
                # Budgets table
                ("budgets", "user_id", "INTEGER"),
                ("budgets", "category", "VARCHAR"),
                ("budgets", "limit_amount", "FLOAT"),
                ("budgets", "current_usage", "FLOAT"),
                ("budgets", "month", "INTEGER"),
                ("budgets", "year", "INTEGER"),
                
                # Monthly Incomes table
                ("monthly_incomes", "user_id", "INTEGER"),
                ("monthly_incomes", "amount", "FLOAT"),
                ("monthly_incomes", "month", "INTEGER"),
                ("monthly_incomes", "year", "INTEGER"),
                ("monthly_incomes", "created_at", "TIMESTAMP"),

                # Saving Goals table
                ("saving_goals", "user_id", "INTEGER"),
                ("saving_goals", "name", "VARCHAR"),
                ("saving_goals", "target_amount", "FLOAT"),
                ("saving_goals", "current_amount", "FLOAT"),
                ("saving_goals", "target_date", "TIMESTAMP"),
                ("saving_goals", "is_active", "INTEGER"),
                ("saving_goals", "created_at", "TIMESTAMP"),
            ]
            
            for table, column, data_type in migrations:
                try:
                    # Using PostgreSQL syntax for IF NOT EXISTS column addition
                    # Note: ALTER TABLE ... ADD COLUMN IF NOT EXISTS is supported in PostgreSQL 9.6+
                    query = text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {data_type}")
                    self.session.execute(query)
                except Exception as col_e:
                    logging.warning(f"Could not migrate {table}.{column}: {col_e}")
                    self.session.rollback()
                    continue
            
            self.session.commit()
            logging.info("Database migration check completed successfully.")
            
        except Exception as e:
            self.session.rollback()
            logging.error(f"Global Migration Error: {e}")

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

    def get_user(self, telegram_id):
        return self.session.query(User).filter_by(telegram_id=telegram_id).first()

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

    def get_transactions_history(self, user_id, limit=50, category=None, start_date=None, end_date=None, min_amount=None):
        """
        Retrieves transaction history with advanced filtering.
        """
        query = self.session.query(Transaction).filter(Transaction.user_id == user_id)
        
        if category:
            query = query.filter(Transaction.category.ilike(f"%{category}%"))
        if start_date:
            query = query.filter(Transaction.date >= start_date)
        if end_date:
            query = query.filter(Transaction.date <= end_date)
        if min_amount:
            query = query.filter(Transaction.amount >= min_amount)
            
        return query.order_by(Transaction.date.desc()).limit(limit).all()

    def delete_transaction(self, user_id, transaction_id):
        """
        Deletes a specific transaction and reverses budget usage.
        """
        tx = self.session.query(Transaction).filter_by(id=transaction_id, user_id=user_id).first()
        if tx:
            if tx.type == 'expense':
                # Reverse budget usage
                self.update_budget_usage(user_id, tx.category, -tx.amount)
            
            self.session.delete(tx)
            self.session.commit()
            return True
        return False

    def undo_last_transaction(self, user_id):
        """
        Deletes the very last transaction made by the user.
        """
        last_tx = self.session.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.id.desc()).first()
        if last_tx:
            return self.delete_transaction(user_id, last_tx.id)
        return False

    def get_current_balance(self, user_id):
        """
        Calculates real-time balance: Total Income - Total Expense for the current month.
        """
        now = datetime.now()
        income = self.get_latest_income(user_id)
        total_income = income.amount if income else 0
        
        # Sum all expenses for this month
        transactions = self.get_monthly_report(user_id, now.month, now.year)
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        
        return total_income - total_expense

    def get_monthly_report(self, user_id, month, year):
        return self.session.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.date >= datetime(year, month, 1)
        ).all()

    # --- SAVING GOALS ---
    def add_saving_goal(self, user_id, name, target_amount, target_date=None):
        goal = SavingGoal(
            user_id=user_id,
            name=name,
            target_amount=target_amount,
            target_date=target_date
        )
        self.session.add(goal)
        self.session.commit()
        return goal

    def get_user_saving_goals(self, user_id, active_only=True):
        query = self.session.query(SavingGoal).filter_by(user_id=user_id)
        if active_only:
            query = query.filter_by(is_active=1)
        return query.all()

    def update_saving_progress(self, user_id, goal_id, amount):
        goal = self.session.query(SavingGoal).filter_by(id=goal_id, user_id=user_id).first()
        if goal:
            goal.current_amount += amount
            if goal.current_amount >= goal.target_amount:
                goal.is_active = 0 # Completed
            self.session.commit()
            return goal
        return None

    # --- EXPORT ---
    def export_transactions_to_csv(self, user_id, filepath):
        import pandas as pd
        txs = self.session.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.date.desc()).all()
        
        if not txs:
            return None

        df = pd.DataFrame([{
            'Tanggal': tx.date.strftime('%Y-%m-%d %H:%M'),
            'Tipe': 'Pengeluaran' if tx.type == 'expense' else 'Pemasukan',
            'Kategori': tx.category,
            'Nominal': f"Rp{tx.amount:,.0f}",
            'Catatan': tx.description or '-'
        } for tx in txs])
        
        df.to_csv(filepath, index=False)
        return filepath

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
