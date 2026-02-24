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
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
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
