import time
from .models import get_supabase, Tables
from datetime import datetime, timedelta
import logging
from modules.crypto import EncryptionManager

# Cache TTL (seconds)
CACHE_TTL_USER = 300
CACHE_TTL_BUDGET = 60

# Roles
ROLE_SUPERADMIN = "superadmin"
ROLE_MODERATOR = "moderator"
ROLE_FINANCE = "finance"
ROLE_SUPPORT = "support"
ROLE_USER = "user"

# Permissions Matrix
PERMISSIONS = {
    ROLE_SUPERADMIN: ["*"],
    ROLE_MODERATOR: ["view_users", "block_user", "broadcast", "view_logs"],
    ROLE_FINANCE: ["view_transactions", "export_data", "view_reports"],
    ROLE_SUPPORT: ["view_users", "message_user", "view_activity"],
    ROLE_USER: []
}

# Superadmin Configuration
SUPERADMIN_ID = 1512347775 # Muhamad Hanif

class DBHandler:
    def __init__(self, session=None):
        self.supabase = get_supabase()
        self.cutoff_hour = 4
        self.crypto = EncryptionManager()
        self._user_cache = {}
        self._budget_cache = {}

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

    def _safe_execute(self, query_builder):
        """Execute a Supabase query with retry logic for connection errors."""
        max_retries = 5 # Increased retries
        for attempt in range(max_retries):
            try:
                return query_builder.execute()
            except Exception as e:
                err_msg = str(e)
                # Check for common connection/protocol errors
                # RemoteProtocolError is often caused by HTTP/2 issues with Supabase/Koyeb
                is_protocol_error = any(kw in err_msg for kw in ["RemoteProtocolError", "ConnectionTerminated", "PROTOCOL_ERROR"])
                
                if is_protocol_error and attempt < max_retries - 1:
                    logging.warning(f"Supabase protocol error detected ({err_msg}), retrying ({attempt+1}/{max_retries})...")
                    time.sleep(1.0 * (attempt + 1)) # More aggressive backoff
                    continue
                
                # Also log non-protocol errors for debugging
                logging.error(f"Supabase Execution Error: {err_msg}")
                raise e

    def get_user(self, telegram_id):
        now = time.time()
        cached = self._user_cache.get(telegram_id)
        if cached and (now - cached['ts'] < CACHE_TTL_USER):
            return cached['data']

        response = self._safe_execute(self.supabase.table(Tables.USERS).select("*").eq("telegram_id", telegram_id))
        if response.data:
            user = type('User', (object,), response.data[0])
            self._user_cache[telegram_id] = {'data': user, 'ts': now}
            return user
        return None

    def get_all_users(self):
        # Heavy query, consider pagination for scale
        response = self._safe_execute(self.supabase.table(Tables.USERS).select("*"))
        return [type('User', (object,), item) for item in response.data]

    def get_daily_transactions(self, user_id, date_obj):
        start_time = datetime.combine(date_obj, datetime.min.time()).isoformat()
        end_time = datetime.combine(date_obj, datetime.max.time()).isoformat()
        
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_id)\
            .gte("date", start_time).lte("date", end_time))
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def get_or_create_user(self, telegram_id, username):
        user = self.get_user(telegram_id)
        if not user:
            data = {"telegram_id": telegram_id, "username": username}
            response = self._safe_execute(self.supabase.table(Tables.USERS).insert(data))
            new_user = type('User', (object,), response.data[0])
            self._user_cache[telegram_id] = {'data': new_user, 'ts': time.time()}
            return new_user
        elif getattr(user, 'username', '') != username:
            data = {"username": username}
            self._safe_execute(self.supabase.table(Tables.USERS).update(data).eq("telegram_id", telegram_id))
            # Update cache
            user.username = username
            self._user_cache[telegram_id] = {'data': user, 'ts': time.time()}
            return user
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
        
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).insert(data))
        
        # Balance Snapshot Logic (Daily)
        try:
            self._update_balance_snapshot(user_id, amount, trans_type)
        except Exception as e:
            logging.error(f"Snapshot update failed: {e}")

        # Real-time Broadcast via WebSocket (Secure)
        try:
            from core import ws_server
            import asyncio
            if ws_server.loop and ws_server.loop.is_running():
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

    def _update_balance_snapshot(self, user_id, amount, trans_type):
        """Optimized Snapshot Engine"""
        now = datetime.now()
        today = now.date().isoformat()
        
        # Use Redis or Memory cache for fast snapshot
        # For now, DB based
        table = "daily_balance_snapshots" # Hypothetical table
        # Since we don't have schema migration tool here, we skip actual DB insert
        # But this is where the logic goes:
        # Check if snapshot exists for today -> update
        # Else -> create new based on yesterday + tx
        pass

    def get_sliding_window_transactions(self, user_id, days=7):
        end_date = datetime.now()
        start_date = (end_date - timedelta(days=days)).isoformat()
        end_date_iso = end_date.isoformat()
        
        # Add index on (user_id, date) in Supabase for speed
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_id)\
            .gte("date", start_date).lte("date", end_date_iso))
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def set_budget(self, user_id, category, limit_amount):
        now = datetime.now()
        existing = self._safe_execute(self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year))
        
        if existing.data:
            data = {"limit_amount": float(limit_amount)}
            response = self._safe_execute(self.supabase.table(Tables.BUDGETS).update(data).eq("id", existing.data[0]['id']))
        else:
            data = {
                "user_id": user_id,
                "category": category,
                "limit_amount": float(limit_amount),
                "month": now.month,
                "year": now.year,
                "current_usage": 0.0
            }
            response = self._safe_execute(self.supabase.table(Tables.BUDGETS).insert(data))
        
        # Invalidate cache
        cache_key = f"{user_id}:{category}"
        if cache_key in self._budget_cache:
            del self._budget_cache[cache_key]
            
        return type('Budget', (object,), response.data[0])

    def update_budget_usage(self, user_id, category, amount):
        now = datetime.now()
        # Check cache first? No, usage needs atomic update or consistency.
        # But we can read from cache if we trust it.
        
        existing = self._safe_execute(self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year))
        
        if existing.data:
            new_usage = existing.data[0]['current_usage'] + float(amount)
            response = self._safe_execute(self.supabase.table(Tables.BUDGETS).update({"current_usage": new_usage})\
                .eq("id", existing.data[0]['id']))
            return type('Budget', (object,), response.data[0])
        return None

    def get_budget(self, user_id, category):
        now = datetime.now()
        response = self._safe_execute(self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year))
        if response.data:
            return type('Budget', (object,), response.data[0])
        return None

    def get_user_budgets(self, user_id):
        now = datetime.now()
        response = self._safe_execute(self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("month", now.month).eq("year", now.year))
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
            
        response = self._safe_execute(query.order("date", desc=True).limit(limit))
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    def delete_transaction(self, user_id, transaction_id):
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("id", transaction_id).eq("user_id", user_id))
        if response.data:
            tx = response.data[0]
            if tx['type'] == 'expense':
                self.update_budget_usage(user_id, tx['category'], -tx['amount'])
            
            self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).delete().eq("id", transaction_id))
            return True
        return False

    def undo_last_transaction(self, user_id):
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).order("id", desc=True).limit(1))
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
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).gte("date", start_date))
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    # --- SAVING GOALS ---
    def add_saving_goal(self, user_id, name, target_amount, target_date=None):
        data = {
            "user_id": user_id,
            "name": name,
            "target_amount": float(target_amount),
            "target_date": target_date.isoformat() if isinstance(target_date, datetime) else target_date,
            "current_amount": 0.0,
            "is_active": True
        }
        response = self._safe_execute(self.supabase.table(Tables.SAVING_GOALS).insert(data))
        return type('SavingGoal', (object,), response.data[0])

    def get_monthly_wrapper(self, user_id, month, year):
        """Fetch the Spotify-style monthly wrapper if it exists."""
        response = self._safe_execute(self.supabase.table(Tables.MONTHLY_WRAPPERS).select("*")\
            .eq("user_id", user_id).eq("month", month).eq("year", year))
        if response.data:
            return response.data[0]
        return None

    def save_monthly_wrapper(self, user_id, month, year, content, status="pending"):
        """Save/Update a monthly wrapper record."""
        data = {
            "user_id": user_id,
            "month": month,
            "year": year,
            "content": content,
            "status": status,
            "updated_at": datetime.now().isoformat()
        }
        
        # Check if exists
        existing = self.get_monthly_wrapper(user_id, month, year)
        if existing:
            response = self._safe_execute(self.supabase.table(Tables.MONTHLY_WRAPPERS).update(data).eq("id", existing['id']))
        else:
            data["created_at"] = datetime.now().isoformat()
            response = self._safe_execute(self.supabase.table(Tables.MONTHLY_WRAPPERS).insert(data))
        return response.data[0]

    def get_wrapper_stats(self, month, year):
        """Aggregate stats for the admin dashboard."""
        response = self._safe_execute(self.supabase.table(Tables.MONTHLY_WRAPPERS).select("status")\
            .eq("month", month).eq("year", year))
        
        stats = {"total": len(response.data), "sent": 0, "failed": 0, "pending": 0}
        for r in response.data:
            stats[r['status']] = stats.get(r['status'], 0) + 1
        return stats

    def get_user_saving_goals(self, user_id, active_only=True):
        query = self.supabase.table(Tables.SAVING_GOALS).select("*").eq("user_id", user_id)
        if active_only:
            query = query.eq("is_active", 1)
        response = self._safe_execute(query)
        return [type('SavingGoal', (object,), item) for item in response.data]

    def update_saving_progress(self, user_id, goal_id, amount):
        response = self._safe_execute(self.supabase.table(Tables.SAVING_GOALS).select("*")\
            .eq("id", goal_id).eq("user_id", user_id))
        if response.data:
            goal = response.data[0]
            new_amount = goal['current_amount'] + float(amount)
            is_active = 1
            if new_amount >= goal['target_amount']:
                is_active = 0
            
            update_data = {"current_amount": new_amount, "is_active": is_active}
            update_response = self._safe_execute(self.supabase.table(Tables.SAVING_GOALS).update(update_data).eq("id", goal_id))
            return type('SavingGoal', (object,), update_response.data[0])
        return None

    # --- EXPORT ---
    def export_transactions_to_csv(self, user_id, filepath):
        import pandas as pd
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).order("date", desc=True))
        
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
        existing = self._safe_execute(self.supabase.table(Tables.MONTHLY_INCOMES).select("*")\
            .eq("user_id", user_id).eq("month", now.month).eq("year", now.year))
        
        if existing.data:
            response = self._safe_execute(self.supabase.table(Tables.MONTHLY_INCOMES).update({"amount": float(amount)})\
                .eq("id", existing.data[0]['id']))
        else:
            data = {
                "user_id": user_id,
                "amount": float(amount),
                "month": now.month,
                "year": now.year
            }
            response = self._safe_execute(self.supabase.table(Tables.MONTHLY_INCOMES).insert(data))
        
        return type('MonthlyIncome', (object,), response.data[0])

    def get_latest_income(self, user_id):
        response = self._safe_execute(self.supabase.table(Tables.MONTHLY_INCOMES).select("*")\
            .eq("user_id", user_id).order("id", desc=True).limit(1))
        if response.data:
            return type('MonthlyIncome', (object,), response.data[0])
        return None

    # --- Yearly Report ---
    def get_yearly_report(self, user_id, year):
        start_date = datetime(year, 1, 1).isoformat()
        end_date = datetime(year + 1, 1, 1).isoformat()
        response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("*")\
            .eq("user_id", user_id).gte("date", start_date).lt("date", end_date))
        return [type('Transaction', (object,), self._decrypt_tx(item)) for item in response.data]

    # --- Budget thresholds ---
    def set_budget_threshold(self, user_id, category, warn_threshold: float, limit_threshold: float):
        now = datetime.now()
        existing = self._safe_execute(self.supabase.table(Tables.BUDGETS).select("*")\
            .eq("user_id", user_id).eq("category", category)\
            .eq("month", now.month).eq("year", now.year))
        data = {"warn_threshold": float(warn_threshold), "limit_threshold": float(limit_threshold)}
        if existing.data:
            self._safe_execute(self.supabase.table(Tables.BUDGETS).update(data).eq("id", existing.data[0]['id']))
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
            self._safe_execute(self.supabase.table(Tables.BUDGETS).insert(base))
        return True

    def get_last_transaction_date(self, user_id):
        """
        Retrieves the date of the most recent transaction for a user.
        Returns datetime object or None if no transactions found.
        """
        try:
            response = self._safe_execute(self.supabase.table(Tables.TRANSACTIONS).select("date")\
                .eq("user_id", user_id).order("date", desc=True).limit(1))
            
            if response.data:
                date_val = response.data[0]['date']
                if isinstance(date_val, str):
                    return datetime.fromisoformat(date_val.replace("Z", "+00:00"))
                return date_val
            return None
        except Exception as e:
            logging.error(f"Error fetching last transaction date: {e}")
            return None

    # --- Internal helpers ---
    def _decrypt_tx(self, item: dict) -> dict:
        try:
            if item.get("description"):
                item["description"] = self.crypto.decrypt(item["description"])
        except Exception:
            pass
        try:
            date_val = item.get("date")
            if isinstance(date_val, str) and date_val:
                item["date"] = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except Exception:
            pass
        return item

    # --- ADMIN METHODS ---
    def update_user_role(self, telegram_id, role):
        data = {"role": role}
        self._safe_execute(self.supabase.table(Tables.USERS).update(data).eq("telegram_id", telegram_id))
        # Invalidate cache
        if telegram_id in self._user_cache:
            del self._user_cache[telegram_id]
        return True

    def update_user_status(self, telegram_id, is_active):
        data = {"is_active": is_active}
        self._safe_execute(self.supabase.table(Tables.USERS).update(data).eq("telegram_id", telegram_id))
        # Invalidate cache
        if telegram_id in self._user_cache:
            del self._user_cache[telegram_id]
        return True

    def has_permission(self, telegram_id, permission):
        """Check if user has a specific permission based on their role."""
        if telegram_id == SUPERADMIN_ID:
            return True
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        role = getattr(user, 'role', ROLE_USER)
        perms = PERMISSIONS.get(role, [])
        return "*" in perms or permission in perms

    def log_admin_action(self, admin_id, target_id, action, reason=None, action_type="modification", old_value=None, new_value=None, ip_address=None):
        """Enhanced admin action logging for serious audit trail."""
        data = {
            "admin_id": admin_id,
            "target_id": target_id,
            "action": action,
            "action_type": action_type,
            "old_value": str(old_value) if old_value is not None else None,
            "new_value": str(new_value) if new_value is not None else None,
            "reason": reason,
            "ip_address": ip_address,
            "timestamp": datetime.now().isoformat()
        }
        try:
            self._safe_execute(self.supabase.table(Tables.ADMIN_LOGS).insert(data))
        except Exception as e:
            logging.error(f"Failed to log admin action: {e}")
        return True

    def add_system_log(self, level, message, metadata=None):
        """Generic system logging for OOM, errors, and critical events."""
        data = {
            "admin_id": 0,
            "target_id": 0,
            "action": level,
            "action_type": "system",
            "reason": message[:255] if message else None,
            "new_value": str(metadata or message) if metadata or (message and len(message) > 255) else None,
            "timestamp": datetime.now().isoformat()
        }
        try:
            self._safe_execute(self.supabase.table(Tables.ADMIN_LOGS).insert(data))
        except Exception as e:
            logging.error(f"Failed to add system log: {e}")
        return True

    def get_admin_logs(self, limit=100):
        """Fetch audit logs, sorted by most recent."""
        try:
            response = self._safe_execute(self.supabase.table(Tables.ADMIN_LOGS).select("*")\
                .order("timestamp", desc=True).limit(limit))
            return response.data
        except Exception as e:
            logging.error(f"Failed to fetch admin logs: {e}")
            return []

    def get_flagged_transactions(self, limit=50):
        try:
            response = self._safe_execute(self.supabase.table(Tables.FLAGGED_TRANSACTIONS).select("*, transactions(*)")\
                .order("created_at", desc=True).limit(limit))
            return response.data
        except Exception as e:
            logging.error(f"Failed to fetch flagged transactions: {e}")
            return []

    def get_suspicious_users(self, limit=20):
        """Identifies users with high activity or anomalies."""
        try:
            # For now, let's identify users with > 20 transactions today as suspicious
            today = self.get_effective_date()
            start_time = datetime.combine(today, datetime.min.time()).isoformat()
            
            # This is a bit complex for a single Supabase query without RPC, 
            # so we'll do a simple heuristic or return an empty list until RPC is ready.
            # Real version would use a view or RPC.
            return [] 
        except Exception as e:
            logging.error(f"Failed to fetch suspicious users: {e}")
            return []

    def get_dispute_tickets(self, limit=50):
        try:
            response = self._safe_execute(self.supabase.table(Tables.DISPUTES).select("*")\
                .order("created_at", desc=True).limit(limit))
            return response.data
        except Exception as e:
            logging.error(f"Failed to fetch disputes: {e}")
            return []

    def get_moderation_settings(self):
        try:
            response = self._safe_execute(self.supabase.table(Tables.MODERATION_SETTINGS).select("*"))
            if response.data:
                return response.data[0]
            return {
                "auto_flag_high_amount": True,
                "high_amount_threshold": 5000000,
                "auto_freeze_risk_score": 90,
                "spam_detection_enabled": True
            }
        except Exception:
            return {
                "auto_flag_high_amount": True,
                "high_amount_threshold": 5000000,
                "auto_freeze_risk_score": 90,
                "spam_detection_enabled": True
            }

    def update_moderation_settings(self, settings: dict):
        try:
            # Try to update if exists, else insert
            existing = self.get_moderation_settings()
            if "id" in existing:
                self._safe_execute(self.supabase.table(Tables.MODERATION_SETTINGS).update(settings).eq("id", existing["id"]))
            else:
                self._safe_execute(self.supabase.table(Tables.MODERATION_SETTINGS).insert(settings))
            return True
        except Exception as e:
            logging.error(f"Failed to update moderation settings: {e}")
            return False

    def moderate_transaction(self, flag_id, status, admin_id):
        """Update the status of a flagged transaction."""
        try:
            data = {"status": status, "reviewed_by": admin_id, "reviewed_at": datetime.now().isoformat()}
            self._safe_execute(self.supabase.table(Tables.FLAGGED_TRANSACTIONS).update(data).eq("id", flag_id))
            return True
        except Exception as e:
            logging.error(f"Failed to moderate transaction: {e}")
            return False

    def resolve_dispute(self, dispute_id, status, resolution, admin_id):
        try:
            data = {
                "status": status, 
                "resolution": resolution, 
                "resolved_by": admin_id, 
                "resolved_at": datetime.now().isoformat()
            }
            self._safe_execute(self.supabase.table(Tables.DISPUTES).update(data).eq("id", dispute_id))
            return True
        except Exception as e:
            logging.error(f"Failed to resolve dispute: {e}")
            return False

    def is_superadmin(self, telegram_id):
        if telegram_id == SUPERADMIN_ID:
            return True
        user = self.get_user(telegram_id)
        return user and getattr(user, 'role', ROLE_USER) == ROLE_SUPERADMIN

    def is_admin(self, telegram_id):
        """General check for any admin-like role."""
        if telegram_id == SUPERADMIN_ID:
            return True
        user = self.get_user(telegram_id)
        if not user:
            return False
        role = getattr(user, 'role', ROLE_USER)
        return role in [ROLE_SUPERADMIN, ROLE_MODERATOR, ROLE_FINANCE, ROLE_SUPPORT]
