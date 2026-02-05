from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, ocr, nlp, budget_mgr
from utils.dashboard import update_pinned_dashboard
from datetime import datetime
import os
import logging

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if this is a code block
    if text.startswith("```python") and text.endswith("```"):
        code = text.replace("```python", "").replace("```", "").strip()
        context.user_data['pending_code'] = code
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm Edit", callback_data="code_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="code_cancel")
            ]
        ]
        
        await update.message.reply_text(
            "I've received your code. Would you like me to execute it on the server? 🚀",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Handle quick reply buttons
    if text == "📊 Cek Budget":
        await send_budget_summary(update, context)
        return
    elif text == "📈 Laporan":
        from handlers.callbacks import send_report
        await send_report(update, context)
        return
    elif text == "💡 Tips Hemat":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)
        return
    elif text == "🚀 Menu Utama":
        from handlers.commands import help_command
        await help_command(update, context)
        return

    # Check if user is in an edit state
    state = context.user_data.get('state')
    if state == 'WAITING_EDIT_AMOUNT':
        try:
            amount_str = text.lower().replace('.', '').replace(',', '')
            if 'rb' in amount_str:
                amount = float(amount_str.replace('rb', '')) * 1000
            elif 'jt' in amount_str:
                amount = float(amount_str.replace('jt', '')) * 1000000
            else:
                amount = float(amount_str)
                
            pending = context.user_data.get('pending_tx')
            if pending:
                pending['amount'] = amount
                context.user_data['pending_tx'] = pending
                
                keyboard = [
                    [
                        InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                        InlineKeyboardButton("✎ Edit Lagi", callback_data="tx_edit")
                    ]
                ]
                await update.message.reply_text(
                    f"Nominal diubah ke: Rp{amount:,.0f}\n\n"
                    f"Rp{amount:,.0f} · {pending['category']}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data['state'] = None
            return
        except ValueError:
            await update.message.reply_text("Format nominal salah. Masukkan angka saja.")
            return

    # Normal NLP Processing
    # Check for state-based inputs first
    if state == 'WAITING_EDIT_CATEGORY':
        pending = context.user_data.get('pending_tx')
        if pending:
            pending['category'] = text
            context.user_data['pending_tx'] = pending
            context.user_data['state'] = None
            await update.message.reply_text(f"Kategori diubah ke: {text}")
        return
        
    if state == 'WAITING_EDIT_DATE':
        pending = context.user_data.get('pending_tx')
        if pending:
            pending['date'] = text
            context.user_data['pending_tx'] = pending
            context.user_data['state'] = None
            await update.message.reply_text(f"Tanggal diubah ke: {text}")
        return

    # Normal NLP Processing
    amount, category, trans_type = nlp.process_text(text)
    
    if amount > 0:
        user_db = db.get_or_create_user(user_id, update.effective_user.username)
        db.add_transaction(user_db.id, amount, category, text, trans_type)
        
        budget_msg = budget_mgr.check_budget_status(user_db.id, category)
        
        reply = f"✅ Tercatat: Rp{amount:,.0f} · {category}"
        if budget_msg:
            reply += f"\n\n{budget_msg}"
            
        await update.message.reply_text(reply, reply_markup=get_main_menu_keyboard())
        await update_pinned_dashboard(context, user_id)
    else:
        # Check for other intents via NLP parse
        parsed = nlp.parse_message(text)
        intent = parsed.get('intent')
        
        if intent == 'query_budget':
            await send_budget_summary(update, context)
        elif intent == 'get_report':
            from handlers.callbacks import send_report
            await send_report(update, context)
        elif intent == 'help':
            from handlers.commands import help_command
            await help_command(update, context)
        elif intent == 'greeting':
            await update.message.reply_text(
                f"Halo {update.effective_user.first_name}! Ada yang bisa dibantu? 😊",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "Aku nggak paham maksudnya. Coba ketik 'makan 50rb' atau cek /help. 🤔",
                reply_markup=get_main_menu_keyboard()
            )

async def send_budget_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    status = budget_mgr.get_detailed_budget_status(user_db.id)
    if update.callback_query:
        await update.callback_query.message.reply_text(status, reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text(status, reply_markup=get_main_menu_keyboard())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not ocr.enabled:
        await update.message.reply_text("Maaf, fitur baca struk (OCR) sedang dinonaktifkan di server untuk menghemat memori. Kamu bisa catat manual ya!")
        return

    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"temp_{user_id}.jpg"
    await photo_file.download_to_drive(file_path)
    
    processing_msg = await update.message.reply_text("Sedang memproses struk... ⏳")
    
    try:
        ocr_result = ocr.process_receipt(file_path)
        if isinstance(ocr_result, dict):
            amount = ocr_result.get('amount', 0)
            merchant = ocr_result.get('merchant', 'Struk Belanja')
            date_str = ocr_result.get('date', datetime.now().strftime("%Y-%m-%d"))
        else:
            amount = ocr_result if ocr_result else 0
            merchant = 'Struk Belanja'
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        if amount > 0:
            category = nlp._detect_category(merchant)
            if category == "Lain-lain":
                category = "Belanja"
            
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
