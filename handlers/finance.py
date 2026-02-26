from telegram import Update
from telegram.ext import ContextTypes
from core import db, analyzer, ai
from utils.dashboard import update_pinned_dashboard
import logging

async def set_gaji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if not context.args:
        await update.message.reply_text("Cara pakai: `/setgaji [Nominal]`\nContoh: `/setgaji 5000000` atau `/setgaji 5jt`", parse_mode='Markdown')
        return

    try:
        amount_str = context.args[0].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        db.add_monthly_income(user_db.id, amount)
        await update.message.reply_text(f"✅ Pendapatan bulanan berhasil diatur ke Rp{amount:,.0f}. Semangat mengelola uangnya! 💪", parse_mode='Markdown')
        await update_pinned_dashboard(update, context)
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if len(context.args) < 2:
        await update.message.reply_text("Cara pakai: `/setbudget [Kategori] [Nominal]`\nContoh: `/setbudget Makanan 1000000`", parse_mode='Markdown')
        return

    category = context.args[0].capitalize()
    try:
        amount_str = context.args[1].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        db.set_budget(user_db.id, category, amount)
        await update.message.reply_text(f"✅ Budget {category} berhasil diatur ke Rp {amount:,.0f} per bulan.")
        await update_pinned_dashboard(update, context)
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")

async def get_ai_insight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return
    
    raw_insight = analyzer.analyze_patterns(user_db.id)
    ai_insight = ai.generate_smart_insight(raw_insight)
    
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(f"🤖 **FINBOT AI ADVISOR**\n\n{ai_insight}", parse_mode='Markdown')

async def set_budget_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Configure alert thresholds for a budget category.
    Usage: /budgetalert [Kategori] [warn%] [limit%]
    """
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return
    if len(context.args) < 3:
        await update.message.reply_text("Cara pakai: `/budgetalert [Kategori] [warn%] [limit%]`\nContoh: `/budgetalert Makanan 80 100`", parse_mode='Markdown')
        return
    category = context.args[0].capitalize()
    try:
        warn = float(context.args[1]) / 100.0
        limit = float(context.args[2]) / 100.0
        db.set_budget_threshold(user_db.id, category, warn, limit)
        await update.message.reply_text(f"✅ Alert {category} diatur: Warning {warn*100:.0f}% • Limit {limit*100:.0f}%")
    except Exception as e:
        await update.message.reply_text(f"Gagal mengatur alert: {e}")
