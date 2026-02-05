from telegram import Update
from telegram.ext import ContextTypes
from core import db, analyzer, ai
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
