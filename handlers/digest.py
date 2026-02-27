"""
tasks.py — FinBot Pro Scheduled Tasks
Refactored for reliability, performance, and observability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence

import pandas as pd
from telegram.ext import ContextTypes

from core import budget_mgr, db, premium_ai
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VISUAL_REPORT_DAYS = frozenset({1, 7, 14, 21, 28})
_REMINDER_MIN_HOURS = 24
_REMINDER_MAX_HOURS = 48


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Nightly digest (runs at 21:00 WIB via job queue).
    Sends spending summary, category breakdown, budget status, and saving goals.
    Falls back to a reminder nudge when no activity is recorded.
    """
    now = datetime.now()
    users = db.get_all_users()
    logger.info("daily_digest started — processing %d users", len(users))

    success = error = skipped = 0

    for user in users:
        try:
            sent = await _process_user_digest(context, user, now)
            if sent:
                success += 1
            else:
                skipped += 1
        except Exception:
            error += 1
            logger.exception("daily_digest failed for telegram_id=%s", user.telegram_id)

    logger.info(
        "daily_digest done — sent=%d skipped=%d errors=%d",
        success, skipped, error,
    )

"""
tasks.py — FinBot Pro Scheduled Tasks
Refactored for reliability, performance, and observability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence

import pandas as pd
from telegram.ext import ContextTypes

from core import budget_mgr, db, premium_ai
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VISUAL_REPORT_DAYS = frozenset({1, 7, 14, 21, 28})
_REMINDER_MIN_HOURS = 24
_REMINDER_MAX_HOURS = 48


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Nightly digest (runs at 21:00 WIB via job queue).
    Sends spending summary, category breakdown, budget status, and saving goals.
    Falls back to a reminder nudge when no activity is recorded.
    """
    now = datetime.now()
    users = db.get_all_users()
    logger.info("daily_digest started — processing %d users", len(users))

    success = error = skipped = 0

    for user in users:
        try:
            sent = await _process_user_digest(context, user, now)
            if sent:
                success += 1
            else:
                skipped += 1
        except Exception:
            error += 1
            logger.exception("daily_digest failed for telegram_id=%s", user.telegram_id)

    logger.info(
        "daily_digest done — sent=%d skipped=%d errors=%d",
        success, skipped, error,
    )


async def _process_user_digest(context, user, now: datetime) -> bool:
    """
    Build and send the digest for a single user.
    Returns True if a digest was sent, False if we fell back to a reminder (or nothing).
    """
    transactions = db.get_daily_transactions(user.id, now)
    expense_txs = [t for t in transactions if t.type == "expense"]
    total_expense = sum(t.amount for t in expense_txs)

    if not expense_txs or total_expense == 0:
        await check_and_send_reminder(context, user)
        return False

    msg = _build_digest_message(user, expense_txs, total_expense, now)
    await context.bot.send_message(
        chat_id=user.telegram_id,
        text=msg,
        parse_mode="Markdown",
    )

    if now.day in _VISUAL_REPORT_DAYS:
        await _try_send_visual_report(context, user)

    return True


def _build_digest_message(user, expense_txs: list, total_expense: float, now: datetime) -> str:
    """Compose the full digest text. Pure function — easy to unit test."""

    # --- Category breakdown via pandas ---
    df = pd.DataFrame([{"amount": t.amount, "category": t.category} for t in expense_txs])
    cat_summary = df.groupby("category")["amount"].sum().sort_values(ascending=False)

    # --- 7-day trend ---
    trend = _compute_trend(user.id, total_expense)

    # --- Budget status for top category ---
    top_cat = cat_summary.index[0]
    budget_info = budget_mgr.check_budget_status(user.id, top_cat)

    # --- Build message ---
    lines = [
        "🌙 *DAILY DIGEST*\n",
        f"💰 Total Hari Ini: Rp{total_expense:,.0f}",
    ]
    if trend:
        lines.append(trend)
    lines.append("\n📂 *Breakdown:*")
    for cat, amt in cat_summary.items():
        lines.append(f"  • {cat}: Rp{amt:,.0f}")
    if budget_info:
        lines.append(f"\n💡 {budget_info}")

    # --- Saving goal (first active one) ---
    goal_block = _build_goal_block(user.id, now)
    if goal_block:
        lines.append(goal_block)

    return "\n".join(lines)


def _compute_trend(user_id: int, total_expense: float) -> str:
    """Return a trend emoji string, or empty string if no history."""
    try:
        last_7 = db.get_sliding_window_transactions(user_id, days=7)
        if not last_7:
            return ""
        avg = sum(t.amount for t in last_7 if t.type == "expense") / 7
        return "📈 Di atas rata-rata" if total_expense > avg else "📉 Di bawah rata-rata"
    except Exception:
        logger.warning("_compute_trend failed for user_id=%d", user_id, exc_info=True)
        return ""


def _build_goal_block(user_id: int, now: datetime) -> str:
    """Return the saving goal section, or empty string if none active."""
    try:
        goals = db.get_user_saving_goals(user_id) or []
        active = [
            g for g in goals
            if g.target_amount > 0 and (g.current_amount / g.target_amount) < 1.0
        ]
        if not active:
            return ""

        g = active[0]
        remaining = g.target_amount - g.current_amount
        block = f"\n\n🎯 Target: *{g.name}*\nSisa: Rp{remaining:,.0f}"

        target_date = getattr(g, "target_date", None)
        if target_date:
            months_left = max(
                1,
                (target_date.year - now.year) * 12
                + (target_date.month - now.month)
                + (1 if target_date.day > now.day else 0),
            )
            block += f"\nPerlu: Rp{remaining / months_left:,.0f}/bulan"

        return block

    except Exception:
        logger.warning("_build_goal_block failed for user_id=%d", user_id, exc_info=True)
        return ""


async def _try_send_visual_report(context, user) -> None:
    """Attempt to send a monthly chart. Failures are logged but never propagated."""
    try:
        from utils.visuals import generate_monthly_chart

        chart_txs = db.get_sliding_window_transactions(user.id, days=30)
        chart_buf = generate_monthly_chart(chart_txs, title="Ringkasan 30 Hari")
        if chart_buf:
            await context.bot.send_photo(
                chat_id=user.telegram_id,
                photo=chart_buf,
                caption="📊 *Visual Report* (Beta)",
                parse_mode="Markdown",
            )
    except Exception:
        logger.error(
            "Visual report failed for telegram_id=%s", user.telegram_id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Reminder system
# ---------------------------------------------------------------------------

async def check_and_send_reminder(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """
    Send a friendly nudge if the user has been silent for 24–48 hours
    AND has reminders enabled (default: on).
    """
    try:
        last_dt = _get_last_interaction(user.id)
        if last_dt is None:
            return  # No history — skip to avoid spamming new users

        if not _reminder_is_due(last_dt):
            return

        if not _reminder_is_enabled(user.id):
            return

        msg = await _build_reminder_message(user.id)
        await context.bot.send_message(chat_id=user.telegram_id, text=msg)
        logger.info("Reminder sent to telegram_id=%s", user.telegram_id)

    except Exception:
        logger.exception("check_and_send_reminder failed for telegram_id=%s", user.telegram_id)


# ---------------------------------------------------------------------------
# Reminder helpers
# ---------------------------------------------------------------------------

_FALLBACK_REMINDERS = [
    "Hai! Belum ada pengeluaran hari ini? Jangan lupa catat kalau ada ya! 📝",
    "Kangen nih! Dompet aman? 🤑 Cek budget yuk!",
    "Psst... udah jajan apa aja hari ini? Sini aku catatin biar gak lupa! 🧐",
    "Reminder santai: Pencatatan rutin bikin finansial makin sehat loh! 🚀",
]


def _get_last_interaction(user_id: int) -> Optional[datetime]:
    """
    Return the datetime of the user's last recorded transaction, or None.
    Returns a naive datetime (no tzinfo) for consistent arithmetic.
    """
    try:
        raw = db.get_last_transaction_date(user_id)
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=None)
        # Handle ISO string e.g. "2024-01-15T18:30:00Z"
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        logger.warning("_get_last_interaction failed for user_id=%d", user_id, exc_info=True)
        return None


def _reminder_is_due(last_dt: datetime) -> bool:
    """True if 24 h < silence < 48 h."""
    diff = datetime.now() - last_dt
    return timedelta(hours=_REMINDER_MIN_HOURS) < diff < timedelta(hours=_REMINDER_MAX_HOURS)


def _reminder_is_enabled(user_id: int) -> bool:
    """
    Check user opt-out preference in Redis.
    Defaults to True (enabled) when Redis is unavailable or key not set.
    """
    try:
        redis = RedisManager()
        if not redis.client:
            return True
        pref = redis.client.get(f"user:{user_id}:reminder_enabled")
        if pref is None:
            return True  # Key not set → default ON
        return pref.decode() != "0"
    except Exception:
        logger.warning("_reminder_is_enabled check failed for user_id=%d — defaulting ON", user_id)
        return True


async def _build_reminder_message(user_id: int) -> str:
    """Try AI-generated reminder; fall back to a random canned message."""
    import random

    try:
        ai_msg = await premium_ai.generate_reminder(user_id)
        if ai_msg:
            return ai_msg
    except Exception:
        logger.warning("AI reminder generation failed for user_id=%d", user_id, exc_info=True)

    return random.choice(_FALLBACK_REMINDERS)


def _build_digest_message(user, expense_txs: list, total_expense: float, now: datetime) -> str:
    """Compose the full digest text. Pure function — easy to unit test."""

    # --- Category breakdown via pandas ---
    df = pd.DataFrame([{"amount": t.amount, "category": t.category} for t in expense_txs])
    cat_summary = df.groupby("category")["amount"].sum().sort_values(ascending=False)

    # --- 7-day trend ---
    trend = _compute_trend(user.id, total_expense)

    # --- Budget status for top category ---
    top_cat = cat_summary.index[0]
    budget_info = budget_mgr.check_budget_status(user.id, top_cat)

    # --- Build message ---
    lines = [
        "🌙 *DAILY DIGEST*\n",
        f"💰 Total Hari Ini: Rp{total_expense:,.0f}",
    ]
    if trend:
        lines.append(trend)
    lines.append("\n📂 *Breakdown:*")
    for cat, amt in cat_summary.items():
        lines.append(f"  • {cat}: Rp{amt:,.0f}")
    if budget_info:
        lines.append(f"\n💡 {budget_info}")

    # --- Saving goal (first active one) ---
    goal_block = _build_goal_block(user.id, now)
    if goal_block:
        lines.append(goal_block)

    return "\n".join(lines)


def _compute_trend(user_id: int, total_expense: float) -> str:
    """Return a trend emoji string, or empty string if no history."""
    try:
        last_7 = db.get_sliding_window_transactions(user_id, days=7)
        if not last_7:
            return ""
        avg = sum(t.amount for t in last_7 if t.type == "expense") / 7
        return "📈 Di atas rata-rata" if total_expense > avg else "📉 Di bawah rata-rata"
    except Exception:
        logger.warning("_compute_trend failed for user_id=%d", user_id, exc_info=True)
        return ""


def _build_goal_block(user_id: int, now: datetime) -> str:
    """Return the saving goal section, or empty string if none active."""
    try:
        goals = db.get_user_saving_goals(user_id) or []
        active = [
            g for g in goals
            if g.target_amount > 0 and (g.current_amount / g.target_amount) < 1.0
        ]
        if not active:
            return ""

        g = active[0]
        remaining = g.target_amount - g.current_amount
        block = f"\n\n🎯 Target: *{g.name}*\nSisa: Rp{remaining:,.0f}"

        target_date = getattr(g, "target_date", None)
        if target_date:
            months_left = max(
                1,
                (target_date.year - now.year) * 12
                + (target_date.month - now.month)
                + (1 if target_date.day > now.day else 0),
            )
            block += f"\nPerlu: Rp{remaining / months_left:,.0f}/bulan"

        return block

    except Exception:
        logger.warning("_build_goal_block failed for user_id=%d", user_id, exc_info=True)
        return ""


async def _try_send_visual_report(context, user) -> None:
    """Attempt to send a monthly chart. Failures are logged but never propagated."""
    try:
        from utils.visuals import generate_monthly_chart

        chart_txs = db.get_sliding_window_transactions(user.id, days=30)
        chart_buf = generate_monthly_chart(chart_txs, title="Ringkasan 30 Hari")
        if chart_buf:
            await context.bot.send_photo(
                chat_id=user.telegram_id,
                photo=chart_buf,
                caption="📊 *Visual Report* (Beta)",
                parse_mode="Markdown",
            )
    except Exception:
        logger.error(
            "Visual report failed for telegram_id=%s", user.telegram_id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Reminder system
# ---------------------------------------------------------------------------

async def check_and_send_reminder(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """
    Send a friendly nudge if the user has been silent for 24–48 hours
    AND has reminders enabled (default: on).
    """
    try:
        last_dt = _get_last_interaction(user.id)
        if last_dt is None:
            return  # No history — skip to avoid spamming new users

        if not _reminder_is_due(last_dt):
            return

        if not _reminder_is_enabled(user.id):
            return

        msg = await _build_reminder_message(user.id)
        await context.bot.send_message(chat_id=user.telegram_id, text=msg)
        logger.info("Reminder sent to telegram_id=%s", user.telegram_id)

    except Exception:
        logger.exception("check_and_send_reminder failed for telegram_id=%s", user.telegram_id)


# ---------------------------------------------------------------------------
# Reminder helpers
# ---------------------------------------------------------------------------

_FALLBACK_REMINDERS = [
    "Hai! Belum ada pengeluaran hari ini? Jangan lupa catat kalau ada ya! 📝",
    "Kangen nih! Dompet aman? 🤑 Cek budget yuk!",
    "Psst... udah jajan apa aja hari ini? Sini aku catatin biar gak lupa! 🧐",
    "Reminder santai: Pencatatan rutin bikin finansial makin sehat loh! 🚀",
]


def _get_last_interaction(user_id: int) -> Optional[datetime]:
    """
    Return the datetime of the user's last recorded transaction, or None.
    Returns a naive datetime (no tzinfo) for consistent arithmetic.
    """
    try:
        raw = db.get_last_transaction_date(user_id)
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=None)
        # Handle ISO string e.g. "2024-01-15T18:30:00Z"
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        logger.warning("_get_last_interaction failed for user_id=%d", user_id, exc_info=True)
        return None


def _reminder_is_due(last_dt: datetime) -> bool:
    """True if 24 h < silence < 48 h."""
    diff = datetime.now() - last_dt
    return timedelta(hours=_REMINDER_MIN_HOURS) < diff < timedelta(hours=_REMINDER_MAX_HOURS)


def _reminder_is_enabled(user_id: int) -> bool:
    """
    Check user opt-out preference in Redis.
    Defaults to True (enabled) when Redis is unavailable or key not set.
    """
    try:
        redis = RedisManager()
        if not redis.client:
            return True
        pref = redis.client.get(f"user:{user_id}:reminder_enabled")
        if pref is None:
            return True  # Key not set → default ON
        return pref.decode() != "0"
    except Exception:
        logger.warning("_reminder_is_enabled check failed for user_id=%d — defaulting ON", user_id)
        return True


async def _build_reminder_message(user_id: int) -> str:
    """Try AI-generated reminder; fall back to a random canned message."""
    import random

    try:
        ai_msg = await premium_ai.generate_reminder(user_id)
        if ai_msg:
            return ai_msg
    except Exception:
        logger.warning("AI reminder generation failed for user_id=%d", user_id, exc_info=True)

    return random.choice(_FALLBACK_REMINDERS)