import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, JobQueue
from datetime import time, datetime, timedelta
import pytz

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

    elif intent == "HELP":
        help_msg = (
            "🚀 **FinBot Command Center**\n\n"
            "**Catat Transaksi:**\n"
            "- 'kopi 25rb' atau 'gaji 10jt'\n"
            "- Kirim foto struk 📸\n\n"
            "**Perintah Baru:**\n"
            "- `/undo`: Batalkan transaksi terakhir\n"
            "- `/hapus [ID]`: Hapus transaksi spesifik\n"
            "- `/history`: Lihat semua riwayat\n"
            "- `/history cat:Makanan`: Filter kategori\n"
            "- `/history min:100k`: Filter nominal min\n\n"
            "**Manajemen Budget:**\n"
            "- `/setgaji [jumlah]`\n"
            "- `/setbudget [kategori] [jumlah]`\n\n"
            "Saldo & Dashboard diupdate otomatis di pesan tersemat (pin)!"
        )
        await update.message.reply_text(help_msg, parse_mode='Markdown')
        return

    elif intent == "GREETING":
        msg = f"Halo {update.effective_user.first_name}! 👋\nAku asisten finansial pribadimu. Mau catat apa hari ini?"
        keyboard = [
            [
                InlineKeyboardButton("📊 Status Budget", callback_data="suggest_budget"),
                InlineKeyboardButton("📈 Laporan", callback_data="report_monthly")
            ],
            [
                InlineKeyboardButton("⚙️ Perintah", callback_data="suggest_help")
            ]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Fallback for unknown/low confidence
    fallback_msg = "Maaf, aku tidak mengerti. Coba ketik 'help' untuk daftar perintah atau kirim foto struk."
    keyboard = [
        [
            InlineKeyboardButton("Bantuan", callback_data="suggest_help"),
            InlineKeyboardButton("Contoh: 'kopi 20k'", callback_data="suggest_example")
        ]
    ]
    await update.message.reply_text(fallback_msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    keyboard = [
        [
            InlineKeyboardButton("Bulan Ini", callback_data="report_monthly"),
            InlineKeyboardButton("7 Hari Terakhir", callback_data="report_7days"),
            InlineKeyboardButton("30 Hari Terakhir", callback_data="report_30days")
        ]
    ]
    await update.message.reply_text("Pilih periode laporan:", reply_markup=InlineKeyboardMarkup(keyboard))

async def update_pinned_dashboard(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_db = db.get_user(user_id)
    if not user_db:
        return
        
    report = budget_mgr.generate_report(user_db.id, period='monthly')
    budgets = db.get_user_budgets(user_db.id)
    balance = db.get_current_balance(user_db.id)
    
    summary = f"📌 **DASHBOARD KEUANGAN**\n"
    summary += f"💰 **Saldo Saat Ini: Rp{balance:,.0f}**\n\n"
    summary += f"{report}\n"
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

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    user_data = context.user_data
    
    await query.answer()
    
    action = query.data
    pending = user_data.get('pending_tx')
    
    if action.startswith("report_"):
        period = action.replace("report_", "")
        report_msg = budget_mgr.generate_report(user_db.id, period=period)
        await query.edit_message_text(report_msg)
        return

    if action == "tx_confirm" and pending:
        # Evaluate rules before saving
        from datetime import datetime
        
        # Parse date from pending or use today
        tx_date = datetime.now()
        if pending.get('date'):
            try:
                # Handle various date formats from OCR
                date_clean = pending['date'].replace('/', '-')
                if len(date_clean.split('-')[0]) == 4: # YYYY-MM-DD
                    tx_date = datetime.strptime(date_clean, "%Y-%m-%d")
                else: # DD-MM-YYYY
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
        
        # Check budget status after saving
        budget_msg = budget_mgr.check_budget_status(user_db.id, pending['category'])
        
        final_msg = f"✅ Tersimpan: Rp{pending['amount']:,.0f} · {pending['category']}"
        if budget_msg:
            final_msg += f"\n\n{budget_msg}"
            
        await query.edit_message_text(final_msg)
        user_data.pop('pending_tx', None)
        user_data.pop('state', None)
        
        # Update Pinned Dashboard
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
        # Group categories into rows of 2
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
                    InlineKeyboardButton("✎ Edit Lagi", callback_data="tx_edit"),
                    InlineKeyboardButton("✕ Abaikan", callback_data="tx_ignore")
                ]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        user_data.pop('state', None)

    elif action == "edit_date":
        user_data['state'] = 'WAITING_EDIT_DATE'
        await query.edit_message_text("Ketik tanggal transaksi (format: YYYY-MM-DD):")
        
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
    
    processing_msg = await update.message.reply_text("Sedang memproses struk... ⏳")
    
    try:
        ocr_result = ocr.process_receipt(file_path)
        amount = ocr_result.get('amount', 0)
        
        if amount > 0:
            merchant = ocr_result.get('merchant', 'Struk Belanja')
            date_str = ocr_result.get('date', datetime.now().strftime("%Y-%m-%d"))
            
            # Map merchant to category using NLP
            category = nlp._detect_category(merchant)
            if category == "Lain-lain":
                category = "Belanja" # Default for OCR
            
            # Store temporary transaction data for confirmation
            context.user_data['pending_tx'] = {
                'amount': amount,
                'category': category,
                'merchant': merchant,
                'date': date_str,
                'type': 'expense'
            }
            
            keyboard = [
                [
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                    InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
                    InlineKeyboardButton("✕ Abaikan", callback_data="tx_ignore")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            msg = (
                f"📝 **Data Struk Berhasil Dibaca**\n\n"
                f"💰 **Nominal:** Rp{amount:,.0f}\n"
                f"📂 **Kategori:** {category}\n"
                f"🏪 **Toko:** {merchant}\n"
                f"📅 **Tanggal:** {date_str}\n\n"
                f"Apakah data di atas sudah benar?"
            )
            await processing_msg.edit_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await processing_msg.edit_text("Maaf, aku nggak nemu total harganya. Bisa coba foto lagi atau ketik manual?")
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        await processing_msg.edit_text("Terjadi kesalahan saat memproses gambar. Coba pastikan foto struk terlihat jelas.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    if db.undo_last_transaction(user_db.id):
        await update.message.reply_text("✅ Transaksi terakhir berhasil dibatalkan (undo).")
        await update_pinned_dashboard(context, user_id)
    else:
        await update.message.reply_text("❌ Tidak ada transaksi untuk dibatalkan.")

async def hapus_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    if not context.args:
        await update.message.reply_text("Gunakan: `/hapus [ID]`\nContoh: `/hapus 123`", parse_mode='Markdown')
        return

    try:
        tx_id = int(context.args[0])
        if db.delete_transaction(user_db.id, tx_id):
            await update.message.reply_text(f"✅ Transaksi #{tx_id} berhasil dihapus.")
            await update_pinned_dashboard(context, user_id)
        else:
            await update.message.reply_text(f"❌ Transaksi #{tx_id} tidak ditemukan.")
    except ValueError:
        await update.message.reply_text("ID transaksi harus berupa angka.")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    # Parse filters from arguments
    category = None
    min_amount = None
    
    for arg in context.args:
        if arg.startswith("cat:"):
            category = arg.split(":", 1)[1]
        elif arg.startswith("min:"):
            try:
                min_amount = float(arg.split(":", 1)[1].replace('k', '000'))
            except:
                pass

    txs = db.get_transactions_history(user_db.id, category=category, min_amount=min_amount)
    
    if not txs:
        await update.message.reply_text("Belum ada riwayat transaksi atau tidak ditemukan filter yang cocok.")
        return

    msg = "📜 **RIWAYAT TRANSAKSI**\n\n"
    for tx in txs:
        date_str = tx.date.strftime("%d/%m %H:%M")
        msg += f"`#{tx.id}` {date_str} | **{tx.category}**\n   Rp{tx.amount:,.0f} - {tx.description[:20]}\n"
    
    msg += "\n💡 *Gunakan `/hapus [ID]` untuk menghapus transaksi.*"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_gaji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    try:
        if not context.args:
            await update.message.reply_text("Cara pakai: `/setgaji [jumlah]`\nContoh: `/setgaji 7300000`", parse_mode='Markdown')
            return
            
        amount = float(context.args[0].replace('.', '').replace(',', ''))
        db.add_monthly_income(user_db.id, amount)
        
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
        await update_pinned_dashboard(context, user_id)
        
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
        await update_pinned_dashboard(context, user_id)
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan: {e}")

async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic daily digest at night (21:00 WIB).
    Includes total expenses, category breakdown, budget utilization, and patterns.
    """
    now = datetime.now()
    users = db.get_all_users()
    
    for user in users:
        # 1. Total expenses for the day
        transactions = db.get_daily_transactions(user.id, now)
        if not transactions:
            continue
            
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        if total_expense == 0:
            continue
            
        # 2. Category-wise breakdown
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category
        } for t in transactions if t.type == 'expense'])
        cat_summary = df.groupby('category')['amount'].sum().sort_values(ascending=False)
        
        # 3. Budget utilization for top category
        top_cat = cat_summary.index[0]
        budget_info = budget_mgr.check_budget_status(user.id, top_cat)
        
        # 4. Trending patterns (e.g., comparison with last 7 days average)
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logging.error(f"Exception while handling an update: {context.error}")
    
    # Check for conflict error
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logging.error("CRITICAL: Conflict error detected! Another instance is running with the same token.")
        # We don't exit here as run_polling will handle retries, 
        # but this helps in identifying the issue in logs.

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
        exit(1)
        
    # Start health check server for Koyeb in a separate thread
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add global error handler
    application.add_error_handler(error_handler)
    
    # Scheduler for daily digest (Every night at 21:00 WIB)
    job_queue = application.job_queue
    # 21:00 WIB is 14:00 UTC (assuming server is UTC)
    job_queue.run_daily(daily_digest, time(hour=14, minute=0, tzinfo=pytz.UTC))
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setgaji", set_gaji))
    application.add_handler(CommandHandler("setbudget", set_budget))
    application.add_handler(CommandHandler("undo", undo))
    application.add_handler(CommandHandler("hapus", hapus_transaksi))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("rekomendasi", set_gaji))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("FinBot sedang berjalan...")
    # drop_pending_updates=True will clear old updates and help resolve conflict issues faster
    application.run_polling(drop_pending_updates=True)
