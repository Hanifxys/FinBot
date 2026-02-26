from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, premium_ai, ws_server, nlp, ocr, budget_mgr
import logging
import asyncio
from datetime import datetime
import os
import gc
import time
import json
from config import CATEGORIES
from handlers import tutorial_mode
from modules.amounts import parse_primary_amount_id

logger = logging.getLogger(__name__)

OCR_MAX_DOWNLOAD_BYTES = int(os.getenv("OCR_MAX_DOWNLOAD_BYTES", "1200000"))
OCR_RATE_LIMIT_SECONDS = int(os.getenv("OCR_RATE_LIMIT_SECONDS", "60"))
OCR_HANDLER_TIMEOUT_SECONDS = float(os.getenv("OCR_HANDLER_TIMEOUT_SECONDS", "55"))
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "1"))
OCR_SEMAPHORE = asyncio.Semaphore(max(OCR_CONCURRENCY, 1))
OCR_MAX_MEMORY_PERCENT = float(os.getenv("OCR_MAX_MEMORY_PERCENT", "80"))
CANCEL_CANDIDATE_LIMIT = int(os.getenv("CANCEL_CANDIDATE_LIMIT", "30"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "25"))
TUTORIAL_TIMEOUT_SECONDS = int(os.getenv("TUTORIAL_TIMEOUT_SECONDS", "900"))
TUTORIAL_TOTAL_STEPS = 5

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

def _tutorial_bar(step: int, total: int) -> str:
    try:
        step = int(step)
        total = int(total)
    except Exception:
        return ""
    if total <= 0:
        return ""
    step = max(0, min(step, total))
    filled = int(round((step / total) * 10))
    filled = max(0, min(filled, 10))
    return "█" * filled + "░" * (10 - filled)

def _tutorial_state(user_data: dict):
    state = user_data.get("tutorial_mode")
    if not isinstance(state, dict):
        return None
    if not state.get("active"):
        return None
    return state

def _tutorial_log(user_id: int, event: str, payload: dict):
    try:
        entry = {"event": event, "ts": datetime.utcnow().isoformat() + "Z", "data": payload or {}}
        premium_ai.redis.client.lpush(f"tutorial_events:{user_id}", json.dumps(entry))
        premium_ai.redis.client.ltrim(f"tutorial_events:{user_id}", 0, 500)
    except Exception:
        pass

def _tutorial_keyboard(active: bool = True):
    if not active:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("▶️ Mulai (Pemula)", callback_data="tutorial_start_beginner"),
                InlineKeyboardButton("⚡ Mulai (Cepat)", callback_data="tutorial_start_fast"),
            ],
            [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
        ])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭️ Skip", callback_data="tutorial_skip"),
            InlineKeyboardButton("🆘 Help", callback_data="tutorial_help"),
        ],
        [
            InlineKeyboardButton("🚪 Keluar", callback_data="tutorial_exit"),
        ],
    ])

def _tutorial_intro() -> str:
    return (
        "🎓 **Tutorial Mode (Interaktif)**\n\n"
        "Pilih mode:\n"
        "- **Pemula**: lengkap + banyak contoh\n"
        "- **Cepat**: langsung praktek\n\n"
        f"Progress: `{_tutorial_bar(0, TUTORIAL_TOTAL_STEPS)}` 0/{TUTORIAL_TOTAL_STEPS}"
    )

def _tutorial_step_message(step: int) -> str:
    bar = _tutorial_bar(step - 1, TUTORIAL_TOTAL_STEPS)
    if step == 1:
        return (
            f"🎓 **Tutorial Mode**\n\n"
            f"Progress: `{bar}` {step-1}/{TUTORIAL_TOTAL_STEPS}\n\n"
            "Step 1/5 — **Catat transaksi pertama**\n"
            "Coba ketik pengeluaran pertama kamu.\n\n"
            "Contoh:\n"
            "- `kopi 25rb`\n"
            "- `makan 40000`\n"
        )
    if step == 2:
        bar = _tutorial_bar(1, TUTORIAL_TOTAL_STEPS)
        return (
            f"🎓 **Tutorial Mode**\n\n"
            f"Progress: `{bar}` 1/{TUTORIAL_TOTAL_STEPS}\n\n"
            "Step 2/5 — **Set pemasukan (gaji)**\n"
            "Ketik gaji bulanan kamu.\n\n"
            "Contoh:\n"
            "- `gaji 7jt`\n"
            "- `7000000`\n"
        )
    if step == 3:
        bar = _tutorial_bar(2, TUTORIAL_TOTAL_STEPS)
        cats = ", ".join(CATEGORIES)
        return (
            f"🎓 **Tutorial Mode**\n\n"
            f"Progress: `{bar}` 2/{TUTORIAL_TOTAL_STEPS}\n\n"
            "Step 3/5 — **Set budget kategori**\n"
            f"Pilih 1 kategori dan limitnya.\n\nKategori: {cats}\n\n"
            "Contoh:\n"
            "- `Makanan 1.5jt`\n"
            "- `Transportasi 300rb`\n"
        )
            f"Pilih 1 kategori dan limitnya.\n\nKategori: {cats}\n\n"
            "Contoh:\n"
            "- `Makanan 1.5jt`\n"
            "- `Transportasi 300rb`\n"
        )
    if step == 4:
        bar = _tutorial_bar(3, TUTORIAL_TOTAL_STEPS)
        return (
            f"🎓 **Tutorial Mode**\n\n"
            f"Progress: `{bar}` 3/{TUTORIAL_TOTAL_STEPS}\n\n"
            "Step 4/5 — **Cek budget & laporan**\n"
            "Aku akan tampilkan ringkasan budget kamu sekarang.\n"
            "Setelah itu balas: `lanjut`."
        )
    bar = _tutorial_bar(4, TUTORIAL_TOTAL_STEPS)
    return (
        f"🎓 **Tutorial Mode**\n\n"
        f"Progress: `{bar}` 4/{TUTORIAL_TOTAL_STEPS}\n\n"
        "Step 5/5 — **Latihan pembatalan transaksi**\n"
        "Sekarang coba ketik: `batal transaksi terakhir`\n"
        "Nanti akan muncul tombol konfirmasi 1-klik."
    )

async def _tutorial_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.pop("tutorial_mode", None)
    _tutorial_log(user_id, "completed", {})
    msg = (
        "🏁 **Tutorial selesai!**\n\n"
        "Kamu sudah bisa:\n"
        "- Catat transaksi\n"
        "- Set gaji\n"
        "- Set budget\n"
        "- Cek laporan\n"
        "- Batalkan transaksi dengan 1-klik\n\n"
        "Ketik `help` atau klik **Menu Utama** untuk eksplor fitur."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
        [InlineKeyboardButton("👤 Profil", callback_data="get_profile")],
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

async def _handle_tutorial_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    state = _tutorial_state(context.user_data)
    if not state:
        return False

    now_ts = time.time()
    last_ts = float(state.get("last_ts") or 0)
    if last_ts and (now_ts - last_ts) > TUTORIAL_TIMEOUT_SECONDS:
        _tutorial_log(user_id, "timeout", {"step": int(state.get("step") or 1)})
        context.user_data.pop("tutorial_mode", None)
        await update.message.reply_text("Tutorialnya sudah timeout. Ketik `tutorial` untuk mulai lagi.")
        return True

    t = (text or "").strip()
    low = t.lower()
    state["last_ts"] = now_ts

    if low in ("skip", "lewati", "skip tutorial", "lewati tutorial"):
        state["step"] = min(int(state.get("step") or 1) + 1, TUTORIAL_TOTAL_STEPS)
        _tutorial_log(user_id, "skipped_step", {"step": int(state.get("step") or 1)})
        await update.message.reply_text(_tutorial_step_message(int(state["step"])), parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        context.user_data["tutorial_mode"] = state
        return True

    if low in ("help", "tolong", "bantu", "bingung", "gatau", "ga tau"):
        msg = (
            "🆘 **Bantuan cepat**\n\n"
            "Kalau kamu bingung, pakai format ini:\n"
            "- Transaksi: `kopi 25rb`\n"
            "- Gaji: `7jt`\n"
            "- Budget: `Makanan 1jt`\n"
            "- Lanjut: `lanjut`\n"
            "- Batalin: `batal transaksi terakhir`\n\n"
            "Atau klik `Skip` kalau mau loncat step."
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        context.user_data["tutorial_mode"] = state
        return True

    step = int(state.get("step") or 1)
    user_db = db.get_or_create_user(user_id, update.effective_user.username)

    if step == 1:
        amount = _parse_amount_hint(t)
        if amount is None:
            try:
                pr = await asyncio.wait_for(premium_ai.process_interaction(user_id, t, update.effective_user.first_name), timeout=AI_TIMEOUT_SECONDS)
                if pr and pr.intent == "record" and pr.structured_data:
                    amount = pr.structured_data.get("amount")
            except Exception:
                amount = None
        try:
            amount = float(amount) if amount is not None else None
        except Exception:
            amount = None
        if not amount or amount <= 0:
            state["errors"] = int(state.get("errors") or 0) + 1
            _tutorial_log(user_id, "invalid_input", {"step": 1, "text": t[:120]})
            await update.message.reply_text("Belum kebaca nominalnya. Coba lagi ya, contoh: `kopi 25rb` atau `makan 40000`.", reply_markup=_tutorial_keyboard(True))
            context.user_data["tutorial_mode"] = state
            return True

        try:
            db.add_transaction(user_id=user_db.id, amount=amount, category="Lain-lain", description=t, trans_type="expense")
        except Exception:
            pass
        _tutorial_log(user_id, "step_completed", {"step": 1})
        state["step"] = 2
        context.user_data["tutorial_mode"] = state
        await update.message.reply_text(f"✅ Mantap! Transaksi pertama tercatat: **Rp{amount:,.0f}**", parse_mode="Markdown")
        await update.message.reply_text(_tutorial_step_message(2), parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        return True

    if step == 2:
        amount = _parse_amount_hint(t)
        if amount is None:
            digits = "".join([c for c in low if c.isdigit()])
            try:
                amount = float(digits) if digits else None
            except Exception:
                amount = None
        if not amount or amount < 10000:
            state["errors"] = int(state.get("errors") or 0) + 1
            _tutorial_log(user_id, "invalid_input", {"step": 2, "text": t[:120]})
            await update.message.reply_text("Nominal gajinya belum kebaca. Contoh: `gaji 7jt` atau `7000000`.", reply_markup=_tutorial_keyboard(True))
            context.user_data["tutorial_mode"] = state
            return True

        try:
            db.add_monthly_income(user_db.id, amount)
        except Exception:
            pass
        _tutorial_log(user_id, "step_completed", {"step": 2})
        state["step"] = 3
        context.user_data["tutorial_mode"] = state
        await update.message.reply_text(f"✅ Oke! Gaji kamu tersimpan: **Rp{amount:,.0f}**", parse_mode="Markdown")
        await update.message.reply_text(_tutorial_step_message(3), parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        return True

    if step == 3:
        amount = _parse_amount_hint(t)
        cat = None
        for c in CATEGORIES:
            if c.lower() in low:
                cat = c
                break
        if not cat:
            for token in low.replace(",", " ").split():
                for c in CATEGORIES:
                    if token == c.lower():
                        cat = c
                        break
                if cat:
                    break
        if not amount or not cat:
            state["errors"] = int(state.get("errors") or 0) + 1
            _tutorial_log(user_id, "invalid_input", {"step": 3, "text": t[:120]})
            await update.message.reply_text("Formatnya gini ya: `Makanan 1jt` atau `Transportasi 300rb`.", reply_markup=_tutorial_keyboard(True))
            context.user_data["tutorial_mode"] = state
            return True

        try:
            db.set_budget(user_db.id, cat, amount)
        except Exception:
            pass
        _tutorial_log(user_id, "step_completed", {"step": 3, "category": cat})
        state["step"] = 4
        context.user_data["tutorial_mode"] = state
        await update.message.reply_text(f"✅ Budget tersimpan: **{cat} = Rp{float(amount):,.0f}**", parse_mode="Markdown")
        await update.message.reply_text(_tutorial_step_message(4), parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        try:
            status = budget_mgr.check_budget_status(user_db.id, "Semua")
            if status:
                await update.message.reply_text(status)
        except Exception:
            pass
        return True

    if step == 4:
        if low not in ("lanjut", "ok", "oke", "gas", "next", "lanjut ya"):
            await update.message.reply_text("Balas `lanjut` untuk masuk step terakhir ya.", reply_markup=_tutorial_keyboard(True))
            context.user_data["tutorial_mode"] = state
            return True
        _tutorial_log(user_id, "step_completed", {"step": 4})
        state["step"] = 5
        context.user_data["tutorial_mode"] = state
        await update.message.reply_text(_tutorial_step_message(5), parse_mode="Markdown", reply_markup=_tutorial_keyboard(True))
        return True

    if step == 5:
        if any(k in low for k in ("batal", "undo", "hapus")):
            state["awaiting_cancel_confirm"] = True
            context.user_data["tutorial_mode"] = state
            await _send_cancel_flow(update, context, user_db, {"cancel_action": "undo_last", "reason": "tutorial"}, t)
            _tutorial_log(user_id, "step_started", {"step": 5})
            return True
        await update.message.reply_text("Coba ketik: `batal transaksi terakhir` ya.", reply_markup=_tutorial_keyboard(True))
        context.user_data["tutorial_mode"] = state
        return True

    return False

def _is_tutorial_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    keys = [
        "tutorial", "tutor", "cara pakai", "cara pake", "guide", "panduan",
        "gimana pakenya", "gimana makenya", "cara kerja", "step", "step by step",
        "mulai dari mana", "onboarding", "help dong", "ajarin", "ajari"
    ]
    return any(k in t for k in keys)

def _tutorial_message() -> str:
    return (
        "🚀 **TUTORIAL FINBOT (End-to-End)**\n\n"
        "Tujuan: catat pengeluaran → cek budget → dapat insight → rapihin data → kalau salah, bisa batalin.\n\n"
        "**Flow Cepat (30 detik):**\n"
        "1) Catat: ketik `kopi 25rb` atau `gajian 7jt`\n"
        "2) Cek: klik **📊 Cek Budget** atau ketik `cek budget`\n"
        "3) Laporan: klik **📈 Laporan** atau `/summary monthly`\n"
        "4) Insight: klik **🧠 AI Insights** (di menu)\n"
        "5) Salah catat? ketik: `batal yang 25rb` / `hapus #ID` / `batal transaksi terakhir`\n\n"
        "**Diagram Alur:**\n"
        "Input ➜ (AI/NLP) ➜ Simpan transaksi ➜ Update budget ➜ Insight/Laporan\n"
        "          │\n"
        "          └─ Jika salah ➜ Deteksi pembatalan ➜ Konfirmasi 1-klik ➜ Update riwayat\n\n"
        "Pilih bagian tutorial yang kamu mau:"
    )

def _tutorial_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⚡ Quickstart", callback_data="tutorial_quickstart"),
            InlineKeyboardButton("📸 Scan Struk", callback_data="tutorial_scan"),
        ],
        [
            InlineKeyboardButton("↩️ Batalin Transaksi", callback_data="tutorial_cancel"),
            InlineKeyboardButton("📊 Laporan & Budget", callback_data="tutorial_reports"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="tutorial_settings"),
            InlineKeyboardButton("✅ Best Practices", callback_data="tutorial_best"),
        ],
        [
            InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

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
    return parse_primary_amount_id(text)

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

def _tx_preview_message(pending: dict) -> str:
    amount = pending.get("amount", 0) or 0
    category = pending.get("category") or "Lain-lain"
    merchant = pending.get("merchant") or pending.get("description") or "Transaksi"
    payment = pending.get("payment_method") or "-"
    date = pending.get("date") or datetime.now().strftime("%d-%m-%Y")
    return (
        "🧾 **Preview Transaksi**\n\n"
        f"• Item: **{merchant}**\n"
        f"• Nominal: **Rp{float(amount):,.0f}**\n"
        f"• Kategori: **{category}**\n"
        f"• Metode: **{payment}**\n"
        f"• Tanggal: **{date}**\n\n"
        "Lanjut simpan atau edit dulu?"
    )

def _tx_preview_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Simpan", callback_data="tx_confirm"),
            InlineKeyboardButton("✎ Edit", callback_data="tx_edit"),
        ],
        [
            InlineKeyboardButton("❌ Batal", callback_data="tx_ignore"),
        ],
    ])

def _looks_like_explain_spending(text: str) -> bool:
    t = (text or "").lower()
    keys = ["diatas rata", "di atas rata", "rata2", "rata-rata", "datanya dari mana", "data nya dari mana", "dari mana", "overspending", "boros"]
    return any(k in t for k in keys)

def _is_export_request(text: str) -> bool:
    t = (text or "").lower()
    keys = ["export", "ekspor", "csv", "download data", "unduh data", "backup data"]
    return any(k in t for k in keys)

def _export_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yakin export", callback_data="export_confirm"),
            InlineKeyboardButton("❌ Tidak", callback_data="export_cancel"),
        ]
    ])

def _looks_like_payment_method(text: str) -> str:
    t = (text or "").lower()
    if "qris" in t:
        return "QRIS"
    if "cash" in t or "tunai" in t:
        return "Cash"
    if "debit" in t:
        return "Debit"
    if "kredit" in t or "credit" in t:
        return "Kredit"
    if "ovo" in t:
        return "OVO"
    if "gopay" in t or "go pay" in t:
        return "GoPay"
    if "dana" in t:
        return "DANA"
    if "shopeepay" in t or "shopee pay" in t:
        return "ShopeePay"
    if "transfer" in t:
        return "Transfer"
    return ""

async def _explain_spending(update: Update):
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

def _is_budget_query(text: str) -> bool:
    t = (text or "").lower()
    keys = ["sisa budget", "cek budget", "anggaran", "kuota", "limit", "sisa uang"]
    return any(k in t for k in keys)

async def _roast_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Viral Feature: Roast My Wallet
    AI will analyze spending habits and give a savage/funny commentary.
    """
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    await update.message.reply_text("🔥 **Sedang menyiapkan bahan roasting...**", parse_mode='Markdown')
    
    try:
        # 1. Fetch recent data
        txs = db.get_sliding_window_transactions(user_id, days=30)
        if not txs:
            await update.message.reply_text("Dompetmu terlalu bersih untuk di-roast. Catat dulu sana!")
            return
            
        # 2. Summarize for AI
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
        
        # 3. Call AI
        roast = await premium_ai._call_llm(
            system_prompt="You are a stand-up comedian roasting bad financial habits. Use Indonesian slang.",
            user_prompt=prompt
        )
        
        await update.message.reply_text(roast, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Roast error: {e}")
        await update.message.reply_text("Gagal roasting. AI-nya lagi gak tega.")

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
        # Pre-check for simple NLP intent before heavy AI call
        simple_intent = nlp.classify_intent(text)
        
        if simple_intent.get("intent") == "ROAST_WALLET":
            await _roast_wallet(update, context)
            return

        if simple_intent.get("intent") == "EXPORT_DATA":
            await export_data(update, context)
            return

        # New Intent Handlers
        if simple_intent.get("intent") == "WHAT_IF":
            # Extract params for what-if (amount, desc)
            # Since NLP regex for this is complex, we might rely on args or simple split
            # For now, let's redirect to what_if_simulator but we need args parsing logic
            # Simplification: pass full text to handler and let it re-parse or use regex
            from handlers.finance import what_if_simulator
            # We need to construct context.args from text
            # Remove trigger words
            clean = text.lower()
            for w in ["what if", "simulasi", "kalau", "kalo", "misal"]:
                clean = clean.replace(w, "")
            parts = clean.strip().split()
            if parts:
                context.args = parts
                await what_if_simulator(update, context)
            else:
                await update.message.reply_text("Contoh pakai: `kalo beli hp 5jt`")
            return

        if simple_intent.get("intent") == "SET_MODE":
            mode = simple_intent.get("value")
            from handlers.commands import set_persona_command
            context.args = [mode]
            await set_persona_command(update, context)
            return
            
        if simple_intent.get("intent") == "SET_REMINDER":
            mode = simple_intent.get("value")
            from handlers.commands import reminder_settings
            context.args = [mode]
            await reminder_settings(update, context)
            return

        if _is_budget_query(text):
            msg = budget_mgr.check_budget_status(user_db.id)
            await update.message.reply_text(msg, parse_mode='Markdown')
            return

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
                return
            if state == "WAITING_EDIT_DATE":
                t = (text or "").strip()
                if len(t) >= 8:
                    pending_tx["date"] = t
                    context.user_data["pending_tx"] = pending_tx
                    context.user_data.pop("state", None)
                    await update.message.reply_text(_tx_preview_message(pending_tx), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
                else:
                    await update.message.reply_text("Format tanggal belum kebaca. Contoh: `16-11-2015` atau `2015-11-16`.")
                return

        if pending_tx and not state:
            pm = _looks_like_payment_method(text)
            if pm:
                pending_tx["payment_method"] = pm
                context.user_data["pending_tx"] = pending_tx
                await update.message.reply_text(_tx_preview_message(pending_tx), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
                return

        if _is_export_request(text):
            context.user_data["pending_action"] = {"type": "export_all"}
            await update.message.reply_text(
                "📥 **Export Data (CSV)**\n\nAku akan kirim semua transaksi kamu dalam 1 file CSV.\nYakin mau export sekarang?",
                parse_mode="Markdown",
                reply_markup=_export_confirm_keyboard(),
            )
            return

        if _looks_like_explain_spending(text):
            await _explain_spending(update)
            return

        if await tutorial_mode.handle_text(update, context, text):
            return

        if tutorial_mode.is_tutorial_request(text):
            await update.message.reply_text(tutorial_mode.intro_text(), parse_mode="Markdown", reply_markup=tutorial_mode.intro_keyboard())
            return

        premium_response = await asyncio.wait_for(premium_ai.process_interaction(user_id, text, user_name), timeout=AI_TIMEOUT_SECONDS)
        intent = premium_response.intent
        
        response_msg = premium_response.suggested_response
        if intent == "cancel":
            structured = premium_response.structured_data or {}
            await _send_cancel_flow(update, context, user_db, structured, text)
            return
        
        if intent == "record" and premium_response.structured_data:
            data = premium_response.structured_data
            amount = data.get("amount", 0)
            try:
                amount = float(amount) if amount is not None else 0.0
            except Exception:
                amount = 0.0
            if amount <= 0:
                fallback = parse_primary_amount_id(text)
                if fallback:
                    amount = float(fallback)
            
            if amount <= 0:
                logger.warning(f"Skipping transaction with amount {amount} for user {user_id}")
                response_msg = premium_response.suggested_response or "Hmm, nominalnya berapa ya kak? Aku belum nangkep nih. 🤔"
            else:
                try:
                    is_duplicate = await premium_ai.check_reconciliation(user_id, data)
                    if is_duplicate:
                        response_msg = "⚠️ **Potensi Duplikat Terdeteksi!**\nTransaksi serupa baru saja dicatat. Yakin mau simpan lagi?"
                    else:
                        pending = {
                            "amount": float(amount),
                            "category": data.get("category", "Lain-lain"),
                            "merchant": data.get("description", text),
                            "date": datetime.now().strftime("%d-%m-%Y"),
                            "payment_method": data.get("payment_method", None),
                        }
                        context.user_data["pending_tx"] = pending
                        context.user_data.pop("state", None)
                        await update.message.reply_text(_tx_preview_message(pending), parse_mode="Markdown", reply_markup=_tx_preview_keyboard())
                        return
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
        try:
            key = f"ocr_rl:{user_id}"
            ok = premium_ai.redis.client.set(key, str(int(time.time())), ex=OCR_RATE_LIMIT_SECONDS, nx=True)
            if not ok:
                await update.message.reply_text(f"OCR lagi cooldown. Coba lagi dalam {OCR_RATE_LIMIT_SECONDS} detik ya.")
                return
        except Exception:
            pass

        # 1. OCR Extraction
        async with OCR_SEMAPHORE:
            cache_key = None
            try:
                import hashlib
                with open(photo_path, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                cache_key = f"ocr_cache:{h}"
                cached = premium_ai.redis.client.get(cache_key)
                if cached:
                    result = json.loads(cached)
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(ocr.process_receipt, photo_path, low_mem),
                        timeout=OCR_HANDLER_TIMEOUT_SECONDS
                    )
                    if result:
                        premium_ai.redis.client.set(cache_key, json.dumps(result), ex=7 * 24 * 3600)
            except Exception:
                result = await asyncio.wait_for(
                    asyncio.to_thread(ocr.process_receipt, photo_path, low_mem),
                    timeout=OCR_HANDLER_TIMEOUT_SECONDS
                )
            
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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        logger.error(f"Document Error: {e}")
        await update.message.reply_text("Gagal memproses dokumen.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
