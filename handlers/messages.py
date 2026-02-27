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
from core import db, premium_ai, ws_server, nlp, ocr, budget_mgr, analyzer, persona_mgr, fin_intel, multimodal_ai, doc_processor, market_data
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
    from utils.visuals import format_currency
    amount_str = format_currency(getattr(tx, "amount", 0))
    category = getattr(tx, "category", "-")
    tx_id = getattr(tx, "id", "?")
    
    return f"{icon} `#{tx_id}` | {date_str} | {category} | **{amount_str}**\n_{desc}_"

def _tx_preview_message(pending: dict, feedback: str = "", persona: Any = None) -> str:
    """Formats a premium pending transaction preview message with behavioural insights."""
    from utils.visuals import format_currency
    amount_str = format_currency(pending.get("amount", 0) or 0)
    category = pending.get("category") or "Lain-lain"
    merchant = pending.get("merchant") or pending.get("description") or "Transaksi"
    date = pending.get("date") or datetime.now().strftime("%d-%m-%Y")
    
    # Premium Persona Tone
    persona_name = persona.name if persona else "FinBot"
    
    msg = (
        f"💳 **{persona_name} Preview**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Nominal**: {amount_str}\n"
        f"🏷️ **Kategori**: {category}\n"
        f"🏢 **Merchant**: {merchant}\n"
        f"📅 **Waktu**: {date}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if feedback:
        msg += f"\n💡 **Behavioural Insights**:\n{feedback}\n"
        
    msg += "\n*Konfirmasi untuk simpan transaksi ini?*"
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
                    # 1. New Receipt Intelligence Pipeline
                    result = await asyncio.wait_for(
                        ocr.process_receipt_intelligence(photo_path, user_id),
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
        # Map fields from Receipt Intelligence JSON schema
        amount = result.get('total', 0) 
        items = result.get('items', [])
        tax = result.get('tax', 0)
        discount = result.get('discount', 0)
        
        # Confidence Flagging
        review_required = result.get("review_required", False)
        
        # Construct summary message
        summary = f"🧾 **Receipt Intelligence Result**\n"
        if review_required:
            summary += "⚠️ *Confidence Rendah - Mohon Periksa Kembali*\n"
        summary += f"━━━━━━━━━━━━━━━━━━━━\n"
        summary += f"🏢 **Toko**: {merchant}\n"
        from utils.visuals import format_currency
        summary += f"💰 **Total**: {format_currency(amount)}\n"
        
        if tax > 0: summary += f"🧾 **Pajak**: {format_currency(tax)}\n"
        if discount > 0: summary += f"🏷️ **Diskon**: {format_currency(discount)}\n"
        
        if items:
            summary += "\n🛒 **Item Terdeteksi:**\n"
            for item in items[:5]:
                qty_str = f" (x{item['qty']})" if item.get('qty') else ""
                summary += f"• {item['name']}{qty_str}: {format_currency(item['price'])}\n"
            if len(items) > 5: summary += f"  ...dan {len(items)-5} item lainnya\n"

        await update.message.reply_text(summary, parse_mode='Markdown')
        
        # Prepare Pending Transaction
        pending = {
            "amount": float(amount),
            "category": nlp._detect_category(merchant + " " + (items[0]['name'] if items else ""))[0],
            "merchant": merchant,
            "date": result.get('date') or datetime.now().strftime("%d-%m-%Y"),
            "type": "expense"
        }
        
        # Financial Persona Update (Gamification 2.0)
        from core import gamify, db
        persona_data = await gamify.update_financial_persona(user_id, db)
        
        feedback = ""
        if persona_data:
            feedback = f"👤 **Persona Update**: Kamu saat ini adalah **{persona_data['persona']}**."
            
        # Contextual Insight
        try:
            instant_feedback, stress_level = analyzer.get_instant_feedback(
                user_id, pending["category"], pending["merchant"], pending["amount"]
            )
            feedback += "\n" + instant_feedback
        except Exception: pass

        context.user_data["pending_tx"] = pending
        context.user_data.pop("state", None)
        
        await update.message.reply_text(
            _tx_preview_message(pending, feedback), 
            parse_mode="Markdown", 
            reply_markup=_tx_preview_keyboard()
        )
        
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

async def _handle_disambiguation(update: Update, context: ContextTypes.DEFAULT_TYPE, data: Dict[str, Any]):
    """Asks for clarification on ambiguous intents like 'transfer'."""
    amount = data.get("amount")
    
    msg = (
        f"🔍 **Konfirmasi Transaksi**\n\n"
        f"Kamu baru saja menyebutkan: **Rp{amount:,.0f}**\n"
        "Ini masuk ke kategori mana ya?"
    )
    
    # Store data for callback
    context.user_data["pending_tx"] = {
        "amount": amount,
        "merchant": data.get("merchant") or "Transfer/Bayar",
        "date": data.get("date"),
        "type": "expense" # Default
    }
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Belanja", callback_data="set_cat_Belanja"),
            InlineKeyboardButton("🤝 Sosial", callback_data="set_cat_Sosial")
        ],
        [
            InlineKeyboardButton("📈 Investasi", callback_data="set_cat_Investasi"),
            InlineKeyboardButton("💰 Pemasukan", callback_data="set_cat_Gaji")
        ],
        [InlineKeyboardButton("❌ Abaikan", callback_data="tx_ignore")]
    ])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes uploaded documents for financial intelligence."""
    doc = update.message.document
    file_name = doc.file_name
    mime_type = doc.mime_type
    
    await update.message.reply_text(f"⏳ **Analyzing financial document: {file_name}...**", parse_mode='Markdown')
    
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        
        # 1. Process Raw Text
        raw_text = await doc_processor.process_file(bytes(file_bytes), file_name, mime_type)
        
        # 2. Financial Parsing
        parsed_data = await doc_processor.parse_financial_document(raw_text, premium_ai.client)
        
        if "error" in parsed_data:
            await update.message.reply_text(f"Gagal membedah laporan: {parsed_data['error']}")
            return
            
        # 3. Format Response
        meta = parsed_data.get("metadata", {})
        metrics = parsed_data.get("metrics", {})
        
        msg = (
            f"📄 **Financial Analysis: {meta.get('ticker', 'Unknown')}**\n"
            f"📅 Period: {meta.get('period', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Revenue: {metrics.get('revenue', 0):,.0f}\n"
            f"📉 Net Income: {metrics.get('net_income', 0):,.0f}\n"
            f"🏦 Total Assets: {metrics.get('total_assets', 0):,.0f}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 **Summary**: {parsed_data.get('summary', 'No summary available.')}"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Document analysis failed: {e}")
        await update.message.reply_text("Terjadi kesalahan saat memproses dokumen.")

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
        
        # --- Context Memory Layer (Short-term Brain) ---
        context_buffer = context.user_data.get("context_buffer", {})
        last_ts = context_buffer.get("ts", 0)
        current_ts = datetime.now().timestamp()
        
        # If last message was < 5 minutes ago, try to merge context
        is_follow_up = (current_ts - last_ts) < 300 
        
        extracted = nlp.extract_transaction_data(text)
        
        # --- Predictive Completion ---
        if extracted.get("amount") and extracted.get("category") and extracted.get("merchant") == "Transaksi":
            prediction = analyzer.get_predictive_context(user_id, extracted["category"], extracted["amount"])
            if prediction and prediction.get("merchant"):
                extracted["merchant"] = prediction["merchant"]
                extracted["confidence"] = max(extracted["confidence"], 0.8)
                # Could also add "time_label" hint to the message
        
        if is_follow_up and extracted.get("is_partial"):
            # Merge logic: if this message is partial (e.g. "di mixue"), merge with previous data
            prev_data = context_buffer.get("data", {})
            if prev_data:
                # Merge fields: current message values overwrite previous ones if they exist
                for key in ["amount", "category", "merchant", "date", "type"]:
                    if extracted.get(key):
                        prev_data[key] = extracted[key]
                extracted = prev_data
                extracted["confidence"] = min(0.95, extracted.get("confidence", 0.6) + 0.1) # Boost confidence on merge
                extracted["is_partial"] = not (extracted.get("amount") and extracted.get("merchant") != "Transaksi")
        
        # Save current state to context buffer
        context.user_data["context_buffer"] = {
            "ts": current_ts,
            "data": extracted
        }

        intent = extracted.get("intent")
        
        # --- Intent Routing (Fixed) ---
        if intent == "STOP_NOTIF":
             await update.message.reply_text("Siap! Aku bakal kurangi frekuensi daily digest kamu. Pengaturan notifikasi bisa kamu atur lebih detail di `/settings` ya.")
             return

        if intent == "CANCEL":
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
            context.args = [extracted.get("value")]
            await set_persona_command(update, context)
            return
            
        if intent == "SET_REMINDER":
            context.args = [extracted.get("value")]
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
                # New: Cashflow Forecast after salary input
                forecast = await analyzer.get_predictive_forecast(user_id)
                if forecast:
                    await update.message.reply_text(forecast, parse_mode='Markdown')
            else:
                await update.message.reply_text("Gajinya berapa? Contoh: 'set gaji 10jt'")
            return

        if intent == "UNDO":
            await _handle_undo(update, context, user_db)
            return

        if intent == "EXECUTIVE_MODE":
            summary = analyzer.get_executive_summary(user_id)
            wealth = analyzer.get_wealth_narrative(user_id)
            await update.message.reply_text(f"{summary}\n\n{wealth}", parse_mode='Markdown')
            return
            
        if intent == "ELITE_ANALYSIS":
            await _handle_elite_analysis(update, context)
            return
            
        if intent == "INVESTMENT_OPPS":
            await _handle_investment_opps(update, context)
            return
            
        if intent == "DOC_ANALYSIS":
            await update.message.reply_text("Silakan kirim file (PDF/TXT) atau foto laporan keuangan yang ingin dianalisis.")
            return

        if intent == "SET_BUDGET":
            amount = nlp._extract_amount(text)
            category, _ = nlp._detect_category(text)
            if amount > 0 and category != "Lain-lain":
                context.args = [category, str(int(amount))]
                await set_budget(update, context)
            elif amount > 0:
                 await update.message.reply_text("Budget untuk kategori apa? Contoh: 'set budget makan 1jt'")
            else:
                 await update.message.reply_text("Nominalnya berapa? Contoh: 'set budget makan 1jt'")
            return

        if intent == "SET_BUDGET_ALERT":
            category, _ = nlp._detect_category(text)
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

        # --- Disambiguation Layer ---
        if extracted.get("needs_disambiguation") and extracted.get("amount"):
            await _handle_disambiguation(update, context, extracted)
            return

        # --- More Intent Routing ---
        if intent == "QUERY_SUMMARY" or intent == "get_report": 
             await summary_command(update, context)
             return

        if intent == "CORRECTION":
            await _handle_correction(update, context, user_db, text)
            return

        if intent == "SPLIT_BILL":
            await _handle_split_bill(update, context, user_db, text)
            return

        if intent == "BULK_TRANSACTION":
            await _handle_bulk_transaction(update, context, user_db, text)
            return

        if intent == "SHARING_INFO":
            await _handle_sharing_info(update, context, user_db, text, user_name)
            return
            
        if intent == "GREETING":
            await _handle_sharing_info(update, context, user_db, text, user_name)
            return

        if intent == "SMALL_TALK":
            response = classification.get("response") or "Halo! Ada yang bisa aku bantu?"
            await update.message.reply_text(response)
            return

        # 3. Handle Pending States (Edit Flows)
        if await _handle_pending_states(update, context, text):
            return

        # 4. Check for Transaction (ADD_TRANSACTION)
        if intent == "ADD_TRANSACTION":
             # Use the new extraction logic
             tx_data = extracted # Use the already extracted/merged data
             if tx_data.get("amount"):
                 # Prepare Pending Transaction
                 pending = {
                    "amount": float(tx_data["amount"]),
                    "category": tx_data["category"] or "Lain-lain",
                    "merchant": tx_data["merchant"] or "Transaksi",
                    "date": tx_data.get("date") or datetime.now().strftime("%d-%m-%Y"),
                    "type": tx_data.get("type", "expense")
                 }
                 
                 # Contextual Insight & Stress Level
                 feedback, stress_level = analyzer.get_instant_feedback(
                    user_id, pending["category"], pending["merchant"], pending["amount"]
                 )
                 
                 # Decision Framing (New Premium Feature)
                 framing = budget_mgr.get_decision_framing(user_id, pending["category"], pending["amount"])
                 if framing:
                     feedback = framing + "\n" + feedback
                 
                 # Financial DNA Insight
                 dna = analyzer.get_financial_dna(user_id)
                 if dna.get("tempo") == "boros_awal" and datetime.now().day <= 10:
                     feedback += "\n💡 **Financial DNA**: Kamu cenderung boros di awal bulan. Mau atur limit?"
                 
                 # Adaptive Persona
                 persona = persona_mgr.get_persona(user_id, stress_level)
                 
                 # --- Zero-Friction Auto-Commit ---
                 # If confidence is very high (>0.92) and not a critical alert, auto-save to reduce friction
                 if tx_data.get("confidence", 0) > 0.92 and stress_level == "low":
                     try:
                         new_tx = db.add_transaction(
                             user_id=user_db.id,
                             amount=pending["amount"],
                             category=pending["category"],
                             trans_type=pending["type"],
                             description=pending["merchant"],
                             trans_date=datetime.now()
                         )
                         if new_tx:
                             context.user_data["last_tx_id"] = new_tx.id
                             context.user_data["last_tx_ts"] = datetime.now().timestamp()
                             from utils.visuals import format_currency
                             await update.message.reply_text(
                                 f"✅ **Auto-Logged**: {format_currency(pending['amount'])} untuk {pending['category']}.\n"
                                 f"{framing}\n\n"
                                 f"_Ketik 'undo' untuk batal._",
                                 parse_mode="Markdown"
                             )
                             return
                     except Exception:
                         pass # Fallback to preview if auto-commit fails

                 context.user_data["pending_tx"] = pending
                 context.user_data.pop("state", None)
                 
                 await update.message.reply_text(
                    _tx_preview_message(pending, feedback, persona), 
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

async def _handle_undo(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db):
    """Handles frictionless undo within a 10-second window."""
    last_tx_ts = context.user_data.get("last_tx_ts", 0)
    current_ts = datetime.now().timestamp()
    
    if (current_ts - last_tx_ts) > 30: # Allow 30s for undo (slightly more than 10s for network delay)
        await update.message.reply_text("Sesi undo sudah berakhir. Pakai `batal transaksi terakhir` ya.")
        return
        
    last_tx_id = context.user_data.get("last_tx_id")
    if not last_tx_id:
        await update.message.reply_text("Tidak ada transaksi yang bisa dibatalkan.")
        return
        
    success = db.delete_transaction(user_db.id, last_tx_id)
    if success:
        context.user_data.pop("last_tx_id", None)
        await update.message.reply_text(f"✅ Transaksi `#{last_tx_id}` berhasil dibatalkan. Saldo dipulihkan.")
    else:
        await update.message.reply_text("Gagal membatalkan transaksi. Coba hapus manual via `/history`.")

async def _handle_elite_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deep AI Financial Intelligence Analysis."""
    user_id = update.effective_user.id
    await update.message.reply_text("🚀 **Initiating Elite Financial Intelligence Engine...**", parse_mode='Markdown')
    
    try:
        # 1. Market Trend Prediction
        # For demo, predict popular Indonesian tickers
        tickers = ["BBCA", "TLKM", "ASII", "GOTO"]
        market_data = await fin_intel.predict_market_trends(tickers)
        
        # 2. Risk Assessment
        # Assume a simple demo portfolio
        portfolio = {"BBCA": 0.4, "TLKM": 0.3, "Gold": 0.3}
        risk_data = await fin_intel.assess_investment_risk(portfolio)
        
        # 3. Sentiment Analysis of last user message
        sentiment = await nlp.analyze_financial_sentiment(update.message.text)
        
        # 4. Ensemble Anomalies
        anomalies = await fin_intel.detect_anomalies_ensemble(user_id)
        
        # 5. Visualizations
        trend_viz = visual_reporter.generate_market_trend_viz(market_data)
        risk_viz = visual_reporter.generate_risk_profile_chart(risk_data)
        
        # Prepare Report
        msg = (
            "🧠 **Elite Financial Intelligence Report**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📈 **Market Forecast**:\n"
        )
        for t, d in market_data.items():
            icon = "🟢" if d['trend'] == "BULLISH" else "🔴"
            msg += f"• {t}: {icon} {d['trend']} (Conf: {d['confidence']})\n"
            
        msg += (
            f"\n🛡️ **Risk Profile**: {risk_data['risk_profile']}\n"
            f"• VaR (95%): {risk_data['value_at_risk_95']}%\n"
            f"• Sharpe Ratio: {risk_data['sharpe_ratio']}\n"
            f"• Rec: {risk_data['recommendation']}\n"
            f"\n📊 **Market Sentiment**: {sentiment['sentiment']} ({sentiment['score']})\n"
            f"• Reason: {sentiment['reason']}\n"
        )
        
        if anomalies:
            msg += f"\n🚨 **Anomalies Detected**: {len(anomalies)} suspicious transactions found."
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
        # Send charts
        if trend_viz:
            await update.message.reply_photo(trend_viz, caption="Market Trend Visualization")
        if risk_viz:
            await update.message.reply_photo(risk_viz, caption="Portfolio Risk Assessment")
            
    except Exception as e:
        logger.error(f"Elite analysis failed: {e}")
        await update.message.reply_text("Elite engine encountered an error. Please try again later.")

async def _handle_investment_opps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suggests investment opportunities based on health and market."""
    user_id = update.effective_user.id
    await update.message.reply_text("🔍 **Scanning for investment opportunities...**", parse_mode='Markdown')
    
    try:
        opps_data = await fin_intel.find_investment_opportunities(user_id)
        
        msg = (
            "💰 **Investment Opportunity Scan**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 **Strategy**: {opps_data['strategy']}\n"
            f"🏥 **Health Context**: {opps_data['health_context']}\n\n"
            "🌟 **Recommendations**:\n"
        )
        
        for op in opps_data['opportunities']:
            msg += f"• **{op['asset']}**: {op['reason']} (Conf: {op['confidence']})\n"
            
        msg += "\n⚠️ *Metodologi: Berdasarkan analisis portofolio historis dan tren pasar real-time.*"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Investment opps handler failed: {e}")
        await update.message.reply_text("Failed to scan opportunities. Please try again.")

async def _handle_bulk_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, text: str):
    """Handles multiple transactions in one message."""
    await update.message.reply_text("📦 **Mendeteksi beberapa transaksi sekaligus...**", parse_mode='Markdown')
    
    tx_items = nlp.extract_bulk_transactions(text)
    if not tx_items:
        await update.message.reply_text("Maaf, aku gagal memecah transaksi itu. Coba kirim satu-satu ya!")
        return

    from utils.visuals import format_currency
    msg = f"✅ **Berhasil mengekstrak {len(tx_items)} transaksi:**\n\n"
    total_bulk = 0
    for i, item in enumerate(tx_items, 1):
        amount = float(item.get('amount', 0))
        cat = item.get('category', 'Lain-lain')
        merc = item.get('merchant', 'Transaksi')
        total_bulk += amount
        msg += f"{i}. {cat} | **{format_currency(amount)}** | _{merc}_\n"
    
    msg += f"\n💰 **Total**: {format_currency(total_bulk)}\n\nKonfirmasi untuk simpan semua?"
    
    # Store in session for confirmation
    context.user_data["pending_bulk"] = tx_items
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Simpan Semua", callback_data="bulk_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="bulk_cancel")]
    ])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)

async def _handle_split_bill(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, text: str):
    """Handles split bill assistant."""
    data = nlp.extract_split_bill(text)
    if not data or not data.get("total_amount"):
        await update.message.reply_text("Nominalnya berapa? Contoh: 'makan 450rb bagi 3'")
        return

    from utils.visuals import format_currency
    total = data["total_amount"]
    people = data["num_people"]
    per_person = data["per_person"]
    
    msg = (
        "👥 **Split Bill Assistant**\n\n"
        f"• **Total Tagihan**: {format_currency(total)}\n"
        f"• **Jumlah Orang**: {people} orang\n"
        f"• **Patungan/Orang**: **{format_currency(per_person)}**\n\n"
        f"Mau aku catat sebagai pengeluaran kamu ({format_currency(per_person)}) atau catat total ({format_currency(total)}) dengan piutang?"
    )
    
    # Prepare pending tx for the user's share
    pending = {
        "amount": float(per_person),
        "category": data.get("category", "Sosial"),
        "merchant": f"Split Bill: {data.get('merchant', 'Makan Bareng')}",
        "date": data.get("date"),
        "type": "expense",
        "original_total": total,
        "people_count": people
    }
    
    context.user_data["pending_tx"] = pending
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Catat Rp{per_person:,.0f}", callback_data="tx_confirm")],
        [InlineKeyboardButton("📝 Catat Full + Piutang (Soon)", callback_data="split_receivable")],
        [InlineKeyboardButton("❌ Batal", callback_data="tx_ignore")]
    ])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)

async def _handle_correction(update: Update, context: ContextTypes.DEFAULT_TYPE, user_db, text: str):
    """Handles contextual correction of the last transaction."""
    txs = db.get_transactions_history(user_db.id, limit=1)
    if not txs:
        await update.message.reply_text("Belum ada transaksi yang bisa dikoreksi.")
        return
    
    last_tx = txs[0]
    new_data = nlp.extract_transaction_data_simple(text)
    
    if not new_data.get("amount") and not new_data.get("category") and not new_data.get("merchant"):
        await update.message.reply_text("Maksudnya gimana? Contoh: 'ralat tadi maksudnya 50rb'")
        return

    # Update only fields that are provided
    updated_tx = {
        "amount": new_data.get("amount") or last_tx.amount,
        "category": new_data.get("category") or last_tx.category,
        "merchant": new_data.get("merchant") or last_tx.description, # merchant maps to description in DB
        "date": new_data.get("date") or last_tx.date.strftime("%Y-%m-%d"),
        "type": last_tx.type,
        "id": last_tx.id
    }
    
    from utils.visuals import format_currency
    msg = (
        "✏️ **Koreksi Transaksi Terakhir**\n\n"
        "**LAMA:**\n"
        f"{_format_tx(last_tx)}\n\n"
        "**BARU:**\n"
        f"• Nominal: {format_currency(updated_tx['amount'])}\n"
        f"• Kategori: {updated_tx['category']}\n"
        f"• Deskripsi: {updated_tx['merchant']}\n\n"
        "Konfirmasi perubahan?"
    )
    
    context.user_data["pending_update"] = updated_tx
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ya, Update", callback_data="update_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="update_cancel")]
    ])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)

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
