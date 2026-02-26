import logging
import asyncio
import os
import gc
import time
import json
import hashlib
import psutil
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, Tuple

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)
from telegram.ext import ContextTypes

# Core Modules
from core import db, premium_ai, ws_server, nlp, ocr, budget_mgr, analyzer
from config import CATEGORIES

# Handlers & Utils
from handlers import tutorial_mode
from handlers.transactions import export_data
from handlers.commands import set_persona_command, reminder_settings, summary_command
from handlers.finance import what_if_simulator, set_gaji, set_budget, set_budget_alerts
from modules.amounts import parse_primary_amount_id

# --- Configuration ---
class Config:
    OCR_MAX_DOWNLOAD_BYTES = int(os.getenv("OCR_MAX_DOWNLOAD_BYTES", "1200000"))
    OCR_RATE_LIMIT_SECONDS = int(os.getenv("OCR_RATE_LIMIT_SECONDS", "60"))
    OCR_HANDLER_TIMEOUT_SECONDS = float(os.getenv("OCR_HANDLER_TIMEOUT_SECONDS", "55"))
    OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "1"))
    OCR_MAX_MEMORY_PERCENT = float(os.getenv("OCR_MAX_MEMORY_PERCENT", "80"))
    CANCEL_CANDIDATE_LIMIT = int(os.getenv("CANCEL_CANDIDATE_LIMIT", "30"))
    AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "25"))
    TUTORIAL_TIMEOUT_SECONDS = int(os.getenv("TUTORIAL_TIMEOUT_SECONDS", "900"))
    TUTORIAL_TOTAL_STEPS = 5

logger = logging.getLogger(__name__)

# Global Semaphore for OCR Concurrency Control
OCR_SEMAPHORE = asyncio.Semaphore(max(Config.OCR_CONCURRENCY, 1))


# --- UI Helpers ---

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main menu reply keyboard."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

def _tx_preview_keyboard() -> InlineKeyboardMarkup:
    """Returns inline keyboard for transaction preview actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Simpan", callback_data="tx_confirm"),
            InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
        ],
        [
            InlineKeyboardButton("❌ Batal", callback_data="tx_ignore"),
        ],
    ])

def _format_tx(tx) -> str:
    """Formats a transaction object into a readable string."""
    try:
        date_val = getattr(tx, "date", "")
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%d/%m %H:%M")
        else:
            date_str = str(date_val)
    except Exception:
        date_str = "-"

    desc = (getattr(tx, "description", None) or "-").strip()
    if len(desc) > 80:
        desc = desc[:77] + "..."
    
    ttype = getattr(tx, "type", "")
    icon = "🔻" if ttype == "expense" else "🔹"
    amount = getattr(tx, "amount", 0)
    category = getattr(tx, "category", "-")
    tx_id = getattr(tx, "id", "?")
    
    return f"{icon} `#{tx_id}` | {date_str} | {category} | **Rp{amount:,.0f}**\n_{desc}_"

def _tx_preview_message(pending: dict, feedback: str = "") -> str:
    """Formats a pending transaction preview message with optional feedback."""
    amount = pending.get("amount", 0) or 0
    category = pending.get("category") or "Lain-lain"
    merchant = pending.get("merchant") or pending.get("description") or "Transaksi"
    payment = pending.get("payment_method") or "-"
    date = pending.get("date") or datetime.now().strftime("%d-%m-%Y")
    
    msg = (
        "🧾 **Preview Transaksi**\n\n"
        f"• Item: **{merchant}**\n"
        f"• Nominal: **Rp{float(amount):,.0f}**\n"
        f"• Kategori: **{category}**\n"
        f"• Metode: **{payment}**\n"
        f"• Tanggal: **{date}**\n"
    )
    
    if feedback:
        msg += f"\n💡 {feedback}\n"
        
    msg += "\nLanjut simpan atau edit dulu?"
    return msg

# --- Logic Helpers ---

def _parse_amount_hint(text: str) -> Optional[float]:
    return parse_primary_amount_id(text)

def _looks_like_payment_method(text: str) -> str:
    t = (text or "").lower()
    methods = {
        "qris": "QRIS", "cash": "Cash", "tunai": "Cash", "debit": "Debit",
        "kredit": "Kredit", "credit": "Kredit", "ovo": "OVO", "gopay": "GoPay",
        "go pay": "GoPay", "dana": "DANA", "shopeepay": "ShopeePay",
        "shopee pay": "ShopeePay", "transfer": "Transfer"
    }
    for key, val in methods.items():
        if key in t:
            return val
    return ""

def _looks_like_explain_spending(text: str) -> bool:
    t = (text or "").lower()
    keys = ["diatas rata", "di atas rata", "rata2", "rata-rata", "datanya dari mana", "data nya dari mana", "dari mana", "overspending", "boros"]
    return any(k in t for k in keys)

def _score_cancel_candidate(tx, amount_hint=None, merchant_hint=None, text_hint=None) -> float:
    """Scores a transaction to determine if it matches the cancellation request."""
    score = 0.0
    try:
        if amount_hint is not None:
            tx_amount = float(getattr(tx, "amount", 0))
            if abs(tx_amount - float(amount_hint)) <= 1.0:
                score += 10.0
            elif abs(tx_amount - float(amount_hint)) <= 1000.0:
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
        # Check for matching tokens in description
        tokens = [w for w in th.split() if len(w) >= 4]
        for token in tokens[:5]:
            if token in desc or token in cat:
                score += 2.0
                
    return score

# --- Feature Handlers ---

async def _roast_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Viral Feature: Roast My Wallet"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    await update.message.reply_text("🔥 **Sedang menyiapkan bahan roasting...**", parse_mode='Markdown')
    
    try:
        txs = db.get_sliding_window_transactions(user_id, days=30)
        if not txs:
            await update.message.reply_text("Dompetmu terlalu bersih untuk di-roast. Catat dulu sana!")
            return
            
        total = sum(t.amount for t in txs if t.type == 'expense')
        categories = {}
        for t in txs:
            if t.type == 'expense':
                categories[t.category] = categories.get(t.category, 0) + t.amount
        
        top_cat = max(categories, key=categories.get) if categories else "Nothing"
        
        prompt = f"""
        Roast this user's spending habits! Be savage, funny, and viral-worthy.
        User: {user_name}
        Total Spending (30 days): Rp {total:,.0f}
        Top Category: {top_cat} (Rp {categories.get(top_cat, 0):,.0f})
        Habits: {len(txs)} transactions recorded.
        
        Output format:
        Title: 💀 DOMPET ATAU KUBURAN?
        Roast: [Your savage commentary here, max 100 words]
        Rating: [Give a score like 'Boros Level: Firaun']
        """
        
        roast = await premium_ai._call_llm(
            system_prompt="You are a stand-up comedian roasting bad financial habits. Use Indonesian slang.",
            user_prompt=prompt,
            model=premium_ai.FAST_MODEL
        )
        
        await update.message.reply_text(roast or "Gagal roasting. AI-nya lagi gak tega.", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Roast error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Gagal roasting. AI-nya lagi gak tega.")

async def _explain_spending(update: Update):
    """Explains why spending is above/below average."""
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    now = datetime.now()
    
    try:
        txs = db.get_sliding_window_transactions(user_db.id, days=7)
    except Exception:
        txs = db.get_monthly_report(user_db.id, now.month, now.year)

    expenses = [t for t in (txs or []) if getattr(t, "type", "") == "expense"]
    if not expenses:
        await update.message.reply_text("Belum ada cukup data untuk bandingin rata-rata. Coba catat 3-5 transaksi dulu ya.")
        return

    by_day = {}
    for t in expenses:
        d = getattr(t, "date", None)
        key = d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
        by_day[key] = by_day.get(key, 0) + float(getattr(t, "amount", 0) or 0)

    days = max(1, len(by_day))
    avg = sum(by_day.values()) / days
    today_key = now.date().isoformat()
    today_total = float(by_day.get(today_key, 0))
    delta = today_total - avg
    status = "di atas" if delta > 0 else "di bawah"

    msg = (
        "📌 **Penjelasan 'di atas rata-rata'**\n\n"
        f"• Data: total pengeluaran per hari (window {days} hari terakhir)\n"
        f"• Rata-rata harian: **Rp{avg:,.0f}**\n"
        f"• Hari ini: **Rp{today_total:,.0f}**\n"
        f"• Selisih: **Rp{abs(delta):,.0f}** ({status} rata-rata)\n\n"
        "Kalau kamu mau, aku bisa breakdown kategori paling besar hari ini."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def _send_cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, structured: dict, raw_text: str):
    """Initiates the transaction cancellation flow."""
    user_id = update.effective_user.id
    
    # Parse parameters
    tx_id = structured.get("transaction_id")
    try:
        tx_id = int(tx_id) if tx_id is not None else None
    except (ValueError, TypeError):
        tx_id = None

    amount_hint = structured.get("amount_hint")
    try:
        amount_hint = float(amount_hint) if amount_hint is not None else None
    except (ValueError, TypeError):
        amount_hint = None
    
    if amount_hint is None:
        amount_hint = _parse_amount_hint(raw_text)

    merchant_hint = structured.get("merchant_hint") or ""
    reason = structured.get("reason") or raw_text
    cancel_action = structured.get("cancel_action") or "delete_by_hint"

    # Fetch candidates
    txs = db.get_transactions_history(user_db.id, limit=Config.CANCEL_CANDIDATE_LIMIT)
    if not txs:
        await update.message.reply_text("Belum ada transaksi yang bisa dibatalkan.")
        return

    selected = None
    candidates = []
    
    # Strategy 1: Match by ID
    if tx_id is not None:
        for tx in txs:
            if getattr(tx, "id", None) == tx_id:
                selected = tx
                break
                
    # Strategy 2: Undo Last
    if selected is None and cancel_action == "undo_last":
        selected = txs[0]
        
    # Strategy 3: Heuristic Scoring
    if selected is None:
        for tx in txs:
            score = _score_cancel_candidate(tx, amount_hint=amount_hint, merchant_hint=merchant_hint, text_hint=raw_text)
            candidates.append((score, tx))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates and candidates[0][0] > 0:
            selected = candidates[0][1]
            
    # Fallback: Most recent
    if selected is None:
        selected = txs[0]

    # Prepare Top Candidates for UI
    top = []
    seen = set()
    if candidates:
        for _, tx in candidates[:5]:
            tid = getattr(tx, "id", None)
            if tid not in seen:
                seen.add(tid)
                top.append(tx)
    if not top:
        top = txs[:5]

    # Store State
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

# --- Main Handlers ---

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium: Handle Voice Notes using Groq Whisper"""
    user_id = update.effective_user.id
    voice_path = f"temp_voice_{user_id}.ogg"
    
    try:
        voice = await update.message.voice.get_file()
        await voice.download_to_drive(voice_path)
        
        # Transcribe via Premium AI (Whisper)
        text = await premium_ai.transcribe_voice(voice_path)
        
        if not text:
            await update.message.reply_text("Maaf, aku gagal denger suara kamu. Coba kirim lagi ya!")
            return

        await update.message.reply_text(f"🎤 **Kamu bilang:** \"{text}\"\n\n_Sedang memproses..._", parse_mode='Markdown')
        
        # Process transcribed text
        await _process_text(update, context, text)
        
    except Exception as e:
        logger.error(f"Voice handling error for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Gagal memproses pesan suara.")
    finally:
        if os.path.exists(voice_path):
            try:
                os.remove(voice_path)
            except OSError:
                pass

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt scanning via OCR"""
    user_id = update.effective_user.id
    photo_sizes = update.message.photo or []
    if not photo_sizes:
        await update.message.reply_text("Aku nggak nemu foto-nya. Coba kirim ulang ya.")
        return

    # Memory Check
    try:
        mem = psutil.virtual_memory()
        low_mem = float(mem.percent) >= Config.OCR_MAX_MEMORY_PERCENT
    except Exception:
        low_mem = False

    # Select optimal photo size
    chosen = None
    for p in reversed(photo_sizes):
        if (getattr(p, "file_size", None) or 0) <= Config.OCR_MAX_DOWNLOAD_BYTES:
            chosen = p
            break
        if max(getattr(p, "width", 0) or 0, getattr(p, "height", 0) or 0) <= 1280:
            chosen = p
            break
    if chosen is None:
        chosen = photo_sizes[max(len(photo_sizes) - 2, 0)]

    photo_path = f"temp_receipt_{user_id}.jpg"
    
    try:
        photo = await chosen.get_file()
        await photo.download_to_drive(photo_path)
        
        await update.message.reply_text("📸 **Sedang memindai struk...**", parse_mode='Markdown')
        
        # Rate Limiting
        key = f"ocr_rl:{user_id}"
        if premium_ai.redis.client:
            ok = premium_ai.redis.client.set(key, str(int(time.time())), ex=Config.OCR_RATE_LIMIT_SECONDS, nx=True)
            if not ok:
                await update.message.reply_text(f"OCR lagi cooldown. Coba lagi dalam {Config.OCR_RATE_LIMIT_SECONDS} detik ya.")
                return

        # OCR Extraction
        result = None
        async with OCR_SEMAPHORE:
            try:
                with open(photo_path, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                cache_key = f"ocr_cache:{h}"
                
                cached = None
                if premium_ai.redis.client:
                    cached = premium_ai.redis.client.get(cache_key)
                
                if cached:
                    result = json.loads(cached)
                else:
                    # Run OCR in thread pool to avoid blocking event loop
                    result = await asyncio.wait_for(
                        asyncio.to_thread(ocr.process_receipt, photo_path, low_mem),
                        timeout=Config.OCR_HANDLER_TIMEOUT_SECONDS
                    )
                    if result and premium_ai.redis.client:
                        premium_ai.redis.client.set(cache_key, json.dumps(result), ex=7 * 24 * 3600)
            except asyncio.TimeoutError:
                await update.message.reply_text("OCR timeout. Server lagi sibuk, coba text aja ya.")
                return
            except Exception as e:
                logger.error(f"OCR Internal Error: {e}")
            
        if not result:
            await update.message.reply_text("Gagal membaca struk. Pastikan foto jelas ya!")
            return

        merchant = result.get('merchant', 'Transaksi')
        amount = result.get('amount', 0)
        
        # Construct natural language text for AI processing
        text = f"Beli {merchant} seharga {amount}"

        await update.message.reply_text(f"🔍 **Data Terbaca:**\n{merchant}: {amount}\n\n_Menganalisis detail..._", parse_mode='Markdown')
        await _process_text(update, context, text)
        
    except Exception as e:
        logger.error(f"OCR Error for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Terjadi kesalahan saat memproses foto.")
    finally:
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass
        gc.collect()

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles document uploads for summarization."""
    user_id = update.effective_user.id
    doc = update.message.document
    if not doc:
        return

    # Limit file size (e.g., 10MB)
    if (doc.file_size or 0) > 10 * 1024 * 1024:
        await update.message.reply_text("Ukuran file terlalu besar (maks 10MB).")
        return

    await update.message.reply_text("📄 **Menganalisis dokumen...**", parse_mode='Markdown')

    file_path = f"temp_doc_{user_id}_{doc.file_name}"
    try:
        f = await doc.get_file()
        await f.download_to_drive(file_path)
        
        with open(file_path, "rb") as file_obj:
            content = file_obj.read()
            
        summary = await premium_ai.process_document(user_id, content, doc.file_name, doc.mime_type or "")
        
        await update.message.reply_text(f"📑 **Ringkasan Dokumen**\n\n{summary}", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Document Error for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Gagal memproses dokumen.")
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point for text messages."""
    text = update.message.text
    if text:
        await _process_text(update, context, text)

# --- Core Text Processing Logic ---

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
        # 1. NLP Hybrid Classification
        # Use state to give context (e.g. if waiting for edit)
        current_state = context.user_data.get("state", "IDLE")
        
        # New: Use Hybrid Classify instead of just regex
        classification = nlp.hybrid_classify(text, state=current_state)
        intent = classification.get("intent")
        confidence = classification.get("confidence", 0.0)

        # 2. Dispatch Based on Intent
        if intent == "STOP_NOTIF":
             await update.message.reply_text("Siap! Aku bakal kurangi frekuensi daily digest kamu. Pengaturan notifikasi bisa kamu atur lebih detail di `/settings` ya.")
             return

        if intent == "CANCEL":
             # This is handled inside _handle_pending_states usually, but explicit intent is safer
             context.user_data.pop("state", None)
             context.user_data.pop("pending_tx", None)
             await update.message.reply_text("Oke, dibatalkan ya.")
             return

        if intent == "ROAST_WALLET":
            await _roast_wallet(update, context)
            return

        if intent == "EXPORT_DATA":
            await export_data(update, context)
            return

        if intent == "WHAT_IF":
            amount = nlp._extract_amount(text)
            if amount > 0:
                import re
                clean = re.sub(r'\b(what if|simulasi|kalo|misal|kalau|andai|seandainya|beli)\b', '', text, flags=re.IGNORECASE)
                context.args = [str(int(amount)), clean.strip()]
                await what_if_simulator(update, context)
            else:
                await update.message.reply_text("Contoh: 'kalo beli hp 5jt' atau 'simulasi cicilan motor 1jt'")
            return

        if intent == "SET_MODE":
            context.args = [classification.get("value")]
            await set_persona_command(update, context)
            return
            
        if intent == "SET_REMINDER":
            context.args = [classification.get("value")]
            await reminder_settings(update, context)
            return

        if intent == "CHECK_BUDGET":
            msg = budget_mgr.check_budget_status(user_db.id)
            drift_alerts = analyzer.detect_budget_drift(user_db.id)
            if drift_alerts:
                msg += "\n\n⚠️ **Early Warning System (Budget Drift)**\n"
                for alert in drift_alerts:
                    msg += f"- {alert}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return

        if intent == "SET_GAJI":
            amount = nlp._extract_amount(text)
            if amount > 0:
                context.args = [str(int(amount))]
                await set_gaji(update, context)
            else:
                await update.message.reply_text("Gajinya berapa? Contoh: 'set gaji 10jt'")
            return

        if intent == "SET_BUDGET":
            amount = nlp._extract_amount(text)
            category = nlp._detect_category(text)
            if amount > 0 and category != "Lain-lain":
                context.args = [category, str(int(amount))]
                await set_budget(update, context)
            elif amount > 0:
                 await update.message.reply_text("Budget untuk kategori apa? Contoh: 'set budget makan 1jt'")
            else:
                 await update.message.reply_text("Nominalnya berapa? Contoh: 'set budget makan 1jt'")
            return

        if intent == "SET_BUDGET_ALERT":
            category = nlp._detect_category(text)
            import re
            pcts = re.findall(r'(\d+)%', text)
            if not pcts:
                 pcts = re.findall(r'(\d+)\s*persen', text)
            if category != "Lain-lain" and pcts:
                warn = pcts[0]
                limit = pcts[1] if len(pcts) > 1 else "100"
                context.args = [category, warn, limit]
                await set_budget_alerts(update, context)
            else:
                await update.message.reply_text("Contoh: 'ingetin budget makan kalo udah 80%'")
            return

        if intent == "QUERY_SUMMARY" or intent == "get_report": 
             await summary_command(update, context)
             return

        if intent == "SHARING_INFO":
            await _handle_sharing_info(update, context, user_db, text, user_name)
            return
            
        if intent == "GREETING":
            await _handle_sharing_info(update, context, user_db, text, user_name)
            return

        # 3. Handle Pending States (Edit Flows)
        if await _handle_pending_states(update, context, text):
            return

        # 4. Check for Transaction (ADD_TRANSACTION)
        if intent == "ADD_TRANSACTION":
             # Use the new extraction logic
             tx_data = nlp.extract_transaction_data(text)
             if tx_data.get("amount"):
                 # Wrap into structure expected by _handle_record_intent or handle it directly
                 # Let's reuse _handle_record_intent logic but construct a mock premium response
                 # to keep code DRY, or just inline the logic.
                 
                 # Prepare Pending Transaction
                 pending = {
                    "amount": float(tx_data["amount"]),
                    "category": tx_data["category"] or "Lain-lain",
                    "merchant": tx_data["merchant"] or "Transaksi",
                    "date": datetime.now().strftime("%d-%m-%Y"),
                    "payment_method": None,
                 }
                 
                 # Contextual Insight
                 feedback = ""
                 try:
                    feedback = analyzer.get_instant_feedback(
                        user_id, pending["category"], pending["merchant"], pending["amount"]
                    )
                 except Exception: pass

                 context.user_data["pending_tx"] = pending
                 context.user_data.pop("state", None)
                 
                 await update.message.reply_text(
                    _tx_preview_message(pending, feedback), 
                    parse_mode="Markdown", 
                    reply_markup=_tx_preview_keyboard()
                 )
                 return

        # 5. Check other manual heuristics (Fallback)
        if _looks_like_explain_spending(text):
            await _explain_spending(update)
            return

        if await tutorial_mode.handle_text(update, context, text):
            return

        if tutorial_mode.is_tutorial_request(text):
            await update.message.reply_text(tutorial_mode.intro_text(), parse_mode="Markdown", reply_markup=tutorial_mode.intro_keyboard())
            return

        # 6. Fallback to Premium AI (LLM) if Intent is UNKNOWN but has text
        # This catches complex queries that regex missed but LLM might handle as general conversation
        await _process_with_premium_ai(update, context, user_db, text, user_name)

    except Exception as e:
        logger.error(f"Critical error in handle_message for {user_id}: {e}", exc_info=True)
        error_msg = "Waduh, ada kendala teknis nih. 🛠️\nTim kami sudah diberitahu. Coba lagi sebentar lagi ya!"
        await update.message.reply_text(error_msg)

async def _handle_sharing_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, text: str, user_name: str):
    """Handles informational statements (non-transactional)."""
    try:
        # Use Premium AI to generate a conversational response
        premium_response = await premium_ai.process_interaction(user_db.id, text, user_name)
        
        response_msg = premium_response.suggested_response or "Wah, mantap! Terima kasih infonya."
        
        # Check if there's advice or insight
        if premium_response.predictive_advice:
            response_msg += f"\n\n💡 **Saran:**\n{premium_response.predictive_advice}"
            
        await update.message.reply_text(response_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error handling sharing info: {e}")
        await update.message.reply_text("Wah menarik! Terima kasih sudah cerita.")

async def _handle_pending_states(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Handles explicit state-based flows (editing transactions). Returns True if handled."""
    state = context.user_data.get("state")
    pending_tx = context.user_data.get("pending_tx")
    
    if state and pending_tx:
        if state == "WAITING_EDIT_AMOUNT":
            v = nlp.validate_edit("amount", text)
            if v.get("valid"):
                pending_tx["amount"] = v.get("new_value")
                context.user_data["pending_tx"] = pending_tx
                context.user_data.pop("state", None)
                await update.message.reply_text(_tx_preview_message(pending_tx), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
            else:
                await update.message.reply_text("Nominalnya belum valid. Contoh: `25rb` atau `25000`.")
            return True
            
        if state == "WAITING_EDIT_DATE":
            t = (text or "").strip()
            if len(t) >= 8:
                pending_tx["date"] = t
                context.user_data["pending_tx"] = pending_tx
                context.user_data.pop("state", None)
                await update.message.reply_text(_tx_preview_message(pending_tx), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
            else:
                await update.message.reply_text("Format tanggal belum kebaca. Contoh: `16-11-2015` atau `2015-11-16`.")
            return True

    # Handle Payment Method Context for pending transactions
    if pending_tx and not state:
        pm = _looks_like_payment_method(text)
        if pm:
            pending_tx["payment_method"] = pm
            context.user_data["pending_tx"] = pending_tx
            await update.message.reply_text(_tx_preview_message(pending_tx), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
            return True
            
    return False

async def _process_with_premium_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, text: str, user_name: str):
    """Delegates complex queries to Premium AI Engine."""
    user_id = user_db.id
    
    try:
        premium_response = await asyncio.wait_for(
            premium_ai.process_interaction(user_id, text, user_name), 
            timeout=Config.AI_TIMEOUT_SECONDS
        )
        
        intent = premium_response.intent
        response_msg = premium_response.suggested_response
        
        if intent == "cancel":
            structured = premium_response.structured_data or {}
            await _send_cancel_flow(update, context, user_db, structured, text)
            return
        
        if intent == "record" and premium_response.structured_data:
            await _handle_record_intent(update, context, user_id, text, premium_response)
            return

        elif intent == "insight":
            response_msg = premium_response.predictive_advice or premium_response.suggested_response

        # Gamification & Broadcasting
        if premium_response.needs_live_update:
            await _handle_gamification_update(user_id, intent, text, premium_response, response_msg)

        if response_msg:
            await update.message.reply_text(response_msg, parse_mode='Markdown')

    except asyncio.TimeoutError:
        logger.warning(f"AI Timeout for user {user_id}")
        await update.message.reply_text("Maaf, AI lagi mikir keras dan kelamaan. Coba lagi ya atau persingkat kalimatmu.")
    except Exception as e:
        raise e

async def _handle_record_intent(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, premium_response):
    """Handles transaction recording intent from AI."""
    data = premium_response.structured_data
    amount = data.get("amount", 0)
    
    # Validate amount
    try:
        amount = float(amount) if amount is not None else 0.0
    except (ValueError, TypeError):
        amount = 0.0
    
    # Fallback amount parsing
    if amount <= 0:
        fallback = parse_primary_amount_id(text)
        if fallback:
            amount = float(fallback)
    
    if amount <= 0:
        logger.warning(f"Skipping transaction with amount {amount} for user {user_id}")
        msg = premium_response.suggested_response or "Hmm, nominalnya berapa ya kak? Aku belum nangkep nih. 🤔"
        await update.message.reply_text(msg)
        return

    # Check for duplicates
    try:
        is_duplicate = await premium_ai.check_reconciliation(user_id, data)
        if is_duplicate:
            response_msg = "⚠️ **Potensi Duplikat Terdeteksi!**\nTransaksi serupa baru saja dicatat. Yakin mau simpan lagi?"
            # In a real scenario, we might want to attach a confirmation button here
            # For now, we just warn the user. They can re-submit if needed or we could add a "force" flag.
            await update.message.reply_text(response_msg, parse_mode='Markdown')
            return
    except Exception as e:
        logger.error(f"Error checking reconciliation: {e}")

    # Prepare Pending Transaction
    pending = {
        "amount": float(amount),
        "category": data.get("category", "Lain-lain"),
        "merchant": data.get("description", text),
        "date": datetime.now().strftime("%d-%m-%Y"),
        "payment_method": data.get("payment_method", None),
    }
    
    # Get Contextual Insight (New Feature)
    feedback = ""
    try:
        feedback = analyzer.get_instant_feedback(
            user_id, 
            pending["category"], 
            pending["merchant"], 
            pending["amount"]
        )
    except Exception:
        pass

    context.user_data["pending_tx"] = pending
    context.user_data.pop("state", None)
    
    await update.message.reply_text(
        _tx_preview_message(pending, feedback), 
        parse_mode="Markdown", 
        reply_markup=_tx_preview_keyboard()
    )

async def _handle_gamification_update(user_id: int, intent: str, text: str, premium_response, response_msg: str):
    """Updates gamification stats and broadcasts via WebSocket."""
    try:
        from core import gamify
        xp_status = await gamify.add_xp(user_id, "transaction" if intent == "record" else "insight")
        
        if xp_status.get("leveled_up"):
            level = xp_status.get("current_level")
            title = xp_status.get("title")
            # Append level up message to response
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
