import asyncio
import json
import os
import time
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config import CATEGORIES
from core import db, budget_mgr, premium_ai

TUTORIAL_STEPS = [
    {"id": "tx1", "requires_input": True, "card": "🎓 1/20 ▱▱▱▱▱\nKetik transaksi: `kopi 25rb`"},
    {"id": "inc1", "requires_input": True, "card": "🎓 2/20 ▰▱▱▱▱\nKetik pemasukan: `gaji 7jt`"},
    {"id": "bud1", "requires_input": True, "card": "🎓 3/20 ▰▰▱▱▱\nSet budget: `Makanan 1jt`"},
    {"id": "bud2", "requires_input": True, "card": "🎓 4/20 ▰▰▰▱▱\nSet budget lagi: `Transportasi 300rb`"},
    {"id": "budget", "requires_input": False, "card": "🎓 5/20 ▰▰▰▰▱\nKlik Lanjut untuk cek budget"},
    {"id": "report", "requires_input": False, "card": "🎓 6/20 ▰▰▰▰▱\nKlik Lanjut untuk laporan"},
    {"id": "insight", "requires_input": False, "card": "🎓 7/20 ▰▰▰▰▱\nKlik Lanjut untuk AI tips"},
    {"id": "history", "requires_input": False, "card": "🎓 8/20 ▰▰▰▰▱\nKlik Lanjut untuk riwayat"},
    {"id": "export", "requires_input": False, "card": "🎓 9/20 ▰▰▰▰▱\nKlik Lanjut untuk export CSV"},
    {"id": "scan_tip", "requires_input": False, "card": "🎓 10/20 ▰▰▰▰▱\nTips: foto bagian TOTAL"},
    {"id": "cancel", "requires_input": True, "card": "🎓 11/20 ▰▰▰▰▱\nKetik: `batal transaksi terakhir`"},
    {"id": "cat_tip", "requires_input": False, "card": "🎓 12/20 ▰▰▰▰▱\nTip: singkat + nominal"},
    {"id": "dup_tip", "requires_input": False, "card": "🎓 13/20 ▰▰▰▰▱\nKalau dobel, bot ngingetin"},
    {"id": "budget_tip", "requires_input": False, "card": "🎓 14/20 ▰▰▰▰▱\nSet budget biar kebaca"},
    {"id": "undo_tip", "requires_input": False, "card": "🎓 15/20 ▰▰▰▰▱\nBisa `hapus #ID` juga"},
    {"id": "profile", "requires_input": False, "card": "🎓 16/20 ▰▰▰▰▱\nKlik Lanjut untuk profil"},
    {"id": "settings", "requires_input": False, "card": "🎓 17/20 ▰▰▰▰▱\nKlik Lanjut untuk settings"},
    {"id": "shortcut", "requires_input": False, "card": "🎓 18/20 ▰▰▰▰▱\nShortcut: ketik tanpa menu"},
    {"id": "wrap", "requires_input": False, "card": "🎓 19/20 ▰▰▰▰▱\nKlik Lanjut untuk selesai"},
    {"id": "done", "requires_input": False, "card": "🎓 20/20 ▰▰▰▰▰\nSelesai ✅"},
]

AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "25"))
TUTORIAL_TIMEOUT_SECONDS = int(os.getenv("TUTORIAL_TIMEOUT_SECONDS", "900"))
TUTORIAL_TYPING_SECONDS = float(os.getenv("TUTORIAL_TYPING_SECONDS", "1.2"))
TUTORIAL_TRANSITION_SECONDS = float(os.getenv("TUTORIAL_TRANSITION_SECONDS", "0.4"))

def is_tutorial_request(text: str) -> bool:
    t = (text or "").strip().lower()
    keys = [
        "tutorial", "tutor", "cara pakai", "cara pake", "guide", "panduan",
        "gimana pakenya", "gimana makenya", "onboarding", "ajari", "ajarin"
    ]
    return any(k in t for k in keys)

def _state(user_data: dict):
    s = user_data.get("tutorial_mode")
    if isinstance(s, dict) and s.get("active"):
        return s
    return None

def _log(user_id: int, event: str, payload: dict):
    try:
        entry = {"event": event, "ts": datetime.utcnow().isoformat() + "Z", "data": payload or {}}
        premium_ai.redis.client.lpush(f"tutorial_events:{user_id}", json.dumps(entry))
        premium_ai.redis.client.ltrim(f"tutorial_events:{user_id}", 0, 500)
    except Exception:
        pass

async def _send_card(message, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup):
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(TUTORIAL_TYPING_SECONDS)
    except Exception:
        pass
    await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    try:
        await asyncio.sleep(TUTORIAL_TRANSITION_SECONDS)
    except Exception:
        pass

def _kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➡️ Lanjut", callback_data="tut_next"),
            InlineKeyboardButton("🔁 Ulangi", callback_data="tut_repeat"),
            InlineKeyboardButton("⏭️ Lewati", callback_data="tut_skip"),
        ],
        [
            InlineKeyboardButton("🆘 Help", callback_data="tut_help"),
            InlineKeyboardButton("🚪 Keluar", callback_data="tut_exit"),
        ],
    ])

def intro_text() -> str:
    return "🎓 Tutorial Mode\nPilih: Pemula / Cepat"

def intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Pemula", callback_data="tut_start_beginner"),
            InlineKeyboardButton("⚡ Cepat", callback_data="tut_start_fast"),
        ],
        [
            InlineKeyboardButton("🚀 Menu", callback_data="suggest_help"),
        ],
    ])

def _current_step(state: dict):
    idx = int(state.get("idx") or 0)
    idx = max(0, min(idx, len(TUTORIAL_STEPS) - 1))
    return idx, TUTORIAL_STEPS[idx]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    user_id = update.effective_user.id
    context.user_data["tutorial_mode"] = {
        "active": True,
        "idx": 0,
        "mode": mode,
        "last_ts": time.time(),
        "errors": 0,
    }
    _log(user_id, "started", {"mode": mode})
    idx, step = _current_step(context.user_data["tutorial_mode"])
    await _send_card(update.callback_query.message, context, step["card"], _kb())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> bool:
    if action == "tutorial_quickstart":
        await start(update, context, "beginner")
        return True
    if not action.startswith("tut_"):
        return False

    query = update.callback_query
    user_id = update.effective_user.id
    st = _state(context.user_data)
    if action in ("tut_start_beginner", "tut_start_fast"):
        mode = "beginner" if action == "tut_start_beginner" else "fast"
        await start(update, context, mode)
        return True

    if not st:
        await query.message.reply_text("Tutorial belum aktif. Ketik `tutorial`.", parse_mode="Markdown")
        return True

    st["last_ts"] = time.time()
    idx, step = _current_step(st)

    if action == "tut_exit":
        context.user_data.pop("tutorial_mode", None)
        _log(user_id, "exited", {"idx": idx})
        await query.message.reply_text("Tutorial dihentikan. Ketik `tutorial` kalau mau lanjut lagi.")
        return True

    if action == "tut_help":
        await _send_card(query.message, context, "🆘 Help\nContoh: `kopi 25rb`", _kb())
        return True

    if action == "tut_repeat":
        await _send_card(query.message, context, step["card"], _kb())
        _log(user_id, "repeat", {"idx": idx})
        return True

    if action == "tut_skip":
        st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
        context.user_data["tutorial_mode"] = st
        _log(user_id, "skip", {"from": idx, "to": st["idx"]})
        idx2, step2 = _current_step(st)
        await _send_card(query.message, context, step2["card"], _kb())
        return True

    if action == "tut_next":
        if step.get("requires_input"):
            await _send_card(query.message, context, "⛔ Jawab dulu ya\nLalu klik Lanjut", _kb())
            return True

        await _run_step_side_effect(query.message, context, step.get("id"))
        st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
        context.user_data["tutorial_mode"] = st
        _log(user_id, "next", {"from": idx, "to": st["idx"]})

        idx2, step2 = _current_step(st)
        await _send_card(query.message, context, step2["card"], _kb())

        if step2.get("id") == "done":
            context.user_data.pop("tutorial_mode", None)
            _log(user_id, "completed", {})
        return True

    return True

async def _run_step_side_effect(message, context: ContextTypes.DEFAULT_TYPE, step_id: str):
    try:
        user_id = message.chat_id
        user_db = db.get_or_create_user(user_id, "")
        if step_id == "budget":
            status = budget_mgr.check_budget_status(user_db.id, "Semua")
            if status:
                await _send_card(message, context, "📊 Budget\nCek ringkas di atas", _kb())
                await message.reply_text(status)
        elif step_id == "report":
            msg = budget_mgr.generate_report(user_db.id, "monthly")
            await _send_card(message, context, "📈 Laporan\nBulan ini (ringkas)", _kb())
            await message.reply_text(msg)
        elif step_id == "insight":
            await _send_card(message, context, "🧠 AI Tips\nKlik AI Insights menu", _kb())
        elif step_id == "history":
            from handlers.transactions import history
            fake_update = Update(update_id=0, message=message)
            await history(fake_update, context)
        elif step_id == "export":
            await _send_card(message, context, "📥 Export\nPakai /export", _kb())
        elif step_id == "profile":
            await _send_card(message, context, "👤 Profil\nKlik menu Profil", _kb())
        elif step_id == "settings":
            await _send_card(message, context, "⚙️ Settings\nKlik menu Settings", _kb())
    except Exception:
        pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    st = _state(context.user_data)
    if not st:
        return False

    user_id = update.effective_user.id
    last_ts = float(st.get("last_ts") or 0)
    if last_ts and (time.time() - last_ts) > TUTORIAL_TIMEOUT_SECONDS:
        _log(user_id, "timeout", {"idx": int(st.get("idx") or 0)})
        context.user_data.pop("tutorial_mode", None)
        await update.message.reply_text("Tutorial timeout.\nKetik `tutorial` untuk mulai lagi.", parse_mode="Markdown")
        return True

    st["last_ts"] = time.time()
    idx, step = _current_step(st)

    if not step.get("requires_input"):
        await _send_card(update.message, context, "➡️ Klik Lanjut\nPakai tombol ya", _kb())
        return True

    ok = False
    t = (text or "").strip()
    low = t.lower()

    if step["id"] == "tx1":
        ok = _looks_like_amount(low)
    elif step["id"] == "inc1":
        ok = _looks_like_amount(low)
    elif step["id"] in ("bud1", "bud2"):
        ok = _looks_like_budget(low)
    elif step["id"] == "cancel":
        ok = any(k in low for k in ("batal", "undo", "hapus"))
    else:
        ok = True

    if not ok:
        st["errors"] = int(st.get("errors") or 0) + 1
        _log(user_id, "invalid", {"idx": idx, "text": t[:80]})
        await _send_card(update.message, context, "❌ Belum kebaca\nKlik Ulangi", _kb())
        context.user_data["tutorial_mode"] = st
        return True

    await _apply_input(update, context, step["id"], t)
    _log(user_id, "answer", {"idx": idx})
    st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
    context.user_data["tutorial_mode"] = st
    idx2, step2 = _current_step(st)
    await _send_card(update.message, context, "✅ Oke\nLanjut ya", _kb())
    await _send_card(update.message, context, step2["card"], _kb())
    if step2.get("id") == "done":
        context.user_data.pop("tutorial_mode", None)
        _log(user_id, "completed", {})
    return True

def _looks_like_amount(text: str) -> bool:
    return any(ch.isdigit() for ch in text) and any(k in text for k in ("rb", "ribu", "k", "jt", "juta", "rp")) or text.isdigit()

def _looks_like_budget(text: str) -> bool:
    has_cat = any(c.lower() in text for c in CATEGORIES)
    has_num = any(ch.isdigit() for ch in text)
    return has_cat and has_num

async def _apply_input(update: Update, context: ContextTypes.DEFAULT_TYPE, step_id: str, text: str):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)

    if step_id == "inc1":
        amount = _extract_amount(text)
        if amount:
            try:
                db.add_monthly_income(user_db.id, amount)
            except Exception:
                pass
        return

    if step_id in ("bud1", "bud2"):
        cat = None
        low = text.lower()
        for c in CATEGORIES:
            if c.lower() in low:
                cat = c
                break
        amount = _extract_amount(text)
        if cat and amount:
            try:
                db.set_budget(user_db.id, cat, amount)
            except Exception:
                pass
        return

    if step_id == "tx1":
        try:
            pr = await asyncio.wait_for(
                premium_ai.process_interaction(user_id, text, update.effective_user.first_name),
                timeout=AI_TIMEOUT_SECONDS,
            )
            if pr and pr.intent == "record" and pr.structured_data:
                data = pr.structured_data
                amt = float(data.get("amount") or 0)
                if amt > 0:
                    db.add_transaction(
                        user_id=user_db.id,
                        amount=amt,
                        category=data.get("category", "Lain-lain"),
                        description=data.get("description", text),
                        trans_type=data.get("type", "expense"),
                    )
        except Exception:
            pass

def _extract_amount(text: str):
    t = (text or "").lower().replace("rp", "").replace(" ", "")
    digits = "".join([c for c in t if c.isdigit()])
    if not digits:
        return None
    try:
        val = float(digits)
    except Exception:
        return None
    if "jt" in t or "juta" in t:
        return val * 1000000
    if "rb" in t or "ribu" in t or "k" in t:
        return val * 1000
    return val
