from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, budget_mgr, rules, visual_reporter
from utils.dashboard import update_pinned_dashboard
from utils.executor import execute_code
from config import CATEGORIES
from datetime import datetime
import os
import logging

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    user_data = context.user_data
    
    await query.answer()
    
    action = query.data
    pending = user_data.get('pending_tx')
    
    if action == "suggest_help":
        from handlers.commands import help_command
        await help_command(update, context)
        return

    if action == "suggest_budget":
        status = budget_mgr.check_budget_status(user_db.id, "Semua")
        await query.message.reply_text(status, reply_markup=get_main_menu_keyboard())
        return

    if action == "suggest_insight":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)
        return

    if action == "code_confirm":
        code_to_run = user_data.get('pending_code')
        if code_to_run:
            result = execute_code(code_to_run)
            msg = (
                "Thank you! Your code has been executed successfully. ✅\n\n"
                f"💻 **Output:**\n```\n{result}\n```"
            )
            await query.edit_message_text(msg, parse_mode='Markdown')
            await query.message.reply_text("Apa lagi yang bisa saya bantu? 😊", reply_markup=get_main_menu_keyboard())
            user_data.pop('pending_code', None)
        else:
            await query.edit_message_text("No code found to execute. ❌")
        return

    if action == "code_cancel":
        await query.edit_message_text("Edit cancelled. Feel free to ask again. 👍")
        await query.message.reply_text("Butuh bantuan lainnya?", reply_markup=get_main_menu_keyboard())
        user_data.pop('pending_code', None)
        return

    if action.startswith("report_"):
        period = action.replace("report_", "")
        report_msg = budget_mgr.generate_report(user_db.id, period=period)
        
        now = datetime.now()
        transactions = db.get_monthly_report(user_db.id, now.month, now.year)
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Detail Budget", callback_data="suggest_budget"),
                InlineKeyboardButton("💡 Tips Hemat", callback_data="suggest_insight")
            ],
            [
                InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")
            ]
        ]
        
        await query.edit_message_text(report_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
        photo_path = visual_reporter.generate_expense_pie(transactions, user_id)
        if photo_path:
            try:
                with open(photo_path, 'rb') as photo:
                    await query.message.reply_photo(photo, caption="Visualisasi Pengeluaran Anda")
            except Exception as e:
                logging.error(f"Error sending report photo: {e}")
            finally:
                if os.path.exists(photo_path):
                    os.remove(photo_path)
        return

    if action == "tx_confirm" and pending:
        tx_date = datetime.now()
        if pending.get('date'):
            try:
                date_clean = pending['date'].replace('/', '-')
                if len(date_clean.split('-')[0]) == 4:
                    tx_date = datetime.strptime(date_clean, "%Y-%m-%d")
                else:
                    tx_date = datetime.strptime(date_clean, "%d-%m-%Y")
            except:
                tx_date = datetime.now()

        tags = rules.evaluate({
            "amount": pending['amount'],
            "category": pending['category'],
            "hour": tx_date.hour
        })
        
        description = pending.get('merchant', 'Transaksi')
        if tags:
            description += f" ({', '.join(tags)})"

        db.add_transaction(
            user_id=user_db.id,
            amount=pending['amount'],
            category=pending['category'],
            trans_type='expense',
            description=description,
            trans_date=tx_date
        )
        
        budget_msg = budget_mgr.check_budget_status(user_db.id, pending['category'])
        
        final_msg = f"✅ Tersimpan: Rp{pending['amount']:,.0f} · {pending['category']}"
        if budget_msg:
            final_msg += f"\n\n{budget_msg}"
        else:
            final_msg += "\n\nMau catat transaksi lain atau cek laporan?"
            
        keyboard = [
            [
                InlineKeyboardButton("📊 Cek Budget", callback_data="suggest_budget"),
                InlineKeyboardButton("📈 Laporan", callback_data="report_monthly")
            ],
            [
                InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")
            ]
        ]
            
        await query.edit_message_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text("Ada lagi yang bisa saya bantu?", reply_markup=get_main_menu_keyboard())
        user_data.pop('pending_tx', None)
        user_data.pop('state', None)
        
        await update_pinned_dashboard(context, user_id)
        
    elif action == "tx_edit":
        keyboard = [
            [
                InlineKeyboardButton("Nominal", callback_data="edit_amount"),
                InlineKeyboardButton("Kategori", callback_data="edit_category")
            ],
            [
                InlineKeyboardButton("Tanggal", callback_data="edit_date"),
                InlineKeyboardButton("Abaikan", callback_data="tx_ignore")
            ]
        ]
        await query.edit_message_text("Pilih bagian yang ingin diubah:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "edit_amount":
        user_data['state'] = 'WAITING_EDIT_AMOUNT'
        await query.edit_message_text("Ketik nominal baru (contoh: 50rb atau 50000):")
        
    elif action == "edit_category":
        user_data['state'] = 'WAITING_EDIT_CATEGORY'
        keyboard = []
        for i in range(0, len(CATEGORIES), 2):
            row = [InlineKeyboardButton(cat, callback_data=f"set_cat_{cat}") for cat in CATEGORIES[i:i+2]]
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("Batal", callback_data="tx_edit")])
        await query.edit_message_text("Pilih kategori baru:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action.startswith("set_cat_"):
        new_cat = action.replace("set_cat_", "")
        if pending:
            pending['category'] = new_cat
            user_data['pending_tx'] = pending
            msg = f"Kategori diubah ke: {new_cat}\n\nRp{pending['amount']:,.0f} · {new_cat}"
            keyboard = [
                [
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                    InlineKeyboardButton("✎ Edit Lagi", callback_data="tx_edit")
                ]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "tx_ignore":
        user_data.pop('pending_tx', None)
        user_data.pop('state', None)
        await query.edit_message_text("Transaksi diabaikan. Ada lagi yang mau dicatat?")
        await query.message.reply_text("Silakan pilih menu di bawah:", reply_markup=get_main_menu_keyboard())

    elif action == "suggest_budget":
        # Handled above
        pass

    elif action == "report_monthly":
        # Already handled by report_ logic, but kept for direct calls
        report_msg = budget_mgr.generate_report(user_db.id, period='monthly')
        await query.message.reply_text(report_msg)

    elif action == "suggest_insight":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Bulan Ini", callback_data="report_monthly"),
            InlineKeyboardButton("7 Hari Terakhir", callback_data="report_7days"),
            InlineKeyboardButton("30 Hari Terakhir", callback_data="report_30days")
        ]
    ]
    
    msg = "Pilih periode laporan:"
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
