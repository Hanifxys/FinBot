from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, premium_ai, ws_server, nlp, ocr
import logging
import asyncio
from datetime import datetime
import os
import gc

logger = logging.getLogger(__name__)

OCR_MAX_DOWNLOAD_BYTES = int(os.getenv("OCR_MAX_DOWNLOAD_BYTES", "1200000"))
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "1"))
OCR_SEMAPHORE = asyncio.Semaphore(max(OCR_CONCURRENCY, 1))
OCR_MAX_MEMORY_PERCENT = float(os.getenv("OCR_MAX_MEMORY_PERCENT", "80"))
CANCEL_CANDIDATE_LIMIT = int(os.getenv("CANCEL_CANDIDATE_LIMIT", "30"))

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

def _format_tx(tx) -> str:
    try:
        date_str = tx.date.strftime("%d/%m %H:%M")
    except Exception:
        date_str = str(getattr(tx, "date", ""))
    desc = (getattr(tx, "description", None) or "-").strip()
    if len(desc) > 80:
        desc = desc[:77] + "..."
    ttype = getattr(tx, "type", "")
    icon = "🔻" if ttype == "expense" else "🔹"
    return f"{icon} `#{tx.id}` | {date_str} | {tx.category} | **Rp{tx.amount:,.0f}**\n_{desc}_"

def _parse_amount_hint(text: str):
    import re
    t = (text or "").lower()
    t = t.replace("rp", "").replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta)?", t)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        val = float(raw)
    except Exception:
        return None
    suf = m.group(2) or ""
    if suf in ("rb", "ribu", "k"):
        val *= 1000
    elif suf in ("jt", "juta"):
        val *= 1000000
    if val <= 0:
        return None
    return float(val)

def _score_cancel_candidate(tx, amount_hint=None, merchant_hint=None, text_hint=None):
    score = 0.0
    try:
        if amount_hint is not None and abs(float(tx.amount) - float(amount_hint)) <= 1.0:
            score += 10.0
        elif amount_hint is not None and abs(float(tx.amount) - float(amount_hint)) <= 1000.0:
            score += 5.0
    except Exception:
        pass

    desc = (getattr(tx, "description", "") or "").lower()
    cat = (getattr(tx, "category", "") or "").lower()
    mh = (merchant_hint or "").lower().strip()
    th = (text_hint or "").lower().strip()
    if mh and (mh in desc or mh in cat):
        score += 6.0
    if th:
        for token in [w for w in th.split() if len(w) >= 4][:5]:
            if token in desc or token in cat:
                score += 2.0
    return score

async def _send_cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, structured: dict, raw_text: str):
    user_id = update.effective_user.id
    tx_id = structured.get("transaction_id")
    try:
        tx_id = int(tx_id) if tx_id is not None else None
    except Exception:
        tx_id = None

    amount_hint = structured.get("amount_hint")
    try:
        amount_hint = float(amount_hint) if amount_hint is not None else None
    except Exception:
        amount_hint = None
    if amount_hint is None:
        amount_hint = _parse_amount_hint(raw_text)

    merchant_hint = structured.get("merchant_hint") or ""
    reason = structured.get("reason") or raw_text
    cancel_action = structured.get("cancel_action") or "delete_by_hint"

    txs = db.get_transactions_history(user_db.id, limit=CANCEL_CANDIDATE_LIMIT)
    if not txs:
        await update.message.reply_text("Belum ada transaksi yang bisa dibatalkan.")
        return

    selected = None
    candidates = []
    if tx_id is not None:
        for tx in txs:
            if getattr(tx, "id", None) == tx_id:
                selected = tx
                break
    if selected is None and cancel_action == "undo_last":
        selected = txs[0]
    if selected is None:
        for tx in txs:
            score = _score_cancel_candidate(tx, amount_hint=amount_hint, merchant_hint=merchant_hint, text_hint=raw_text)
            candidates.append((score, tx))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates and candidates[0][0] > 0:
            selected = candidates[0][1]
    if selected is None:
        selected = txs[0]

    top = []
    seen = set()
    if candidates:
        for score, tx in candidates[:5]:
            if getattr(tx, "id", None) not in seen:
                seen.add(getattr(tx, "id", None))
                top.append(tx)
    if not top:
        top = txs[:5]

    context.user_data["pending_cancel"] = {
        "selected_id": getattr(selected, "id", None),
        "reason": reason,
        "amount_hint": amount_hint,
        "merchant_hint": merchant_hint,
        "candidates": [
            {
                "id": getattr(tx, "id", None),
                "amount": float(getattr(tx, "amount", 0) or 0),
                "category": getattr(tx, "category", ""),
                "description": getattr(tx, "description", None),
            }
            for tx in top
        ],
        "eta_seconds": 60,
    }

    msg = (
        "🧾 **Deteksi pembatalan transaksi**\n\n"
        "Aku tangkap kamu mau membatalkan transaksi ini:\n\n"
        f"{_format_tx(selected)}\n\n"
        f"⏱️ Estimasi refund: ≤ {context.user_data['pending_cancel']['eta_seconds']} detik\n"
        "Sebelum lanjut, mau aku tawarkan opsi lain dulu?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Batalkan (1-klik)", callback_data="cancel_confirm"),
            InlineKeyboardButton("🔁 Pilih lain", callback_data="cancel_choose"),
        ],
        [
            InlineKeyboardButton("📜 Riwayat", callback_data="open_history"),
            InlineKeyboardButton("❌ Tidak jadi", callback_data="cancel_abort"),
        ],
    ]
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    logger.info(f"Processing message from {user_id} ({user_name}): {text[:50]}...")
    
    try:
        user_db = db.get_or_create_user(user_id, update.effective_user.username)
    except Exception as e:
        logger.error(f"Failed to ensure user exists: {e}")
        await update.message.reply_text("Maaf, ada masalah koneksi database saat mendaftarkan akunmu. Coba lagi ya!")
        return

    try:
        premium_response = await premium_ai.process_interaction(user_id, text, user_name)
        intent = premium_response.intent
        
        response_msg = premium_response.suggested_response
        if intent == "cancel":
            structured = premium_response.structured_data or {}
            await _send_cancel_flow(update, context, user_db, structured, text)
            return
        
        if intent == "record" and premium_response.structured_data:
            data = premium_response.structured_data
            amount = data.get("amount", 0)
            
            if amount <= 0:
                logger.warning(f"Skipping transaction with amount {amount} for user {user_id}")
                response_msg = premium_response.suggested_response or "Hmm, nominalnya berapa ya kak? Aku belum nangkep nih. 🤔"
            else:
                try:
                    is_duplicate = await premium_ai.check_reconciliation(user_id, data)
                    if is_duplicate:
                        response_msg = "⚠️ **Potensi Duplikat Terdeteksi!**\nTransaksi serupa baru saja dicatat. Yakin mau simpan lagi?"
                    else:
                        db.add_transaction(
                            user_id=user_db.id,
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

        if premium_response.needs_live_update:
            try:
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
    await _process_text(update, context, text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt scanning via OCR"""
    user_id = update.effective_user.id
    photo_sizes = update.message.photo or []
    if not photo_sizes:
        await update.message.reply_text("Aku nggak nemu foto-nya. Coba kirim ulang ya.")
        return

    low_mem = False
    try:
        import psutil
        mem = psutil.virtual_memory()
        if float(mem.percent) >= OCR_MAX_MEMORY_PERCENT:
            low_mem = True
    except Exception:
        pass

    chosen = None
    for p in reversed(photo_sizes):
        if (getattr(p, "file_size", None) or 0) <= OCR_MAX_DOWNLOAD_BYTES:
            chosen = p
            break
        if max(getattr(p, "width", 0) or 0, getattr(p, "height", 0) or 0) <= 1280:
            chosen = p
            break
    if chosen is None:
        chosen = photo_sizes[max(len(photo_sizes) - 2, 0)]

    photo = await chosen.get_file()
    photo_path = f"temp_receipt_{user_id}.jpg"
    await photo.download_to_drive(photo_path)
    
    await update.message.reply_text("📸 **Sedang memindai struk...**", parse_mode='Markdown')
    
    try:
        # 1. OCR Extraction
        async with OCR_SEMAPHORE:
            result = await asyncio.to_thread(ocr.process_receipt, photo_path, low_mem)
            
        if not result:
            await update.message.reply_text("Gagal membaca struk. Pastikan foto jelas ya!")
            return

        merchant = result.get('merchant', 'Transaksi')
        amount = result.get('amount', 0)
        
        # Construct natural language text for AI processing
        text = f"Beli {merchant} seharga {amount}"

        # 2. AI Parsing
        await update.message.reply_text(f"🔍 **Data Terbaca:**\n{merchant}: {amount}\n\n_Menganalisis detail..._")
        
        await _process_text(update, context, text)
        
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await update.message.reply_text("Terjadi kesalahan saat memproses foto.")
    finally:
        if os.path.exists(photo_path):
            os.remove(photo_path)
        gc.collect()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await _process_text(update, context, text)
