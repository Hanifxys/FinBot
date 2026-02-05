from telegram import Update
from telegram.ext import ContextTypes
from core import db
import logging

async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if len(context.args) < 2:
        await update.message.reply_text("Cara pakai: `/target [Nama Barang] [Nominal]`\nContoh: `/target Laptop 10000000`", parse_mode='Markdown')
        return

    try:
        name = " ".join(context.args[:-1])
        amount_str = context.args[-1].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        db.add_saving_goal(user_db.id, name, amount)
        await update.message.reply_text(f"✅ Target **{name}** sebesar Rp{amount:,.0f} berhasil dibuat! Ayo menabung! 🚀", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")

async def add_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if len(context.args) < 2:
        await update.message.reply_text("Cara pakai: `/nabung [ID_Target] [Nominal]`\nCek ID di `/list_target`", parse_mode='Markdown')
        return

    try:
        goal_id = int(context.args[0])
        amount_str = context.args[1].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        goal = db.update_saving_progress(user_db.id, goal_id, amount)
        
        if goal:
            progress = (goal.current_amount / goal.target_amount) * 100
            msg = f"💰 **Tabungan Ditambah!**\n\nTarget: {goal.name}\nProgres: Rp{goal.current_amount:,.0f} / Rp{goal.target_amount:,.0f} ({progress:.1f}%)\n"
            if progress >= 100:
                msg += "\n🎉 **SELAMAT!** Target kamu sudah tercapai! Silakan beli barang impianmu!"
            else:
                msg += f"🔥 Sedikit lagi! Butuh Rp{goal.target_amount - goal.current_amount:,.0f} lagi."
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Target tidak ditemukan.")
    except ValueError:
        await update.message.reply_text("Format ID atau nominal salah.")

async def list_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    goals = db.get_user_saving_goals(user_db.id)
    if not goals:
        await update.message.reply_text("Kamu belum punya target menabung. Buat dengan `/target`")
        return

    msg = "🎯 **DAFTAR TARGET MENABUNG**\n\n"
    for goal in goals:
        progress = (goal.current_amount / goal.target_amount) * 100
        status = "✅" if progress >= 100 else "⏳"
        msg += f"{status} `#{goal.id}` | **{goal.name}**\n   Rp{goal.current_amount:,.0f} / Rp{goal.target_amount:,.0f} ({progress:.1f}%)\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')
