from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, premium_ai, ws_server, nlp, ocr
import logging
import asyncio
from datetime import datetime
import os

logger = logging.getLogger(__name__)

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
    if os.path.exists(voice_path):
        os.remove(voice_path) # Clean up
    
    if not text:
        await update.message.reply_text("Maaf, aku gagal denger suara kamu. Coba kirim lagi ya!")
        return

    await update.message.reply_text(f"🎤 **Kamu bilang:** \"{text}\"\n\n_Sedang memproses..._")
    
    # 2. Process transcribed text through existing Elite AI logic
    # Reuse handle_message logic but with the transcribed text
    update.message.text = text
    await handle_message(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt scanning via OCR"""
    user_id = update.effective_user.id
    photo = await update.message.photo[-1].get_file()
    photo_path = f"temp_receipt_{user_id}.jpg"
    await photo.download_to_drive(photo_path)
    
    await update.message.reply_text("📸 **Sedang memindai struk...**", parse_mode='Markdown')
    
    try:
        # 1. OCR Extraction
        result = ocr.process_receipt(photo_path)
        if os.path.exists(photo_path):
            os.remove(photo_path)
            
        if not result:
            await update.message.reply_text("Gagal membaca struk. Pastikan foto jelas ya!")
            return

        merchant = result.get('merchant', 'Transaksi')
        amount = result.get('amount', 0)
        
        # Construct natural language text for AI processing
        text = f"Beli {merchant} seharga {amount}"

        # 2. AI Parsing
        await update.message.reply_text(f"🔍 **Data Terbaca:**\n{merchant}: {amount}\n\n_Menganalisis detail..._")
        
        # Reuse handle_message logic
        update.message.text = text
        await handle_message(update, context)
        
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await update.message.reply_text("Terjadi kesalahan saat memproses foto.")
        if os.path.exists(photo_path):
            os.remove(photo_path)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text
    
    logger.info(f"Processing message from {user_id} ({user_name}): {text[:50]}...")
    
    # [CRITICAL FIX] Ensure user exists in database before any transaction
    try:
        user_db = db.get_or_create_user(user_id, update.effective_user.username)
    except Exception as e:
        logger.error(f"Failed to ensure user exists: {e}")
        await update.message.reply_text("Maaf, ada masalah koneksi database saat mendaftarkan akunmu. Coba lagi ya!")
        return

    try:
        # 1. Premium Autonomous Intent & Context Engine
        premium_response = await premium_ai.process_interaction(user_id, text, user_name)
        intent = premium_response.intent
        
        # 2. Advanced Decision Engine with Smart Reconciliation
        response_msg = premium_response.suggested_response
        
        if intent == "record" and premium_response.structured_data:
            data = premium_response.structured_data
            amount = data.get("amount", 0)
            
            # [SAFETY] Ignore zero or negative transactions unless explicitly handled
            if amount <= 0:
                logger.warning(f"Skipping transaction with amount {amount} for user {user_id}")
                response_msg = premium_response.suggested_response or "Hmm, nominalnya berapa ya kak? Aku belum nangkep nih. 🤔"
            else:
                try:
                    # [NEW] Check for Duplicates
                    is_duplicate = await premium_ai.check_reconciliation(user_id, data)
                    if is_duplicate:
                        response_msg = "⚠️ **Potensi Duplikat Terdeteksi!**\nTransaksi serupa baru saja dicatat. Yakin mau simpan lagi?"
                    else:
                        db.add_transaction(
                            user_id=user_db.id, # Use DB Primary Key, NOT Telegram ID
                            amount=amount,
                            category=data.get("category", "Lain-lain"),
                            description=data.get("description", text),
                            trans_type=data.get("type", "expense")
                        )
                        response_msg = premium_response.suggested_response
                except Exception as e:
                    logger.error(f"Error saving transaction for {user_id}: {e}", exc_info=True)
                    response_msg = "Maaf, saya gagal menyimpan transaksi tersebut. Silakan coba lagi."

        elif intent == "insight":
            response_msg = premium_response.predictive_advice or premium_response.suggested_response

        # 3. Real-time Multi-channel Broadcast & Gamification
        if premium_response.needs_live_update:
            try:
                # [NEW] Add XP for interaction
                from core import gamify
                xp_status = await gamify.add_xp(user_id, "transaction" if intent == "record" else "insight")
                
                if xp_status.get("leveled_up"):
                    level = xp_status.get("current_level")
                    title = xp_status.get("title")
                    response_msg += f"\n\n🎉 **LEVEL UP!**\nSelamat! Kamu naik ke Level {level}: **{title}** 🏆"
                
                if ws_server.loop and ws_server.loop.is_running():
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
            except Exception as ws_err:
                logger.warning(f"Gamification/WS Broadcast failed for {user_id}: {ws_err}")

        await update.message.reply_text(response_msg, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Critical error in handle_message for {user_id}: {e}", exc_info=True)
        error_msg = "Waduh, ada kendala teknis nih. 🛠️\nTim kami sudah diberitahu. Coba lagi sebentar lagi ya!"
        await update.message.reply_text(error_msg)
