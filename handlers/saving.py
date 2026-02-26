from telegram import Update
from telegram.ext import ContextTypes
from core import db
import logging
from datetime import datetime, timedelta
from modules.amounts import parse_primary_amount_id

def _add_months(dt: datetime, months: int) -> datetime:
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.replace(year=y, month=m, day=d)

def _months_left(now: datetime, target: datetime) -> int:
    if target <= now:
        return 1
    return max(1, (target.year - now.year) * 12 + (target.month - now.month) + (1 if target.day > now.day else 0))

async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if len(context.args) < 2:
        await update.message.reply_text("Cara pakai: `/target [Nama] [Nominal] [Deadline]`\nContoh: `/target Laptop 10jt 6bulan`", parse_mode='Markdown')
        return

    try:
        target_date = None
        deadline_token = None
        if len(context.args) >= 3:
            last = context.args[-1].lower()
            if last.endswith("bulan") or last.endswith("bln") or last.endswith("month") or "-" in last:
                deadline_token = context.args[-1]

        if deadline_token:
            amount_token = context.args[-2]
            name = " ".join(context.args[:-2])
        else:
            amount_token = context.args[-1]
            name = " ".join(context.args[:-1])

        amount = parse_primary_amount_id(amount_token)
        if not amount:
            raise ValueError("amount")

        if deadline_token:
            d = deadline_token.strip().lower()
            now = datetime.now()
            if "-" in d:
                try:
                    target_date = datetime.fromisoformat(d)
                except Exception:
                    target_date = None
            if target_date is None:
                digits = "".join([c for c in d if c.isdigit()])
                months = int(digits) if digits else 0
                if months > 0:
                    target_date = _add_months(now, months)

        db.add_saving_goal(user_db.id, name, float(amount), target_date=target_date.isoformat() if target_date else None)

        msg = f"✅ Target **{name}**: Rp{float(amount):,.0f}"
        if target_date:
            mleft = _months_left(datetime.now(), target_date)
            req = (float(amount) / mleft) if mleft > 0 else float(amount)
            msg += f"\n⏳ Deadline: {target_date.strftime('%d-%m-%Y')} ({mleft} bulan)\n📌 Perlu nabung: **Rp{req:,.0f}/bulan**"
        msg += "\n\nKetik `/nabung ID nominal` untuk update progres."
        await update.message.reply_text(msg, parse_mode='Markdown')
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
        amount = parse_primary_amount_id(context.args[1])
        if not amount:
            raise ValueError("amount")
            
        goal = db.update_saving_progress(user_db.id, goal_id, float(amount))
        
        if goal:
            progress = (goal.current_amount / goal.target_amount) * 100
            msg = f"💰 **Tabungan Ditambah!**\n\nTarget: {goal.name}\nProgres: Rp{goal.current_amount:,.0f} / Rp{goal.target_amount:,.0f} ({progress:.1f}%)\n"
            if progress >= 100:
                msg += "\n🎉 **SELAMAT!** Target kamu sudah tercapai! Silakan beli barang impianmu!"
            else:
                remaining = goal.target_amount - goal.current_amount
                msg += f"🔥 Sedikit lagi! Sisa Rp{remaining:,.0f}."
                try:
                    if getattr(goal, "target_date", None):
                        td = goal.target_date
                        mleft = _months_left(datetime.now(), td)
                        req = remaining / mleft
                        msg += f"\n📌 Perlu nabung: Rp{req:,.0f}/bulan"
                except Exception:
                    pass
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
        msg += f"{status} `#{goal.id}` | **{goal.name}**\n   Rp{goal.current_amount:,.0f} / Rp{goal.target_amount:,.0f} ({progress:.1f}%)"
        try:
            if getattr(goal, "target_date", None) and progress < 100:
                td = goal.target_date
                mleft = _months_left(datetime.now(), td)
                remaining = goal.target_amount - goal.current_amount
                req = remaining / mleft
                msg += f"\n   ⏳ {td.strftime('%d-%m-%Y')} · Rp{req:,.0f}/bulan"
        except Exception:
            pass
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')
