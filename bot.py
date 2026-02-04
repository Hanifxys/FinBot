import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from config import TELEGRAM_BOT_TOKEN, CATEGORIES
from database.db_handler import DBHandler
from modules.ocr import OCRProcessor
from modules.nlp import NLPProcessor
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer
from modules.rules import RuleEngine
from utils.visuals import VisualReporter

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize components
db = DBHandler()
ocr = OCRProcessor()
nlp = NLPProcessor()
budget_mgr = BudgetManager(db)
analyzer = ExpenseAnalyzer(db)
rules = RuleEngine()
visual_reporter = VisualReporter()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)
    
    welcome_msg = (
        f"Halo {user.first_name}! Aku FinBot.\n\n"
        "Aku bakal bantu catat pengeluaranmu otomatis.\n"
        "Cukup ketik misal: `kopi 25rb` atau kirim foto struk.\n\n"
        "Ketik `/setgaji [jumlah]` buat mulai alokasi budget."
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    user_data = context.user_data
    state = user_data.get('state', 'IDLE')
    
    # AI-Powered Intent Detection with State Awareness
    intent_data = nlp.classify_intent(text, state)
    intent = intent_data['intent']
    confidence = intent_data['confidence']

    # Handle EDIT_TRANSACTION state strictly
    if state.startswith('WAITING_EDIT'):
        field = state.split('_')[-1].lower() # e.g., WAITING_EDIT_AMOUNT -> amount
        
        if intent == "CANCEL":
            user_data.pop('state', None)
            await update.message.reply_text("Edit dibatalkan.")
            return
            
        validation = nlp.validate_edit(field, text)
        if validation['valid']:
            # Update pending transaction
            pending = user_data.get('pending_tx')
            if pending:
                pending[field] = validation['new_value']
                user_data.pop('state', None)
                
                # Show updated transaction
                msg = f"Rp{pending['amount']:,.0f} · {pending['category']}\n{pending.get('merchant', '')}"
                keyboard = [
                    [
                        InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                        InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
                        InlineKeyboardButton("✕ Abaikan", callback_data="tx_ignore")
                    ]
                ]
                await update.message.reply_text(f"Berhasil diubah:\n{msg}", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(f"Gagal: {validation['reason']}. Pilih tombol di atas atau ketik 'batal'.")
        return

    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    # Handle Global Intents
    if intent == "ADD_TRANSACTION":
        tx_data = nlp.extract_transaction_data(text)
        if tx_data['confidence'] >= 0.7:
            user_data['pending_tx'] = tx_data
            msg = f"Rp{tx_data['amount']:,.0f} · {tx_data['category']}\n{tx_data['merchant'] if tx_data['merchant'] else ''}"
            keyboard = [
                [
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                    InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
                    InlineKeyboardButton("✕ Abaikan", callback_data="tx_ignore")
                ]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif intent == "CHECK_BUDGET":
        await send_budget_summary(update, context)
        return
        
    elif intent == "QUERY_SUMMARY":
        await send_report(update, context)
        return

    # Fallback for unknown/low confidence
    if any(kw in text.lower() for kw in ["halo", "hi", "hai", "p"]):
        msg = f"Halo {update.effective_user.first_name}! Ada yang bisa kubantu catat?"
        keyboard = [[
            InlineKeyboardButton("/setgaji", callback_data="suggest_/setgaji"),
            InlineKeyboardButton("Laporan", callback_data="suggest_laporan")
        ]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Maaf, aku tidak mengerti. Coba: 'kopi 25rb' atau 'sisa budget'.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    await query.answer()
    
    action = query.data
    pending = context.user_data.get('pending_tx')
    
    if action == "tx_confirm" and pending:
        # Evaluate rules before saving
        from datetime import datetime
        hour = datetime.now().hour
        tags = rules.evaluate({
            "amount": pending['amount'],
            "category": pending['category'],
            "hour": hour
        })
        
        description = pending['merchant']
        if tags:
            description += f" ({', '.join(tags)})"

        db.add_transaction(
            user_id=user_db.id,
            amount=pending['amount'],
            category=pending['category'],
            type='expense',
            description=description
        )
        
        # Check budget status after saving
        budget_msg = budget_mgr.check_budget_status(user_db.id, pending['category'])
        
        # Principle 2.1: Simple response (Confirmation + Sisa Budget)
        final_msg = f"Rp{pending['amount']:,.0f} · {pending['category']}"
        if budget_msg:
            final_msg += f"\n{budget_msg}"
            
        await query.edit_message_text(final_msg)
        context.user_data.pop('pending_tx', None)
        
    elif action == "tx_edit":
        user_data['state'] = 'WAITING_EDIT_CHOICE'
        keyboard = [
            [
                InlineKeyboardButton("Nominal", callback_data="edit_amount"),
                InlineKeyboardButton("Kategori", callback_data="edit_category"),
                InlineKeyboardButton("Batal", callback_data="tx_ignore")
            ]
        ]
        await query.edit_message_text("Edit apa?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "edit_amount":
        user_data['state'] = 'WAITING_EDIT_AMOUNT'
        await query.edit_message_text("Ketik nominal baru (contoh: 50rb atau 50000):")
        
    elif action == "edit_category":
        user_data['state'] = 'WAITING_EDIT_CATEGORY'
        await query.edit_message_text("Ketik kategori baru (contoh: Makan, Transport, Belanja):")
        
    elif action == "view_salary_summary":
        user_id = update.effective_user.id
        user_db = db.get_user(user_id)
        # Get the latest income for this month
        income = db.get_monthly_income(user_db.id)
        if income:
            msg, _ = budget_mgr.get_allocation_recommendation(income)
            await query.edit_message_text(msg)
        else:
            await query.edit_message_text("Data gaji belum ada.")

    elif action == "tx_ignore":
        user_data = context.user_data
        user_data.pop('state', None)
        await query.edit_message_text("Transaksi diabaikan.")
        user_data.pop('pending_tx', None)

    elif action == "show_budget_menu":
        await query.edit_message_text("Mau ubah alokasi?")
        keyboard = [
            [
                InlineKeyboardButton("Ubah persentase", callback_data="change_allocation"),
                InlineKeyboardButton("Biarkan", callback_data="tx_ignore")
            ]
        ]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif action.startswith("suggest_"):
        suggested_cmd = action.split("_")[1]
        if suggested_cmd == "/setgaji":
            await query.edit_message_text("Ketik `/setgaji [jumlah]` untuk mulai. Contoh: `/setgaji 7.5jt`", parse_mode='Markdown')
        elif suggested_cmd == "/setbudget":
            await query.edit_message_text("Ketik `/setbudget [Kategori] [Jumlah]` untuk atur limit.", parse_mode='Markdown')
        elif suggested_cmd == "laporan":
            await send_report(update, context)
        else:
            await query.edit_message_text(f"Kamu memilih: {suggested_cmd}")

async def send_budget_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    budgets = db.get_user_budgets(user_db.id)
    
    if not budgets:
        await update.message.reply_text("Kamu belum set budget apapun. Gunakan `/setbudget [Kategori] [Jumlah]`")
        return
        
    msg = ""
    for b in budgets:
        msg += budget_mgr.get_detailed_budget_status(user_db.id, b.category) + "\n\n"
    
    await update.message.reply_text(msg.strip())

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    from datetime import datetime
    now = datetime.now()
    report = budget_mgr.generate_report(user_db.id)
    transactions = db.get_monthly_report(user_db.id, now.month, now.year)
    
    await update.message.reply_text(report)
    
    photo_path = visual_reporter.generate_expense_pie(transactions, user_id)
    if photo_path:
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo, caption="Visualisasi Pengeluaran Anda")
        os.remove(photo_path)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not ocr.enabled:
        await update.message.reply_text("Maaf, fitur baca struk (OCR) sedang dinonaktifkan di server untuk menghemat memori. Kamu bisa catat manual ya!")
        return

    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    # Download photo
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"temp_{user_id}.jpg"
    await photo_file.download_to_drive(file_path)
    
    await update.message.reply_text("Sedang memproses struk... ⏳")
    
    try:
        amount = ocr.process_receipt(file_path)
        if amount > 0:
            category = "Belanja"
            merchant = "Struk Belanja"
            
            # Store temporary transaction data for confirmation
            context.user_data['pending_tx'] = {
                'amount': amount,
                'category': category,
                'merchant': merchant,
                'type': 'expense'
            }
            
            keyboard = [
                [
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_save"),
                    InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
                    InlineKeyboardButton("✕ Abaikan", callback_data="tx_ignore")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            msg = f"Rp {amount:,.0f} · {category}\n{merchant}"
            await update.message.reply_text(msg, reply_markup=reply_markup)
        else:
            await update.message.reply_text("Maaf, aku nggak nemu total harganya. Bisa coba foto lagi atau ketik manual?")
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        await update.message.reply_text("Terjadi kesalahan saat memproses gambar.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def set_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    try:
        if not context.args:
            await update.message.reply_text("Cara pakai: `/setgaji [jumlah]`\nContoh: `/setgaji 7300000`", parse_mode='Markdown')
            return
            
        amount = float(context.args[0].replace('.', '').replace(',', ''))
        db.add_monthly_income(user_db.id, amount)
        
        # Principle 3.1: Ringkas
        keyboard = [
            [
                InlineKeyboardButton("Lihat ringkasan", callback_data="view_salary_summary"),
                InlineKeyboardButton("Atur budget", callback_data="show_budget_menu")
            ]
        ]
        await update.message.reply_text(
            f"Gaji dicatat: Rp{amount:,.0f}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan: {e}")

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    try:
        # Expected: /setbudget Makanan 2000000
        args = context.args
        if len(args) < 2:
            categories_str = ", ".join(CATEGORIES)
            await update.message.reply_text(f"Cara pakai: `/setbudget [Kategori] [Jumlah]`\nContoh: `/setbudget Makanan 2000000`\n\nKategori: {categories_str}", parse_mode='Markdown')
            return
            
        category = args[0].capitalize()
        if category not in CATEGORIES:
            await update.message.reply_text(f"Kategori tidak valid. Pilih salah satu: {', '.join(CATEGORIES)}")
            return
            
        amount = float(args[1].replace('.', '').replace(',', ''))
        db.set_budget(user_db.id, category, amount)
        
        await update.message.reply_text(f"✅ Budget {category} berhasil diatur ke Rp {amount:,.0f} per bulan.")
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan: {e}")

async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic daily digest at night.
    Principle 2.4: Only send if there are transactions.
    """
    from datetime import datetime
    import pandas as pd
    now = datetime.now()
    users = db.get_all_users()
    
    for user in users:
        transactions = db.get_daily_transactions(user.id, now.day, now.month, now.year)
        if not transactions:
            continue
            
        total = sum(t.amount for t in transactions if t.type == 'expense')
        if total == 0:
            continue
            
        # Get top category
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category
        } for t in transactions if t.type == 'expense'])
        top_cat = df.groupby('category')['amount'].sum().idxmax()
        top_amt = df.groupby('category')['amount'].sum().max()
        
        msg = (f"Hari ini: Rp {total:,.0f}\n"
               f"Terbesar: {top_cat} Rp {top_amt:,.0f}\n\n")
        
        # Add budget info for top category
        budget_info = budget_mgr.check_budget_status(user.id, top_cat)
        if budget_info:
            msg += budget_info
            
        try:
            await context.bot.send_message(chat_id=user.telegram_id, text=msg)
        except Exception as e:
            print(f"Failed to send digest to {user.telegram_id}: {e}")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        # Silence logs to keep things clean
        return

def run_health_check_server():
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health check server running on port {port}")
    server.serve_forever()

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
        exit(1)
        
    # Start health check server for Koyeb in a separate thread
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Scheduler for daily digest (Every night at 21:00)
    job_queue = application.job_queue
    from datetime import time
    job_queue.run_daily(daily_digest, time(hour=21, minute=0))
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setgaji", set_salary))
    application.add_handler(CommandHandler("setbudget", set_budget))
    application.add_handler(CommandHandler("rekomendasi", set_salary)) # Alias for showing recommendation
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("FinBot sedang berjalan...")
    application.run_polling()
