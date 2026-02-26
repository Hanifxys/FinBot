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
from modules.amounts import parse_primary_amount_id

TUTORIAL_STEPS = [
    {"id": "tx1", "requires_input": True, "prompt": "Ketik transaksi: `kopi 25rb`"},
    {"id": "inc1", "requires_input": True, "prompt": "Ketik pemasukan: `gaji 7jt`"},
    {"id": "bud1", "requires_input": True, "prompt": "Set budget: `Makanan 1jt`"},
    {"id": "bud2", "requires_input": True, "prompt": "Set budget lagi: `Transportasi 300rb`"},
    {"id": "budget", "requires_input": False, "prompt": "Cek budget ringkas"},
    {"id": "report", "requires_input": False, "prompt": "Lihat laporan ringkas"},
    {"id": "insight", "requires_input": False, "prompt": "AI tips (biar hemat)"},
    {"id": "history", "requires_input": False, "prompt": "Lihat riwayat (ID)"},
    {"id": "export", "requires_input": False, "prompt": "Export CSV (opsional)"},
    {"id": "scan_tip", "requires_input": False, "prompt": "Tip OCR: fokus bagian TOTAL"},
    {"id": "cancel", "requires_input": True, "prompt": "Latihan: `batal transaksi terakhir`"},
    {"id": "cat_tip", "requires_input": False, "prompt": "Tip: singkat + nominal"},
    {"id": "dup_tip", "requires_input": False, "prompt": "Kalau dobel, bot ngingetin"},
    {"id": "budget_tip", "requires_input": False, "prompt": "Budget bikin kontrol rapih"},
    {"id": "undo_tip", "requires_input": False, "prompt": "Bisa juga: `hapus #ID`"},
    {"id": "profile", "requires_input": False, "prompt": "Cek profil & rank"},
    {"id": "settings", "requires_input": False, "prompt": "Cek settings"},
    {"id": "shortcut", "requires_input": False, "prompt": "Shortcut: ketik tanpa menu"},
    {"id": "wrap", "requires_input": False, "prompt": "Wrap-up tutorial"},
    {"id": "done", "requires_input": False, "prompt": "Selesai ✅"},
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

def _pick(user_id: int, idx: int, items):
    if not items:
        return ""
    try:
        return items[(int(user_id) + int(idx)) % len(items)]
    except Exception:
        return items[0]

def _progress_line(idx: int, total: int) -> str:
    pos = max(1, min(idx + 1, total))
    blocks = 5
    filled = int(round((pos / max(1, total)) * blocks))
    filled = max(0, min(filled, blocks))
    bar = "▰" * filled + "▱" * (blocks - filled)
    return f"🎓 {pos}/{total} {bar}"

def _render_card(user_id: int, idx: int, step: dict, state: dict) -> str:
    total = len(TUTORIAL_STEPS)
    vibe = _pick(
        user_id,
        idx,
        ["Gas tipis", "Oke, fokus", "Nice", "Mantap", "Yuk lanjut", "Sip"],
    )
    prompt = step.get("prompt") or ""
    if step.get("requires_input"):
        second = prompt
    else:
        second = f"{vibe}: auto lanjut…"
        if prompt:
            second = f"{prompt} — auto lanjut…"
    line1 = _progress_line(idx, total)
    line2 = second
    if "\n" in line2:
        line2 = line2.split("\n", 1)[0]
    return f"{line1}\n{line2}"

def _keyboard_for(step: dict) -> InlineKeyboardMarkup:
    if step.get("id") == "done":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
        ])
    if step.get("requires_input"):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔁 Ulangi", callback_data="tut_repeat"),
                InlineKeyboardButton("⏭️ Lewati", callback_data="tut_skip"),
            ],
            [
                InlineKeyboardButton("🆘 Help", callback_data="tut_help"),
                InlineKeyboardButton("🚪 Keluar", callback_data="tut_exit"),
            ],
        ])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭️ Lewati", callback_data="tut_skip"),
        ],
        [
            InlineKeyboardButton("🆘 Help", callback_data="tut_help"),
            InlineKeyboardButton("🚪 Keluar", callback_data="tut_exit"),
        ],
    ])

async def _typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(TUTORIAL_TYPING_SECONDS)
    except Exception:
        return

async def _upsert(context: ContextTypes.DEFAULT_TYPE, state: dict, chat_id: int, text: str, keyboard: InlineKeyboardMarkup):
    msg_id = state.get("msg_id")
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(msg_id),
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return
        except Exception:
            state["msg_id"] = None
    try:
        sent = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=keyboard)
        state["msg_id"] = getattr(sent, "message_id", None)
    except Exception:
        return

def intro_text() -> str:
    return "🎓 Tutorial Mode\nPilih gaya: **Pemula** / **Cepat**"

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
    st = {
        "active": True,
        "idx": 0,
        "mode": mode,
        "last_ts": time.time(),
        "errors": 0,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
        "msg_id": None,
    }
    if update.callback_query and update.callback_query.message:
        st["chat_id"] = update.callback_query.message.chat_id
        st["msg_id"] = update.callback_query.message.message_id
    context.user_data["tutorial_mode"] = st
    _log(user_id, "started", {"mode": mode})
    idx, step = _current_step(st)
    chat_id = int(st.get("chat_id") or update.effective_chat.id)
    await _typing(context, chat_id)
    await _upsert(context, st, chat_id, _render_card(user_id, idx, step, st), _keyboard_for(step))
    try:
        await asyncio.sleep(TUTORIAL_TRANSITION_SECONDS)
    except Exception:
        pass

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
        await query.message.reply_text("Tutorial belum aktif.\nKetik `tutorial`", parse_mode="Markdown")
        return True

    st["last_ts"] = time.time()
    idx, step = _current_step(st)
    chat_id = int(st.get("chat_id") or (query.message.chat_id if query and query.message else update.effective_chat.id))

    if action == "tut_exit":
        context.user_data.pop("tutorial_mode", None)
        _log(user_id, "exited", {"idx": idx})
        await _typing(context, chat_id)
        await query.message.reply_text("Tutorial dihentikan.\nKetik `tutorial` lagi.", parse_mode="Markdown")
        return True

    if action == "tut_help":
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, "🆘 Help\nContoh: `kopi 25rb`", _keyboard_for(step))
        return True

    if action == "tut_repeat":
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, _render_card(user_id, idx, step, st), _keyboard_for(step))
        _log(user_id, "repeat", {"idx": idx})
        return True

    if action == "tut_skip":
        st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
        context.user_data["tutorial_mode"] = st
        _log(user_id, "skip", {"from": idx, "to": st["idx"]})
        idx2, step2 = _current_step(st)
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, _render_card(user_id, idx2, step2, st), _keyboard_for(step2))
        await _autoplay(update, context, st)
        return True

    if action == "tut_next":
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, "✅ Oke\nSekarang auto lanjut…", _keyboard_for(step))
        await _autoplay(update, context, st)
        return True

    return True

async def _run_step_side_effect(message, context: ContextTypes.DEFAULT_TYPE, step_id: str):
    try:
        user_id = message.chat_id
        user_db = db.get_or_create_user(user_id, "")
        if step_id == "budget":
            status = budget_mgr.check_budget_status(user_db.id, "Semua")
            if status:
                await message.reply_text(status)
        elif step_id == "report":
            msg = budget_mgr.generate_report(user_db.id, "monthly")
            await message.reply_text(msg)
        elif step_id == "insight":
            await message.reply_text("🧠 AI tips tersedia di menu.\nKlik **AI Insights**", parse_mode="Markdown")
        elif step_id == "history":
            from handlers.transactions import history
            fake_update = Update(update_id=0, message=message)
            await history(fake_update, context)
        elif step_id == "export":
            await message.reply_text("📥 Export: pakai `/export`", parse_mode="Markdown")
        elif step_id == "profile":
            await message.reply_text("👤 Profil: klik menu Profil", parse_mode="Markdown")
        elif step_id == "settings":
            await message.reply_text("⚙️ Settings: klik menu Settings", parse_mode="Markdown")
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
        await update.message.reply_text("Tutorial timeout.\nKetik `tutorial` lagi.", parse_mode="Markdown")
        return True

    st["last_ts"] = time.time()
    idx, step = _current_step(st)
    chat_id = int(st.get("chat_id") or update.effective_chat.id)

    if not step.get("requires_input"):
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, "⏳ Tunggu ya\nLagi lanjut…", _keyboard_for(step))
        await _autoplay(update, context, st)
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
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, "❌ Belum kebaca\nCoba format contoh ya.", _keyboard_for(step))
        context.user_data["tutorial_mode"] = st
        return True

    await _apply_input(update, context, step["id"], t)
    _log(user_id, "answer", {"idx": idx})
    st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
    context.user_data["tutorial_mode"] = st
    idx2, step2 = _current_step(st)
    await _typing(context, chat_id)
    ack = _ack_for(step.get("id"), t)
    await _upsert(context, st, chat_id, ack, _keyboard_for(step))
    try:
        await asyncio.sleep(TUTORIAL_TRANSITION_SECONDS)
    except Exception:
        pass
    await _typing(context, chat_id)
    await _upsert(context, st, chat_id, _render_card(user_id, idx2, step2, st), _keyboard_for(step2))
    if step2.get("id") == "done":
        context.user_data.pop("tutorial_mode", None)
        _log(user_id, "completed", {})
    await _autoplay(update, context, st)
    return True

def _ack_for(step_id: str, raw: str) -> str:
    t = (raw or "").strip()
    amt = _extract_amount(t) or 0
    if step_id == "tx1" and amt > 0:
        return f"✅ Masuk\nRp{amt:,.0f} tercatat"
    if step_id == "inc1" and amt > 0:
        needs = amt * 0.5
        wants = amt * 0.3
        save = amt * 0.2
        return f"✅ Gaji set\n50/30/20: {needs:,.0f}/{wants:,.0f}/{save:,.0f}"
    if step_id in ("bud1", "bud2") and amt > 0:
        cat = None
        low = t.lower()
        for c in CATEGORIES:
            if c.lower() in low:
                cat = c
                break
        cat = cat or "Kategori"
        return f"✅ Budget ok\n{cat}: Rp{amt:,.0f}"
    if step_id == "cancel":
        return "✅ Siap\nLanjut ya"
    return _pick(0, 0, ["✅ Oke", "✅ Sip", "✅ Mantap", "✅ Gas"]) + "\nLanjut…"

async def _autoplay(update: Update, context: ContextTypes.DEFAULT_TYPE, st: dict):
    if not st or not st.get("active"):
        return
    try:
        chat_id = int(st.get("chat_id") or (update.effective_chat.id if update.effective_chat else 0))
        user_id = int(update.effective_user.id)
    except Exception:
        return

    while True:
        idx, step = _current_step(st)
        if step.get("requires_input") or step.get("id") == "done":
            return

        await _run_step_side_effect(update.effective_message, context, step.get("id"))
        st["idx"] = min(idx + 1, len(TUTORIAL_STEPS) - 1)
        context.user_data["tutorial_mode"] = st
        _log(user_id, "auto_next", {"from": idx, "to": st["idx"]})

        idx2, step2 = _current_step(st)
        await _typing(context, chat_id)
        await _upsert(context, st, chat_id, _render_card(user_id, idx2, step2, st), _keyboard_for(step2))

        if step2.get("id") == "done":
            context.user_data.pop("tutorial_mode", None)
            _log(user_id, "completed", {})
            return
        if step2.get("requires_input"):
            return

def _looks_like_amount(text: str) -> bool:
    return parse_primary_amount_id(text) is not None

def _looks_like_budget(text: str) -> bool:
    has_cat = any(c.lower() in text for c in CATEGORIES)
    has_amt = parse_primary_amount_id(text) is not None
    return has_cat and has_amt

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
    return parse_primary_amount_id(text)
