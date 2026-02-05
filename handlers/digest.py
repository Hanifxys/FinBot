import logging
import pandas as pd
from datetime import datetime
from telegram.ext import ContextTypes
from core import db, budget_mgr
import pytz

async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic daily digest at night (21:00 WIB).
    Includes total expenses, category breakdown, budget utilization, and patterns.
    """
    now = datetime.now()
    users = db.get_all_users()
    
    for user in users:
        transactions = db.get_daily_transactions(user.id, now)
        if not transactions:
            continue
            
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        if total_expense == 0:
            continue
            
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category
        } for t in transactions if t.type == 'expense'])
        cat_summary = df.groupby('category')['amount'].sum().sort_values(ascending=False)
        
        top_cat = cat_summary.index[0]
        budget_info = budget_mgr.check_budget_status(user.id, top_cat)
        
        last_7_days = db.get_sliding_window_transactions(user.id, days=7)
        if last_7_days:
            avg_7_days = sum(t.amount for t in last_7_days if t.type == 'expense') / 7
            trend = "📈 Di atas rata-rata" if total_expense > avg_7_days else "📉 Di bawah rata-rata"
        else:
            trend = ""

        msg = (f"🌙 **DAILY DIGEST**\n\n"
               f"💰 Total Hari Ini: Rp{total_expense:,.0f}\n"
               f"{trend}\n\n"
               f"📂 Breakdown:\n")
        
        for cat, amt in cat_summary.items():
            msg += f"- {cat}: Rp{amt:,.0f}\n"
            
        if budget_info:
            msg += f"\n💡 {budget_info}"
            
        try:
            await context.bot.send_message(chat_id=user.telegram_id, text=msg, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Failed to send digest to {user.telegram_id}: {e}")
