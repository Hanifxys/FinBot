"""
handlers/callbacks.py — FinBot Pro Telegram Callback Handler
Refactored: handler registry pattern, no mutation, full error handling, typed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from config import CATEGORIES
from core import budget_mgr, db, rules, visual_reporter
from handlers import tutorial_mode
from handlers.transactions import duplicate_transaction, history, load_pending_update
from utils.dashboard import update_pinned_dashboard
from utils.onboarding import send_onboarding_hint
from utils.executor import execute_code

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
CallbackHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, str],
    Coroutine[Any, Any, None],
]

# ---------------------------------------------------------------------------
# Keyboards (pure functions — no side effects)
# ---------------------------------------------------------------------------

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
            [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")],
        ],
        resize_keyboard=True,
    )


def _post_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Cek Budget", callback_data="suggest_budget"),
            InlineKeyboardButton("📈 Laporan", callback_data="report_monthly"),
        ],
        [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
    ])


def _report_nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Detail Budget", callback_data="suggest_budget"),
            InlineKeyboardButton("💡 Tips Hemat", callback_data="suggest_insight"),
        ],
        [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
    ])


def _cancel_candidates_kb(candidates: list) -> InlineKeyboardMarkup:
    rows = []
    for c in candidates[:5]:
        txid = c.get("id")
        amount = c.get("amount", 0)
        cat = c.get("category", "")
        desc = (c.get("description") or "-")[:25] + ("..." if len(c.get("description") or "") > 25 else "")
        rows.append([InlineKeyboardButton(
            f"#{txid} Rp{amount:,.0f} · {cat} · {desc}",
            callback_data=f"cancel_pick:{txid}",
        )])
    rows.append([InlineKeyboardButton("❌ Tidak jadi", callback_data="cancel_abort")])
    return InlineKeyboardMarkup(rows)


def _cancel_confirm_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Batalkan (1-klik)", callback_data="cancel_confirm"),
            InlineKeyboardButton("🔁 Pilih lain", callback_data="cancel_choose"),
        ],
        [
            InlineKeyboardButton("📜 Riwayat", callback_data="open_history"),
            InlineKeyboardButton("❌ Tidak jadi", callback_data="cancel_abort"),
        ],
    ])


def _edit_field_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Nominal", callback_data="edit_amount"),
            InlineKeyboardButton("Kategori", callback_data="edit_category"),
        ],
        [
            InlineKeyboardButton("Tanggal", callback_data="edit_date"),
            InlineKeyboardButton("Abaikan", callback_data="tx_ignore"),
        ],
    ])


def _category_select_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(cat, callback_data=f"set_cat_{cat}") for cat in CATEGORIES[i : i + 2]]
        for i in range(0, len(CATEGORIES), 2)
    ]
    rows.append([InlineKeyboardButton("Batal", callback_data="tx_edit")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Tutorial helpers
# ---------------------------------------------------------------------------

def _tut_bar(step: int, total: int) -> str:
    if total <= 0:
        return ""
    filled = max(0, min(10, round((max(0, min(step, total)) / total) * 10)))
    return "█" * filled + "░" * (10 - filled)


def _tut_kb(active: bool = True) -> InlineKeyboardMarkup:
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
        [InlineKeyboardButton("🚪 Keluar", callback_data="tutorial_exit")],
    ])


def _tut_step_msg(step: int, total: int, mode: str) -> str:
    bar = _tut_bar(step - 1, total)
    base = f"🎓 **Tutorial Mode**\n\nProgress: `{bar}` {step - 1}/{total}\n\n"
    steps = {
        1: (
            "Step 1 — Catat transaksi pertama\nCoba ketik: `kopi 25rb` atau `makan 40000`",
            "\n\nTips: tulis singkat + nominal, misalnya `parkir 5rb`.",
        ),
        2: (
            "Step 2 — Set gaji bulanan\nKetik: `gaji 7jt` atau `7000000`",
            "\n\nKalau kamu freelancer, isi rata-rata per bulan.",
        ),
        3: (
            "Step 3 — Set budget kategori\nKetik: `Makanan 1jt` atau `Transportasi 300rb`",
            "\n\nTips: mulai dari kategori paling sering kamu pakai.",
        ),
        4: (
            "Step 4 — Cek budget\nAku tampilkan ringkasan budget kamu. Balas: `lanjut`.",
            "",
        ),
        5: (
            "Step 5 — Latihan pembatalan\nKetik: `batal transaksi terakhir` lalu tekan tombol konfirmasi.",
            "",
        ),
    }
    text, beginner_tip = steps.get(step, ("", ""))
    if mode == "beginner" and beginner_tip:
        text += beginner_tip
    return base + text


_TUTORIAL_SECTIONS: Dict[str, str] = {
    "quickstart": (
        "⚡ **Quickstart (Step-by-step)**\n\n"
        "1) **Catat pengeluaran** — Ketik: `kopi 25rb` / `makan 40rb`\n"
        "   Atau: klik **📸 Scan Struk** lalu kirim foto.\n\n"
        "2) **Catat pemasukan** — Ketik: `gajian 7jt` atau `/setgaji 7000000`\n\n"
        "3) **Cek budget** — Klik **📊 Cek Budget** atau ketik `cek budget`\n\n"
        "4) **Lihat laporan** — Klik **📈 Laporan** atau `/summary monthly`\n\n"
        "5) **Minta insight** — Klik **🧠 AI Insights**"
    ),
    "scan": (
        "📸 **Scan Struk (Biar Cepet & Akurat)**\n\n"
        "1) Klik **📸 Scan Struk**\n"
        "2) Kirim foto struk yang terang, tidak blur, tidak miring.\n"
        "3) Bot akan baca **merchant + total**, lalu auto-catat.\n\n"
        "Tips: kalau struk panjang, foto bagian yang ada tulisan **TOTAL**."
    ),
    "cancel": (
        "↩️ **Pembatalan Transaksi (1-klik)**\n\n"
        "Ketik: `batal transaksi terakhir` / `batal yang 25rb` / `hapus #123`\n\n"
        "Bot akan tampilkan kandidat + tombol ✅ Batalkan / 🔁 Pilih lain / ❌ Tidak jadi\n\n"
        "Tips: sertakan nominal agar lebih akurat: `batal yang 25000`."
    ),
    "reports": (
        "📊 **Budget & Laporan**\n\n"
        "• Klik **📊 Cek Budget** untuk ringkasan cepat\n"
        "• Klik **📈 Laporan** untuk pilih periode\n"
        "• `/history` untuk lihat ID transaksi\n"
        "• `/export` untuk CSV"
    ),
    "settings": (
        "⚙️ **Pengaturan Penting**\n\n"
        "• `/setgaji 7000000` — set pemasukan bulanan\n"
        "• `/setbudget [Kategori] [Nominal]` — limit kategori\n"
        "• `/budgetalert [Kat] [Warn%] [Limit%]` — notifikasi\n\n"
        "Contoh:\n"
        "• `/setbudget Makanan 1500000`\n"
        "• `/budgetalert Makanan 0.8 1.0`"
    ),
    "best": (
        "✅ **Best Practices**\n\n"
        "1) Catat segera setelah transaksi\n"
        "2) Pakai deskripsi singkat: `kopi`, `makan siang`, `ongkir`\n"
        "3) Set budget kategori untuk kontrol pengeluaran\n"
        "4) Kalau ragu kategori, tetap catat dulu\n"
        "5) Kalau salah catat, pakai `batal yang ...` secepatnya"
    ),
}


def _tutorial_content_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Quickstart", callback_data="tutorial_quickstart"),
            InlineKeyboardButton("📸 Scan Struk", callback_data="tutorial_scan"),
        ],
        [
            InlineKeyboardButton("↩️ Pembatalan", callback_data="tutorial_cancel"),
            InlineKeyboardButton("📊 Laporan", callback_data="tutorial_reports"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="tutorial_settings"),
            InlineKeyboardButton("✅ Best Practices", callback_data="tutorial_best"),
        ],
        [InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")],
    ])


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------

def _parse_date(date_str: Optional[str]) -> datetime:
    """Parse a date string, returning datetime.now() on any failure."""
    if not date_str:
        return datetime.now()
    try:
        cleaned = date_str.replace("/", "-")
        fmt = "%Y-%m-%d" if len(cleaned.split("-")[0]) == 4 else "%d-%m-%Y"
        return datetime.strptime(cleaned, fmt)
    except ValueError:
        logger.debug("Could not parse date string %r — using now()", date_str)
        return datetime.now()


# ---------------------------------------------------------------------------
# Redis audit helper (fire-and-forget, never raises)
# ---------------------------------------------------------------------------

def _redis_audit(key: str, payload: dict, max_len: int = 200) -> None:
    try:
        from core import premium_ai
        client = premium_ai.redis.client
        if client:
            client.lpush(key, json.dumps(payload))
            client.ltrim(key, 0, max_len)
    except Exception as exc:
        logger.debug("Redis audit failed key=%s: %s", key, exc)


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

class CallbackRouter:
    """
    Maps callback_data strings (exact or prefix) to async handler functions.
    Handlers receive (update, context, action) and are responsible for
    answering the query and replying — they do NOT call query.answer().
    """

    def __init__(self) -> None:
        self._exact: Dict[str, CallbackHandler] = {}
        self._prefix: list[tuple[str, CallbackHandler]] = []

    def exact(self, *actions: str):
        def decorator(fn: CallbackHandler) -> CallbackHandler:
            for a in actions:
                self._exact[a] = fn
            return fn
        return decorator

    def prefix(self, pfx: str):
        def decorator(fn: CallbackHandler) -> CallbackHandler:
            self._prefix.append((pfx, fn))
            return fn
        return decorator

    async def dispatch(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
    ) -> bool:
        """Return True if a handler was found and invoked."""
        handler = self._exact.get(action)
        if handler:
            await handler(update, context, action)
            return True
        for pfx, fn in self._prefix:
            if action.startswith(pfx):
                await fn(update, context, action)
                return True
        return False


router = CallbackRouter()


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------

# ── Export ──────────────────────────────────────────────────────────────────

@router.exact("export_csv")
async def _h_export_csv(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    ctx.user_data["pending_action"] = {"type": "export_all"}
    await query.edit_message_text(
        "📥 **Export Data (CSV)**\n\nAku akan kirim semua transaksi kamu dalam 1 file CSV.\nYakin mau export sekarang?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yakin export", callback_data="export_confirm"),
            InlineKeyboardButton("❌ Tidak", callback_data="export_cancel"),
        ]]),
    )


@router.exact("export_confirm")
async def _h_export_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    ctx.user_data.pop("pending_action", None)
    from handlers.transactions import export_data
    await query.edit_message_text("📥 Oke, lagi siapin CSV kamu…")
    await export_data(update, ctx)


@router.exact("export_cancel")
async def _h_export_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("pending_action", None)
    await update.callback_query.edit_message_text("Oke, export dibatalkan. ✅")


# ── Tutorial flow ────────────────────────────────────────────────────────────

@router.exact("tutorial_start_beginner", "tutorial_start_fast")
async def _h_tutorial_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    mode = "fast" if action == "tutorial_start_fast" else "beginner"
    total = 5
    ctx.user_data["tutorial_mode"] = {
        "active": True,
        "step": 1,
        "mode": mode,
        "total": total,
        "last_ts": datetime.now(tz=timezone.utc).timestamp(),
        "errors": 0,
    }
    _redis_audit(
        f"tutorial_events:{user_id}",
        {"event": "started", "ts": datetime.now(tz=timezone.utc).isoformat(), "data": {"mode": mode}},
        max_len=500,
    )
    await query.edit_message_text(
        _tut_step_msg(1, total, mode),
        parse_mode="Markdown",
        reply_markup=_tut_kb(True),
    )


@router.exact("tutorial_help")
async def _h_tutorial_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.message.reply_text(
        "🆘 **Bantuan Tutorial**\n\n"
        "Format aman yang pasti kebaca:\n"
        "- Transaksi: `kopi 25rb`\n"
        "- Gaji: `7000000`\n"
        "- Budget: `Makanan 1000000`\n"
        "- Lanjut: `lanjut`\n\n"
        "Kalau masih bingung, tekan `Skip` untuk loncat step.",
        parse_mode="Markdown",
        reply_markup=_tut_kb(True),
    )


@router.exact("tutorial_exit")
async def _h_tutorial_exit(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("tutorial_mode", None)
    await update.callback_query.edit_message_text(
        "Tutorial Mode selesai. Ketik `tutorial` kalau mau mulai lagi. ✅"
    )


@router.exact("tutorial_skip")
async def _h_tutorial_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    tm: dict = ctx.user_data.get("tutorial_mode") or {}
    if not tm.get("active"):
        await query.message.reply_text("Tutorial Mode belum aktif. Ketik `tutorial` untuk mulai.")
        return
    step = min(int(tm.get("step") or 1) + 1, int(tm.get("total") or 5))
    total = int(tm.get("total") or 5)
    mode = tm.get("mode") or "beginner"
    tm.update(step=step, last_ts=datetime.now(tz=timezone.utc).timestamp())
    ctx.user_data["tutorial_mode"] = tm
    if step >= total:
        await query.edit_message_text(
            f"🎓 **Tutorial Mode**\n\nProgress: `{_tut_bar(total, total)}` {total}/{total}\n\n"
            "Step terakhir: ketik `batal transaksi terakhir` untuk latihan ya.",
            parse_mode="Markdown",
            reply_markup=_tut_kb(True),
        )
        return
    await query.edit_message_text(
        _tut_step_msg(step, total, mode),
        parse_mode="Markdown",
        reply_markup=_tut_kb(True),
    )


@router.prefix("tutorial_")
async def _h_tutorial_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    section = action.removeprefix("tutorial_")
    text = _TUTORIAL_SECTIONS.get(section, "Pilih bagian tutorial yang kamu mau.")
    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=_tutorial_content_kb(),
    )


# ── Cancellation flow ────────────────────────────────────────────────────────

@router.exact("cancel_abort")
async def _h_cancel_abort(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("pending_cancel", None)
    await update.callback_query.edit_message_text("Oke, pembatalan dibatalkan. ✅")


@router.exact("cancel_choose")
async def _h_cancel_choose(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    pending_cancel = ctx.user_data.get("pending_cancel")
    if not pending_cancel or not pending_cancel.get("candidates"):
        await query.message.reply_text(
            "Aku belum nemu kandidat transaksi. Coba tulis: `batal transaksi terakhir` atau `hapus #ID`.",
            parse_mode="Markdown",
        )
        return
    await query.edit_message_text(
        "Pilih transaksi yang mau dibatalkan:",
        reply_markup=_cancel_candidates_kb(pending_cancel["candidates"]),
    )


@router.exact("list_targets")
async def _h_list_targets(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.saving import list_targets
    await list_targets(update, ctx)


@router.prefix("cancel_pick:")
async def _h_cancel_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    pending_cancel = ctx.user_data.get("pending_cancel")
    if not pending_cancel:
        await query.message.reply_text("Session pembatalan sudah habis. Coba ulangi perintah pembatalan ya.")
        return
    try:
        tx_id = int(action.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("ID transaksi tidak valid.")
        return

    pending_cancel["selected_id"] = tx_id
    ctx.user_data["pending_cancel"] = pending_cancel
    await query.edit_message_text(
        f"Siap. Kamu mau membatalkan transaksi `#{tx_id}`. Lanjut?",
        parse_mode="Markdown",
        reply_markup=_cancel_confirm_kb(tx_id),
    )


@router.exact("cancel_confirm")
async def _h_cancel_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    pending_cancel = ctx.user_data.get("pending_cancel")

    if not pending_cancel or not pending_cancel.get("selected_id"):
        await query.message.reply_text(
            "Aku belum tahu transaksi mana yang harus dibatalkan. "
            "Ketik: `batal transaksi terakhir` atau `hapus #ID`."
        )
        return

    tx_id = int(pending_cancel["selected_id"])
    eta_seconds = int(pending_cancel.get("eta_seconds") or 60)

    try:
        success = db.delete_transaction(user_db.id, tx_id)
    except Exception as exc:
        logger.error("delete_transaction failed tx_id=%d: %s", tx_id, exc)
        success = False

    if success:
        _redis_audit(
            f"cancel_audit:{user_id}",
            {
                "tx_id": tx_id,
                "reason": pending_cancel.get("reason") or "",
                "eta_seconds": eta_seconds,
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            },
        )
        _broadcast_ws(user_id, {"event": "refund_status", "data": {"tx_id": tx_id, "status": "success", "eta_seconds": eta_seconds}})
        ctx.user_data.pop("pending_cancel", None)
        await query.edit_message_text(
            f"✅ **Berhasil dibatalkan**: transaksi `#{tx_id}`\n⏱️ Estimasi refund: ≤ {eta_seconds} detik",
            parse_mode="Markdown",
        )
        try:
            await update_pinned_dashboard(ctx, user_id)
        except Exception as exc:
            logger.warning("update_pinned_dashboard failed: %s", exc)
    else:
        await query.edit_message_text(
            f"❌ Gagal membatalkan transaksi `#{tx_id}`. "
            f"Coba cek `/history` lalu pakai `/hapus {tx_id}`.",
            parse_mode="Markdown",
        )


# ── Transaction confirm / edit ───────────────────────────────────────────────

@router.exact("tx_confirm")
async def _h_tx_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    pending = ctx.user_data.get("pending_tx")
    if not pending:
        await query.answer("Sesi transaksi sudah habis. Silakan catat ulang.")
        return

    tx_date = _parse_date(pending.get("date"))
    tags = rules.evaluate({
        "amount": pending.get("amount", 0),
        "category": pending.get("category", "Lain-lain"),
        "hour": tx_date.hour,
    })
    description = pending.get("merchant") or pending.get("description") or "Transaksi"
    if tags:
        description += f" ({', '.join(tags)})"

    try:
        new_tx = db.add_transaction(
            user_id=user_db.id,
            amount=pending.get("amount", 0),
            category=pending.get("category", "Lain-lain"),
            trans_type=pending.get("type", "expense"),
            description=description,
            trans_date=tx_date,
        )
        # For frictionless undo
        if new_tx:
            ctx.user_data["last_tx_id"] = new_tx.id
            ctx.user_data["last_tx_ts"] = datetime.now().timestamp()
            
    except Exception as exc:
        logger.error("add_transaction failed: %s", exc)
        await query.edit_message_text("❌ Gagal menyimpan transaksi. Coba lagi ya.")
        return

    from utils.visuals import format_currency
    amount_str = format_currency(pending.get('amount', 0))
    budget_msg = budget_mgr.check_budget_status(user_db.id, pending.get("category", "Lain-lain"))
    
    # Internal Score Check
    from core import analyzer
    score_data = analyzer.calculate_financial_score(user_db.id)
    
    final_msg = f"✅ Dicatat: {amount_str} · {pending.get('category', 'Lain-lain')}"
    if budget_msg:
        final_msg += f"\n\n{budget_msg}"
    
    final_msg += f"\n\n🏆 **Financial Score**: {score_data['score']}/100 ({score_data['status']})"
    final_msg += "\n\n_Ketik 'undo' dalam 30 detik untuk batal._"

    await query.edit_message_text(final_msg, reply_markup=_post_action_kb())
    await query.message.reply_text("Ada lagi yang bisa saya bantu?", reply_markup=get_main_menu_keyboard())
    await send_onboarding_hint(query.message, db_user_id=user_db.id, telegram_user_id=user_id)

    ctx.user_data.pop("pending_tx", None)
    ctx.user_data.pop("state", None)

    try:
        await update_pinned_dashboard(ctx, user_id)
    except Exception as exc:
        logger.warning("update_pinned_dashboard failed: %s", exc)


@router.exact("tx_edit")
async def _h_tx_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.edit_message_text(
        "Pilih bagian yang ingin diubah:", reply_markup=_edit_field_kb()
    )


@router.exact("tx_ignore")
async def _h_tx_ignore(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("pending_tx", None)
    ctx.user_data.pop("state", None)
    query = update.callback_query
    await query.edit_message_text("Transaksi diabaikan. Ada lagi yang mau dicatat?")
    await query.message.reply_text("Silakan pilih menu di bawah:", reply_markup=get_main_menu_keyboard())


@router.exact("edit_amount")
async def _h_edit_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data["state"] = "WAITING_EDIT_AMOUNT"
    await update.callback_query.edit_message_text("Ketik nominal baru (contoh: 50rb atau 50000):")


@router.exact("edit_category")
async def _h_edit_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data["state"] = "WAITING_EDIT_CATEGORY"
    await update.callback_query.edit_message_text(
        "Pilih kategori baru:", reply_markup=_category_select_kb()
    )


@router.prefix("set_cat_")
async def _h_set_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    new_cat = action.removeprefix("set_cat_")
    pending = ctx.user_data.get("pending_tx")
    if not pending:
        await query.answer("Sesi sudah habis.")
        return
    pending["category"] = new_cat
    ctx.user_data["pending_tx"] = pending
    from utils.visuals import format_currency
    amount_str = format_currency(pending.get('amount', 0))
    await query.edit_message_text(
        f"Kategori diubah ke: {new_cat}\n\n{amount_str} · {new_cat}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
            InlineKeyboardButton("✎ Edit Lagi", callback_data="tx_edit"),
        ]]),
    )


# ── Reports ──────────────────────────────────────────────────────────────────

@router.prefix("report_")
async def _h_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    period = action.removeprefix("report_")
    report_msg = budget_mgr.generate_report(user_db.id, period=period)
    
    # Add Financial Score to Report
    from core import analyzer
    score_data = analyzer.calculate_financial_score(user_db.id)
    report_msg += f"\n🏆 **Financial Score**: {score_data['score']}/100 ({score_data['status']})"

    await query.edit_message_text(report_msg, reply_markup=_report_nav_kb())

    now = datetime.now()
    try:
        transactions = db.get_monthly_report(user_db.id, now.month, now.year)
        photo_path = visual_reporter.generate_expense_pie(transactions, user_id)
        if photo_path:
            try:
                with open(photo_path, "rb") as photo:
                    await query.message.reply_photo(photo, caption="Visualisasi Pengeluaran Anda")
            finally:
                if os.path.exists(photo_path):
                    os.remove(photo_path)
    except Exception as exc:
        logger.warning("Report chart failed: %s", exc)


# ── Navigation / shortcuts ────────────────────────────────────────────────────

@router.exact("suggest_help")
async def _h_suggest_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.commands import help_command
    await help_command(update, ctx)


@router.exact("suggest_budget")
async def _h_suggest_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    status = budget_mgr.check_budget_status(user_db.id, "Semua")
    await update.callback_query.message.reply_text(status, reply_markup=get_main_menu_keyboard())


@router.exact("suggest_insight", "get_ai_insight")
async def _h_suggest_insight(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.finance import get_ai_insight
    await get_ai_insight(update, ctx)
    await update.callback_query.message.reply_text(
        "Aksi konkret: kurangi ngopi 20% minggu ini.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Set limit Minuman", callback_data="insight:set_limit:minuman"),
        ]]),
    )


@router.exact("open_history")
async def _h_open_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.transactions import history
    # Pass the callback's message as a proxy — do NOT mutate update.message
    await history(update, ctx)


@router.exact("get_report")
async def _h_get_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    msg = budget_mgr.generate_report(user_db.id, "monthly")
    await update.callback_query.message.reply_text(msg)


@router.exact("get_profile")
async def _h_get_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.commands import profile_command
    await profile_command(update, ctx)


@router.exact("manual_add")
async def _h_manual_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.message.reply_text(
        "💸 **Catat Transaksi**\n\nKetik langsung: `Item Harga`\nContoh: `Kopi 25rb` atau `Gaji 10jt`",
        parse_mode="Markdown",
    )


@router.exact("get_persona")
async def _h_get_persona(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    """API-like handler for GET /persona."""
    user_id = update.effective_user.id
    from core import gamify, db
    
    # Use callback_query instead of message for reply
    query = update.callback_query
    await query.answer("Calculating your financial persona...")
    
    persona_data = await gamify.update_financial_persona(user_id, db)
    
    if not persona_data:
        await query.message.reply_text("Belum ada cukup data untuk menentukan persona kamu. Terus catat ya!")
        return

    msg = (
        f"👤 **Financial Persona: {persona_data['persona']}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Key Drivers**:\n"
    )
    for driver in persona_data['key_drivers']:
        msg += f"• {driver}\n"
        
    msg += f"\n💡 **Premium Tips**:\n"
    for tip in persona_data['tips']:
        msg += f"• {tip}\n"
        
    msg += f"\n_Confidence: {persona_data['confidence']*100:.0f}%_"
    
    await query.message.reply_text(msg, parse_mode='Markdown')


@router.exact("scan_receipt")
async def _h_scan_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.message.reply_text(
        "📸 **Scan Struk**\n\nSilakan kirim foto struk belanjaan kamu sekarang!",
        parse_mode="Markdown",
    )


@router.exact("list_target")
async def _h_list_target(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    from handlers.saving import list_targets
    await list_targets(update, ctx)


@router.exact("set_gaji_menu")
async def _h_set_gaji_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.message.reply_text(
        "💰 **Atur Gaji**\n\nKetik `/setgaji [Nominal]`\nContoh: `/setgaji 10jt`",
        parse_mode="Markdown",
    )


@router.exact("settings_menu")
async def _h_settings_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.message.reply_text(
        "⚙️ **Pengaturan**\n\n"
        "• `/setbudget [Kat] [Jml]` — Atur limit kategori\n"
        "• `/budgetalert [Kat] [Warn%] [Limit%]` — Notifikasi\n"
        "• `/hapus [ID]` — Hapus transaksi\n"
        "• `/undo` — Batal transaksi terakhir",
        parse_mode="Markdown",
    )


# ── Code execution ────────────────────────────────────────────────────────────

@router.exact("code_confirm")
async def _h_code_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    code = ctx.user_data.get("pending_code")
    if not code:
        await query.edit_message_text("No code found to execute. ❌")
        return
    result = execute_code(code)
    await query.edit_message_text(
        f"Thank you! Your code has been executed successfully. ✅\n\n💻 **Output:**\n```\n{result}\n```",
        parse_mode="Markdown",
    )
    await query.message.reply_text("Apa lagi yang bisa saya bantu? 😊", reply_markup=get_main_menu_keyboard())
    ctx.user_data.pop("pending_code", None)


@router.exact("code_cancel")
async def _h_code_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    await query.edit_message_text("Edit cancelled. Feel free to ask again. 👍")
    await query.message.reply_text("Butuh bantuan lainnya?", reply_markup=get_main_menu_keyboard())
    ctx.user_data.pop("pending_code", None)


# ── Bulk & Correction flow ───────────────────────────────────────────────────

@router.exact("bulk_confirm")
async def _h_bulk_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    items = ctx.user_data.get("pending_bulk")
    
    if not items:
        await query.answer("Sesi bulk sudah habis.")
        return

    await query.edit_message_text(f"⏳ Sedang menyimpan {len(items)} transaksi...")
    
    success_count = 0
    last_added_id = None
    for item in items:
        try:
            tx_date = _parse_date(item.get("date"))
            new_tx = db.add_transaction(
                user_id=user_db.id,
                amount=float(item["amount"]),
                category=item["category"],
                trans_type=item.get("type", "expense"),
                description=item.get("merchant") or "Bulk Entry",
                trans_date=tx_date,
            )
            if new_tx:
                last_added_id = new_tx.id
            success_count += 1
        except Exception as exc:
            logger.error("Bulk item failed: %s", exc)

    if last_added_id:
        ctx.user_data["last_tx_id"] = last_added_id
        ctx.user_data["last_tx_ts"] = datetime.now().timestamp()

    ctx.user_data.pop("pending_bulk", None)
    await query.edit_message_text(f"✅ Berhasil menyimpan {success_count} transaksi!\n_Ketik 'undo' untuk batal._")
    await query.message.reply_text("Ada lagi yang mau dicatat?", reply_markup=get_main_menu_keyboard())
    
    try:
        await update_pinned_dashboard(ctx, user_id)
    except Exception: pass


@router.exact("bulk_cancel")
async def _h_bulk_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("pending_bulk", None)
    await update.callback_query.edit_message_text("Oke, semua transaksi dibatalkan. ✅")


@router.exact("update_confirm")
async def _h_update_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    pending = ctx.user_data.get("pending_update")
    
    if not pending:
        await query.answer("Sesi koreksi sudah habis.")
        return

    try:
        # We need a db.update_transaction method. Let's check if it exists or use delete + add
        # Based on current db_handler.py, it might not have update.
        # Let's assume we can use db.supabase directly if needed, or check db_handler.
        success = db.delete_transaction(user_db.id, pending["id"])
        if success:
            db.add_transaction(
                user_id=user_db.id,
                amount=float(pending["amount"]),
                category=pending["category"],
                trans_type=pending["type"],
                description=pending["merchant"],
                trans_date=_parse_date(pending["date"]),
            )
            await query.edit_message_text("✅ Transaksi berhasil dikoreksi!")
        else:
            await query.edit_message_text("❌ Gagal mengoreksi transaksi lama.")
    except Exception as exc:
        logger.error("update_confirm failed: %s", exc)
        await query.edit_message_text("❌ Terjadi kesalahan saat update.")

    ctx.user_data.pop("pending_update", None)
    await query.message.reply_text("Ada lagi?", reply_markup=get_main_menu_keyboard())
    try:
        await update_pinned_dashboard(ctx, user_id)
    except Exception: pass


@router.exact("update_cancel")
async def _h_update_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    ctx.user_data.pop("pending_update", None)
    await update.callback_query.edit_message_text("Koreksi dibatalkan. ✅")


@router.exact("split_receivable")
async def _h_split_receivable(update: Update, ctx: ContextTypes.DEFAULT_TYPE, _action: str):
    await update.callback_query.answer("Fitur Piutang sedang dalam pengembangan! 🚀", show_alert=True)


# History UX
@router.prefix("hist:")
async def _h_history_ux(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    parts = action.split(":")

    if len(parts) == 2 and parts[1] in {"today", "week", "top", "all"}:
        ctx.user_data["history_filter"] = parts[1]
        if parts[1] != "all":
            ctx.user_data.pop("history_category", None)
        await history(update, ctx)
        return

    if len(parts) == 2 and parts[1] == "cat":
        rows = []
        for i in range(0, len(CATEGORIES), 2):
            row = []
            for cat in CATEGORIES[i : i + 2]:
                row.append(InlineKeyboardButton(cat, callback_data=f"hist:catset:{cat}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("Reset", callback_data="hist:all")])
        await query.edit_message_text("Pilih kategori:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if len(parts) == 3 and parts[1] == "catset":
        ctx.user_data["history_filter"] = "all"
        ctx.user_data["history_category"] = parts[2]
        await history(update, ctx)
        return

    if len(parts) == 4 and parts[1] == "item":
        try:
            tx_id = int(parts[2])
        except ValueError:
            await query.answer("ID transaksi invalid.", show_alert=True)
            return
        action_name = parts[3]
        if action_name == "delete":
            ok = db.delete_transaction(user_db.id, tx_id)
            if ok:
                await query.message.reply_text(f"Transaksi #{tx_id} dihapus.")
                await history(update, ctx)
            else:
                await query.message.reply_text("Transaksi tidak ditemukan.")
            return

        if action_name == "dup":
            ok = await duplicate_transaction(update, ctx, tx_id)
            if ok:
                await query.message.reply_text(f"Transaksi #{tx_id} berhasil diduplikasi.")
                await history(update, ctx)
            else:
                await query.message.reply_text("Gagal duplikasi transaksi.")
            return

        if action_name == "edit":
            ok = load_pending_update(ctx, user_db.id, tx_id)
            if not ok:
                await query.message.reply_text("Transaksi tidak ditemukan.")
                return
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Edit Nominal", callback_data="hist:update:amount"),
                        InlineKeyboardButton("Edit Kategori", callback_data="hist:update:category"),
                    ],
                    [
                        InlineKeyboardButton("Simpan Perubahan", callback_data="update_confirm"),
                        InlineKeyboardButton("Batal", callback_data="update_cancel"),
                    ],
                ]
            )
            await query.message.reply_text(
                f"Edit transaksi #{tx_id}. Pilih field yang ingin diubah.",
                reply_markup=kb,
            )
            return

    if action == "hist:update:amount":
        ctx.user_data["state"] = "WAITING_UPDATE_EDIT_AMOUNT"
        await query.edit_message_text("Ketik nominal baru untuk transaksi ini:")
        return

    if action == "hist:update:category":
        ctx.user_data["state"] = "WAITING_UPDATE_EDIT_CATEGORY"
        await query.edit_message_text("Ketik kategori baru. Contoh: Makanan")
        return


@router.prefix("insight:set_limit:")
async def _h_insight_set_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    category = action.split(":")[-1].capitalize()
    budget = db.get_budget(user_db.id, category)
    current = float(getattr(budget, "limit_amount", 0) or 0)
    new_limit = max(100000, current * 0.8) if current > 0 else 300000
    db.set_budget(user_db.id, category, new_limit)
    await query.message.reply_text(f"Limit {category} di-set ke Rp{new_limit:,.0f}.")


@router.prefix("reminder:")
async def _h_reminder_personal(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    query = update.callback_query
    user_id = update.effective_user.id
    parts = action.split(":")
    try:
        from modules.redis_mgr import RedisManager

        redis = RedisManager()
        if not redis.client:
            await query.message.reply_text("Redis tidak tersedia, coba lagi nanti.")
            return
        if action == "reminder:menu":
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Santai", callback_data="reminder:tone:santai"),
                        InlineKeyboardButton("Tegas", callback_data="reminder:tone:tegas"),
                        InlineKeyboardButton("Formal", callback_data="reminder:tone:formal"),
                    ],
                    [
                        InlineKeyboardButton("Jam 08", callback_data="reminder:time:8"),
                        InlineKeyboardButton("Jam 20", callback_data="reminder:time:20"),
                        InlineKeyboardButton("Jam 21", callback_data="reminder:time:21"),
                    ],
                    [
                        InlineKeyboardButton("Snooze 1 hari", callback_data="reminder:snooze:1d"),
                        InlineKeyboardButton("ON", callback_data="reminder:toggle:on"),
                        InlineKeyboardButton("OFF", callback_data="reminder:toggle:off"),
                    ],
                ]
            )
            await query.edit_message_text("Pengaturan reminder personal:", reply_markup=kb)
            return
        if len(parts) == 3 and parts[1] == "toggle":
            redis.client.set(f"user:{user_id}:reminder_enabled", "1" if parts[2] == "on" else "0")
            await query.message.reply_text(f"Reminder {'aktif' if parts[2] == 'on' else 'nonaktif'}.")
            return
        if len(parts) == 3 and parts[1] == "tone":
            redis.client.set(f"user:{user_id}:reminder_tone", parts[2])
            await query.message.reply_text(f"Tone reminder di-set: {parts[2]}.")
            return
        if len(parts) == 3 and parts[1] == "time":
            hour = int(parts[2])
            hour = max(0, min(23, hour))
            redis.client.set(f"user:{user_id}:reminder_hour", str(hour))
            await query.message.reply_text(f"Jam reminder di-set ke {hour:02d}:00.")
            return
        if len(parts) == 3 and parts[1] == "snooze" and parts[2] == "1d":
            snooze_until = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
            redis.client.set(f"user:{user_id}:reminder_snooze_until", str(snooze_until))
            await query.message.reply_text("Reminder disnooze 1 hari.")
            return
    except Exception as exc:
        logger.error("reminder callback failed: %s", exc)
        await query.message.reply_text("Gagal mengatur reminder.")


# ---------------------------------------------------------------------------
# WebSocket broadcast helper (fire-and-forget)
# ---------------------------------------------------------------------------

def _broadcast_ws(user_id: int, message: dict) -> None:
    try:
        from core import ws_server
        if ws_server.loop and ws_server.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                ws_server.broadcast_to_user(user_id=user_id, message=message),
                ws_server.loop,
            )
    except Exception as exc:
        logger.debug("WS broadcast failed user=%d: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Main entry-point (registered with python-telegram-bot)
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    action = query.data or ""

    # Delegate tutorial module's own callbacks first
    if await tutorial_mode.handle_callback(update, context, action):
        return

    dispatched = await router.dispatch(update, context, action)
    if not dispatched:
        logger.warning("Unhandled callback action=%r user=%s", action, update.effective_user.id)
        await query.answer("Aksi tidak dikenali. Coba lagi ya.", show_alert=True)


# ---------------------------------------------------------------------------
# Report selector (called from commands)
# ---------------------------------------------------------------------------

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Bulan Ini", callback_data="report_monthly"),
        InlineKeyboardButton("7 Hari Terakhir", callback_data="report_7days"),
        InlineKeyboardButton("30 Hari Terakhir", callback_data="report_30days"),
    ]])
    msg = "Pilih periode laporan:"
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(msg, reply_markup=kb)

