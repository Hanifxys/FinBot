import logging
import pandas as pd
from datetime import datetime, timedelta
from telegram.ext import ContextTypes
from core import db, budget_mgr, premium_ai
import pytz
import random

async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic daily digest at night (21:00 WIB).
    Includes total expenses, category breakdown, budget utilization, and patterns.
    """
    now = datetime.now()
    users = db.get_all_users()
    
    for user in users:
        try:
            transactions = db.get_daily_transactions(user.id, now)
            if not transactions:
                # If no transactions today, check last activity for reminder
                await check_and_send_reminder(context, user)
                continue
                
            total_expense = sum(t.amount for t in transactions if t.type == 'expense')
            if total_expense == 0:
                await check_and_send_reminder(context, user)
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
                goals = db.get_user_saving_goals(user.id)
                active = []
                for g in goals or []:
                    try:
                        prog = (g.current_amount / g.target_amount) * 100
                    except Exception:
                        prog = 0
                    if prog < 100:
                        active.append(g)
                if active:
                    g = active[0]
                    msg += f"\n\n🎯 Target: **{g.name}**"
                    try:
                        remaining = g.target_amount - g.current_amount
                        msg += f"\nSisa: Rp{remaining:,.0f}"
                        if getattr(g, "target_date", None):
                            now = datetime.now()
                            td = g.target_date
                            months_left = max(1, (td.year - now.year) * 12 + (td.month - now.month) + (1 if td.day > now.day else 0))
                            req = remaining / months_left
                            msg += f"\nPerlu: Rp{req:,.0f}/bulan"
                    except Exception:
                        pass
            except Exception:
                pass
                
            await context.bot.send_message(chat_id=user.telegram_id, text=msg, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Failed to process digest for {user.telegram_id}: {e}")

async def check_and_send_reminder(context: ContextTypes.DEFAULT_TYPE, user):
    """
    Intelligent 24-hour reminder system.
    Sends a friendly nudge if user hasn't interacted for >24 hours.
    """
    try:
        # Check last interaction time from Redis or DB
        # For now, we use DB's last transaction as a proxy, but ideally should be last_interaction
        # Assuming DB has a method or we track it. 
        # Fallback: check last transaction date.
        
        last_tx = db.get_last_transaction_date(user.id)
        if not last_tx:
            # New user or no data ever? Skip to avoid spamming unless we want onboarding.
            return

        now = datetime.now()
        # Parse last_tx safely (it might be string or datetime)
        if isinstance(last_tx, str):
            try:
                last_dt = datetime.fromisoformat(last_tx.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                return 
        else:
            last_dt = last_tx

        # Check user preference (Opt-out)
        from modules.redis_mgr import RedisManager
        redis = RedisManager()
        pref = redis.client.get(f"user:{user.id}:reminder_enabled")
        # Default is ON (None) or "1". If "0", skip.
        if pref and pref.decode() == "0":
            return

        diff = now - last_dt
        
        # If silent for > 24 hours (and < 48 hours to avoid spamming dead users daily)
        if timedelta(hours=24) < diff < timedelta(hours=48):
            # Generate AI-powered contextual reminder
            persona = premium_ai.persona_mgr.get_persona(user.id)
            
            prompts = [
                "Hai! Belum ada pengeluaran hari ini? Jangan lupa catat kalau ada ya! 📝",
                "Kangen nih! Dompet aman? 🤑 Cek budget yuk!",
                "Psst... udah jajan apa aja hari ini? Sini aku catatin biar gak lupa! 🧐",
                "Reminder santai: Pencatatan rutin bikin finansial makin sehat loh! 🚀"
            ]
            
            # Use AI to generate variant if possible, else random
            ai_msg = await premium_ai.generate_reminder(user.id)
            msg = ai_msg if ai_msg else random.choice(prompts)
            
            await context.bot.send_message(chat_id=user.telegram_id, text=msg)
            
    except Exception as e:
        logging.error(f"Reminder error for {user.telegram_id}: {e}")
