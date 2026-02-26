from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, ai, ws_server, nlp
import logging
import asyncio
from datetime import datetime

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # 1. Autonomous Intent Detection (No commands needed)
    intent_data = ai.detect_autonomous_intent(text)
    intent = intent_data.get("intent")
    
    # 2. Process based on Autonomous Intent
    if intent == "record" and intent_data.get("structured_data"):
        data = intent_data["structured_data"]
        user_db = db.get_or_create_user(user_id, update.effective_user.username)
        db.add_transaction(
            user_id=user_db.id,
            amount=data.get("amount", 0),
            category=data.get("category", "Lain-lain"),
            description=data.get("description", text),
            trans_type=data.get("type", "expense")
        )
        response_msg = intent_data.get("suggested_response", "✅ Transaksi dicatat!")
    elif intent == "query_budget":
        response_msg = intent_data.get("suggested_response", "Cek budget di dashboard ya!")
    else:
        # Fallback to smart chat
        response_msg = intent_data.get("suggested_response", "Aku dengerin, ada yang bisa kubantu?")

    # 3. Real-time WebSocket Interaction
    if intent_data.get("needs_live_update"):
        asyncio.run_coroutine_threadsafe(
            ws_server.broadcast({
                "event": "ai_interaction",
                "data": {
                    "user_text": text,
                    "bot_intent": intent,
                    "response": response_msg
                }
            }),
            ws_server.loop
        )

    await update.message.reply_text(response_msg, parse_mode='Markdown')

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
