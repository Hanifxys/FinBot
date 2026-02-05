from telegram.ext import ContextTypes
from core import db, budget_mgr
import logging

async def update_pinned_dashboard(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_db = db.get_user(user_id)
    if not user_db:
        return
        
    report = budget_mgr.generate_report(user_db.id, period='monthly')
    budgets = db.get_user_budgets(user_db.id)
    balance = db.get_current_balance(user_db.id)
    goals = db.get_user_saving_goals(user_db.id)
    
    summary = f"📌 **DASHBOARD KEUANGAN PRO**\n"
    summary += f"💰 **Saldo Saat Ini: Rp{balance:,.0f}**\n\n"
    summary += f"{report}\n"

    if goals:
        summary += "\n🎯 **Saving Goals:**\n"
        for g in goals:
            prog = (g.current_amount / g.target_amount) * 100
            summary += f"• {g.name}: {prog:.1f}% (Rp{g.current_amount:,.0f}/Rp{g.target_amount:,.0f})\n"
    if budgets:
        summary += "\n📊 **Budget Utilization:**\n"
        for b in budgets:
            percent = (b.current_usage / b.limit_amount) * 100
            bar = "▓" * int(percent/10) + "░" * (10 - int(percent/10))
            summary += f"{b.category}: {bar} {percent:.0f}%\n"

    try:
        if user_db.pinned_message_id:
            await context.bot.edit_message_text(
                chat_id=user_db.telegram_id,
                message_id=user_db.pinned_message_id,
                text=summary,
                parse_mode='Markdown'
            )
        else:
            msg = await context.bot.send_message(
                chat_id=user_db.telegram_id,
                text=summary,
                parse_mode='Markdown'
            )
            await context.bot.pin_chat_message(chat_id=user_db.telegram_id, message_id=msg.message_id)
            user_db.pinned_message_id = msg.message_id
            db.session.commit()
    except Exception as e:
        logging.error(f"Error updating pinned dashboard: {e}")
