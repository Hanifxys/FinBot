
import asyncio
import os
import sys
import random
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.getcwd())

from database.db_handler import DBHandler
from database.models import Tables

async def insert_dummy_data():
    print("🚀 Starting dummy data insertion...")
    db = DBHandler()
    
    # 1. Ensure Target User exists (Superadmin or test user)
    # Using Hanif's ID as primary target for dashboard verification
    target_telegram_id = 1512347775 
    user = db.get_or_create_user(target_telegram_id, "m_hanif77")
    print(f"✅ User verified: {user.username} (ID: {user.id})")
    
    # 2. Insert Monthly Income if not present
    # Check if target user has income
    print("📊 Inserting monthly incomes...")
    income_data = {
        "user_id": user.id,
        "amount": 15000000.0, # 15jt
        "source": "Gaji Utama",
        "month": datetime.now().month,
        "year": datetime.now().year
    }
    try:
        db.supabase.table(Tables.MONTHLY_INCOMES).insert(income_data).execute()
    except Exception as e:
        print(f"⚠️ Income might already exist or error: {e}")

    # 3. Insert Bulk Transactions (Last 30 days)
    print("💸 Inserting bulk transactions...")
    categories = ["Makanan", "Transportasi", "Hiburan", "Tagihan", "Belanja", "Kesehatan"]
    merchants = ["Gojek", "Grab", "Indomaret", "Alfamart", "Netflix", "Spotify", "Tokopedia", "Shopee"]
    
    transactions = []
    now = datetime.now()
    for i in range(50):
        days_ago = random.randint(0, 30)
        date = (now - timedelta(days=days_ago)).isoformat()
        category = random.choice(categories)
        amount = random.randint(20000, 500000)
        
        # Note: add_transaction handles encryption of description
        # We'll bypass and do bulk insert for speed, but manually encrypting is complex here
        # So we'll use db.add_transaction for a few and bulk for the rest
        if i < 5:
            db.add_transaction(user.id, amount, category, f"Dummy {category} at {random.choice(merchants)}", "expense", date)
        else:
            transactions.append({
                "user_id": user.id,
                "amount": float(amount),
                "category": category,
                "description": None, # Keep simple for dummy bulk
                "type": "expense",
                "date": date
            })
    
    if transactions:
        db.supabase.table(Tables.TRANSACTIONS).insert(transactions).execute()
    print(f"✅ Inserted {len(transactions) + 5} transactions.")

    # 4. Insert Budgets
    print("📅 Setting dummy budgets...")
    for cat in categories:
        limit = random.randint(1000000, 3000000)
        db.set_budget(user.id, cat, float(limit))
    
    # 5. Insert AI Intelligence Logs (If table exists, though usually handled via intelligence layer)
    # We can simulate AI usage by just ensuring intelligence manager can load
    print("🧠 Simulating AI activity...")
    from core import intelligence_manager
    intel = intelligence_manager.get_layer(target_telegram_id)
    await intel.process_interaction("Halo, bantu saya kelola uang")
    await intel.process_interaction("Berapa sisa budget makan saya?")
    
    print("✨ Dummy data insertion completed successfully!")

if __name__ == "__main__":
    asyncio.run(insert_dummy_data())
