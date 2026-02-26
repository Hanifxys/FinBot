from supabase import create_client, Client
import sys
import os

# Add project root to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SUPABASE_URL, SUPABASE_KEY

# Initialize Supabase Client
supabase: Client = None

def get_supabase():
    global supabase
    if supabase is None:
        # Re-import and re-load just in case of race conditions during startup
        from config import SUPABASE_URL, SUPABASE_KEY
        
        url = SUPABASE_URL or os.environ.get("SUPABASE_URL")
        key = SUPABASE_KEY or os.environ.get("SUPABASE_KEY")
        
        if not url or not key:
            raise ValueError(f"SUPABASE_URL or SUPABASE_KEY is missing. URL found: {bool(url)}, Key found: {bool(key)}")
        supabase = create_client(url, key)
    return supabase

def init_db():
    """
    Supabase handles schema creation via dashboard/migrations.
    This function remains for compatibility with existing code.
    """
    pass

# We don't need SQLAlchemy classes here anymore as we'll use dictionaries with Supabase,
# but keeping simple names for reference in other files if needed.
class Tables:
    USERS = "users"
    MONTHLY_INCOMES = "monthly_incomes"
    TRANSACTIONS = "transactions"
    BUDGETS = "budgets"
    SAVING_GOALS = "saving_goals"
    ADMIN_LOGS = "admin_logs"
    FLAGGED_TRANSACTIONS = "flagged_transactions"
    DISPUTES = "disputes"
    MODERATION_SETTINGS = "moderation_settings"
