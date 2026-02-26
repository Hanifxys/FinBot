from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, premium_ai, ws_server, nlp
import logging
import asyncio
from datetime import datetime

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium: Handle Voice Notes using Groq Whisper"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    voice = await update.message.voice.get_file()
    voice_path = f"temp_voice_{user_id}.ogg"
    await voice.download_to_drive(voice_path)
    
    # 1. Transcribe via Premium AI (Whisper)
    text = await premium_ai.transcribe_voice(voice_path)
    os.remove(voice_path) # Clean up
    
    if not text:
        await update.message.reply_text("Maaf, aku gagal denger suara kamu. Coba kirim lagi ya!")
        return

    await update.message.reply_text(f"🎤 **Kamu bilang:** \"{text}\"\n\n_Sedang memproses..._")
    
    # 2. Process transcribed text through existing Elite AI logic
    # Reuse handle_message logic but with the transcribed text
    update.message.text = text
    await handle_message(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text
    
    # 1. Premium Autonomous Intent & Context Engine
    premium_response = await premium_ai.process_interaction(user_id, text, user_name)
    intent = premium_response.intent
    
    # 2. Advanced Decision Engine with Smart Reconciliation
    if intent == "record" and premium_response.structured_data:
        data = premium_response.structured_data
        
        # [NEW] Check for Duplicates
        is_duplicate = await premium_ai.check_reconciliation(user_id, data)
        if is_duplicate:
            response_msg = "⚠️ **Potensi Duplikat Terdeteksi!**\nTransaksi serupa baru saja dicatat. Yakin mau simpan lagi?"
            # Add inline button for confirmation if needed
        else:
            db.add_transaction(
                user_id=user_id,
                amount=data.get("amount", 0),
                category=data.get("category", "Lain-lain"),
                description=data.get("description", text),
                trans_type=data.get("type", "expense")
            )
            response_msg = premium_response.suggested_response
    elif intent == "insight":
        response_msg = premium_response.predictive_advice or premium_response.suggested_response
    else:
        response_msg = premium_response.suggested_response

    # 3. Real-time Multi-channel Broadcast
    if premium_response.needs_live_update:
        # [NEW] Add XP for interaction
        from core import gamify
        xp_status = await gamify.add_xp(user_id, "transaction" if intent == "record" else "insight")
        
        asyncio.run_coroutine_threadsafe(
            ws_server.broadcast_to_user(
                user_id=user_id,
                message={
                    "event": "premium_ai_insight",
                    "data": {
                        "text": text,
                        "sentiment": premium_response.sentiment,
                        "language": premium_response.language,
                        "response": response_msg,
                        "advice": premium_response.predictive_advice,
                        "gamify": xp_status
                    }
                }
            ),
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
