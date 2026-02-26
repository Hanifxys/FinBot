from .models import get_supabase, Tables
from datetime import datetime, timedelta
import logging
from modules.crypto import EncryptionManager

class DBHandler:
    def __init__(self, session=None):
        # We use session=None for backward compatibility, but we use Supabase client now
        self.supabase = get_supabase()
        # Principle 3.1: User-defined day cutoff (Default 04:00 AM)
        self.cutoff_hour = 4
        # Optional encryption
        self.crypto = EncryptionManager()

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
        response = self.supabase.table(Tables.USERS).select("*").eq("telegram_id", telegram_id).execute()
        if response.data:
            # Wrap in a simple object-like structure for compatibility
            return type('User', (object,), response.data[0])
        return None

    def get_all_users(self):
        response = self.supabase.table(Tables.USERS).select("*").execute()
        return [type('User', (object,), item) for item in response.data]

    def get_daily_transactions(self, user_id, date_obj):
        start_time = datetime.combine(date_obj, datetime.min.time()).isoformat()
        end_time = datetime.combine(date_obj, datetime.max.time()).isoformat()
        
        response = self.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_id)\
            .gte("date", start_time).lte("date", end_time).execute()
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def get_or_create_user(self, telegram_id, username):
        user = self.get_user(telegram_id)
        if not user:
            data = {"telegram_id": telegram_id, "username": username}
            response = self.supabase.table(Tables.USERS).insert(data).execute()
            return type('User', (object,), response.data[0])
        elif user.username != username:
            data = {"username": username}
            response = self.supabase.table(Tables.USERS).update(data).eq("telegram_id", telegram_id).execute()
            return type('User', (object,), response.data[0])
        return user

    def add_transaction(self, user_id, amount, category, description, trans_type='expense', trans_date=None):
        if trans_date is None:
            now = datetime.now()
            trans_date = now.isoformat()
        elif isinstance(trans_date, datetime):
            trans_date = trans_date.isoformat()

        data = {
            "user_id": user_id,
            "amount": float(amount),
            "category": category,
            "description": self.crypto.encrypt(description) if description else None,
            "type": trans_type,
            "date": trans_date
        }
        
        response = self.supabase.table(Tables.TRANSACTIONS).insert(data).execute()
        
        # Real-time Broadcast via WebSocket (Secure)
        try:
            from core import ws_server
            import asyncio
            asyncio.run_coroutine_threadsafe(
                ws_server.broadcast_to_user(
                    user_id=user_id,
                    message={
                        "event": "new_transaction",
                        "data": data
                    }
                ),
                ws_server.loop
            )
        except Exception as e:
            logging.error(f"WS Broadcast Failed: {e}")

        # Update budget if it's an expense
        if trans_type == 'expense':
            self.update_budget_usage(user_id, category, amount)
            
        return type('Transaction', (object,), response.data[0])

    def get_sliding_window_transactions(self, user_id, days=7):
        end_date = datetime.now()
        start_date = (end_date - timedelta(days=days)).isoformat()
        end_date_iso = end_date.isoformat()
        
        response = self.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_id)\
            .gte("date", start_date).lte("date", end_date_iso).execute()
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def set_budget(self, user_id, category, limit_amount):
        now = datetime.now()
        existing = self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year).execute()
        
        if existing.data:
            data = {"limit_amount": float(limit_amount)}
            response = self.supabase.table(Tables.BUDGETS).update(data).eq("id", existing.data[0]['id']).execute()
        else:
            data = {
                "user_id": user_id,
                "category": category,
                "limit_amount": float(limit_amount),
                "month": now.month,
                "year": now.year,
                "current_usage": 0.0
            }
            response = self.supabase.table(Tables.BUDGETS).insert(data).execute()
        
        return type('Budget', (object,), response.data[0])

    def update_budget_usage(self, user_id, category, amount):
        now = datetime.now()
        existing = self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year).execute()
        
        if existing.data:
            new_usage = existing.data[0]['current_usage'] + float(amount)
            response = self.supabase.table(Tables.BUDGETS).update({"current_usage": new_usage})\
                .eq("id", existing.data[0]['id']).execute()
            return type('Budget', (object,), response.data[0])
        return None

    def get_budget(self, user_id, category):
        now = datetime.now()
        response = self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year).execute()
        if response.data:
            return type('Budget', (object,), response.data[0])
        return None

    def get_user_budgets(self, user_id):
        now = datetime.now()
        response = self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("month", now.month).eq("year", now.year).execute()
        return [type('Budget', (object,), item) for item in response.data]

    def get_transactions_history(self, user_id, limit=50, category=None, start_date=None, end_date=None, min_amount=None):
        query = self.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_id)
        
        if category:
            query = query.ilike("category", f"%{category}%")
        if start_date:
            query = query.gte("date", start_date.isoformat() if isinstance(start_date, datetime) else start_date)
        if end_date:
            query = query.lte("date", end_date.isoformat() if isinstance(end_date, datetime) else end_date)
        if min_amount:
            query = query.gte("amount", float(min_amount))
            
        response = query.order("date", desc=True).limit(limit).execute()
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def delete_transaction(self, user_id, transaction_id):
        response = self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("id", transaction_id).eq("user_id", user_id).execute()
        if response.data:
            tx = response.data[0]
            if tx['type'] == 'expense':
                self.update_budget_usage(user_id, tx['category'], -tx['amount'])
            
            self.supabase.table(Tables.TRANSACTIONS).delete().eq("id", transaction_id).execute()
            return True
        return False

    def undo_last_transaction(self, user_id):
        response = self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).order("id", desc=True).limit(1).execute()
        if response.data:
            return self.delete_transaction(user_id, response.data[0]['id'])
        return False

    def get_current_balance(self, user_id):
        now = datetime.now()
        income = self.get_latest_income(user_id)
        total_income = income.amount if income else 0
        
        transactions = self.get_monthly_report(user_id, now.month, now.year)
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        
        return total_income - total_expense

    def get_monthly_report(self, user_id, month, year):
        start_date = datetime(year, month, 1).isoformat()
        response = self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).gte("date", start_date).execute()
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    # --- SAVING GOALS ---
    def add_saving_goal(self, user_id, name, target_amount, target_date=None):
        data = {
            "user_id": user_id,
            "name": name,
            "target_amount": float(target_amount),
            "target_date": target_date.isoformat() if isinstance(target_date, datetime) else target_date,
            "is_active": 1,
            "current_amount": 0.0
        }
        response = self.supabase.table(Tables.SAVING_GOALS).insert(data).execute()
        return type('SavingGoal', (object,), response.data[0])

    def get_user_saving_goals(self, user_id, active_only=True):
        query = self.supabase.table(Tables.SAVING_GOALS).select("*").eq("user_id", user_id)
        if active_only:
            query = query.eq("is_active", 1)
        response = query.execute()
        return [type('SavingGoal', (object,), item) for item in response.data]

    def update_saving_progress(self, user_id, goal_id, amount):
        response = self.supabase.table(Tables.SAVING_GOALS).select("*")\
            .eq("id", goal_id).eq("user_id", user_id).execute()
        if response.data:
            goal = response.data[0]
            new_amount = goal['current_amount'] + float(amount)
            is_active = 1
            if new_amount >= goal['target_amount']:
                is_active = 0
            
            update_data = {"current_amount": new_amount, "is_active": is_active}
            update_response = self.supabase.table(Tables.SAVING_GOALS).update(update_data).eq("id", goal_id).execute()
            return type('SavingGoal', (object,), update_response.data[0])
        return None

    # --- EXPORT ---
    def export_transactions_to_csv(self, user_id, filepath):
        import pandas as pd
        response = self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).order("date", desc=True).execute()
        
        if not response.data:
            return None

        # Helper to parse ISO strings back to datetime objects
        def parse_date(date_str):
            try:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                return date_str

        df = pd.DataFrame([{
            'Tanggal': parse_date(tx['date']).strftime('%Y-%m-%d %H:%M'),
            'Tipe': 'Pengeluaran' if tx['type'] == 'expense' else 'Pemasukan',
            'Kategori': tx['category'],
            'Nominal': f"Rp{tx['amount']:,.0f}",
            'Catatan': (self.crypto.decrypt(tx['description']) if tx.get('description') else '-') 
        } for tx in response.data])
        
        df.to_csv(filepath, index=False)
        return filepath

    def add_monthly_income(self, user_id, amount):
        now = datetime.now()
        existing = self.supabase.table(Tables.MONTHLY_INCOMES).select("*")\
            .eq("user_id", user_id).eq("month", now.month).eq("year", now.year).execute()
        
        if existing.data:
            response = self.supabase.table(Tables.MONTHLY_INCOMES).update({"amount": float(amount)})\
                .eq("id", existing.data[0]['id']).execute()
        else:
            data = {
                "user_id": user_id,
                "amount": float(amount),
                "month": now.month,
                "year": now.year
            }
            response = self.supabase.table(Tables.MONTHLY_INCOMES).insert(data).execute()
        
        return type('MonthlyIncome', (object,), response.data[0])

    def get_latest_income(self, user_id):
        response = self.supabase.table(Tables.MONTHLY_INCOMES).select("*")\
            .eq("user_id", user_id).order("id", desc=True).limit(1).execute()
        if response.data:
            return type('MonthlyIncome', (object,), response.data[0])
        return None

    # --- Yearly Report ---
    def get_yearly_report(self, user_id, year):
        start_date = datetime(year, 1, 1).isoformat()
        end_date = datetime(year + 1, 1, 1).isoformat()
        response = self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).gte("date", start_date).lt("date", end_date).execute()
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    # --- Budget thresholds ---
    def set_budget_threshold(self, user_id, category, warn_threshold: float, limit_threshold: float):
        now = datetime.now()
        existing = self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year).execute()
        data = {"warn_threshold": float(warn_threshold), "limit_threshold": float(limit_threshold)}
        if existing.data:
            self.supabase.table(Tables.BUDGETS).update(data).eq("id", existing.data[0]['id']).execute()
        else:
            base = {
                "user_id": user_id,
                "category": category,
                "limit_amount": 0.0,
                "month": now.month,
                "year": now.year,
                "current_usage": 0.0
            }
            base.update(data)
            self.supabase.table(Tables.BUDGETS).insert(base).execute()
        return True

    # --- Internal helpers ---
    def _decrypt_tx(self, item: dict) -> dict:
        try:
            if item.get("description"):
                item["description"] = self.crypto.decrypt(item["description"])
        except Exception:
            pass
        return item
