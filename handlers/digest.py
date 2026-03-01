from __future__ import annotations # HARUS DI SINI
import logging
import random
from datetime import datetime, timedelta
from typing import Optional, Sequence, Dict, Any

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import budget_mgr, db, premium_ai, analyzer, persona_mgr
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monthly Wrapper (Spotify-style)
# ---------------------------------------------------------------------------

async def monthly_wrapper_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Monthly wrapper job (runs 1st of every month at 09:00 WIB).
    Sends personalized monthly summary to all users.
    """
    now = datetime.now()
    # If it's the 1st, we summarize PREVIOUS month
    target_date = now - timedelta(days=5) # Go back to previous month
    month = target_date.month
    year = target_date.year
    
    users = db.get_all_users()
    logger.info("monthly_wrapper_job started — summarizing %d/%d for %d users", month, year, len(users))

    from modules.analysis import ExpenseAnalyzer
    analyzer_obj = ExpenseAnalyzer(db)
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            # Check if already sent
            existing = db.get_monthly_wrapper(user.id, month, year)
            if existing and existing['status'] == 'sent':
                continue
                
            wrapper_data = analyzer_obj.generate_monthly_wrapper(user.id, month, year)
            if not wrapper_data:
                continue
            
            # Save as pending first (Tracking)
            db.save_monthly_wrapper(user.id, month, year, wrapper_data, status="pending")
            
            # Format and send
            msg = _format_wrapper_message(user, wrapper_data)
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=msg,
                parse_mode="Markdown"
            )
            
            # Mark as sent
            db.save_monthly_wrapper(user.id, month, year, wrapper_data, status="sent")
            success += 1
            
        except Exception as e:
            logger.error(f"Failed to send monthly wrapper to {user.id}: {e}")
            db.save_monthly_wrapper(user.id, month, year, wrapper_data if 'wrapper_data' in locals() else {}, status="failed")
            failed += 1
            
    logger.info("monthly_wrapper_job done — success=%d failed=%d", success, failed)


def _format_wrapper_message(user, data: dict) -> str:
    """Formats the monthly wrapper message."""
    month_name = datetime(2000, data['month'], 1).strftime('%B')
    
    lines = [
        f"🌟 **FINBOT WRAPPED: {month_name.upper()} {data['year']}** 🌟\n",
        f"Halo {user.username or 'Sobat Cuan'}! Bulan lalu seru banget ya. Ini rangkuman finansialmu:\n",
        f"🏆 Gelar Kamu: **{data['title']}**\n",
        f"📊 Total Pengeluaran: *Rp{data['total_spend']:,.0f}*",
        f"🏷️ Kategori Teratas: *{data['top_category']}* (Rp{data['top_category_spend']:,.0f})",
        f"🏦 Saving Rate: *{data['saving_rate']:.1f}%*",
        f"📝 Total Transaksi: *{data['transaction_count']}*",
        "\nTetap semangat kontrol keuanganmu di bulan ini ya! 💪"
    ]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VISUAL_REPORT_DAYS = frozenset({1, 7, 14, 21, 28})
_REMINDER_MIN_HOURS = 24
_REMINDER_MAX_HOURS = 48


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def _is_preferred_hour(user_id: int, now_dt: datetime) -> bool:
    try:
        redis = RedisManager()
        if not redis.client:
            return True
        raw = redis.client.get(f"user:{user_id}:reminder_hour")
        if raw is None:
            return True
        raw_str = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        hour = int(raw_str)
        return int(now_dt.hour) == max(0, min(23, hour))
    except Exception:
        return True


def _is_snoozed(user_id: int) -> bool:
    try:
        redis = RedisManager()
        if not redis.client:
            return False
        raw = redis.client.get(f"user:{user_id}:reminder_snooze_until")
        if raw is None:
            return False
        raw_str = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        return int(raw_str) > int(datetime.now().timestamp())
    except Exception:
        return False

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


async def smart_reminder_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Job that runs periodically to check for inactive users and send reminders.
    """
    users = db.get_all_users()
    redis = RedisManager()
    now = datetime.now()

    for user in users:
        try:
            last_dt = _get_last_interaction(user.id)
            if not last_dt:
                continue

            diff = now - last_dt

            # Kirim pengingat jika:
            # - Sudah lewat 24 jam sejak transaksi terakhir
            # - Belum dikirim reminder dalam 24 jam terakhir (biar gak tiap jam dicolek)
            reminder_lock = f"user:{user.id}:reminder_cooldown"

            if timedelta(hours=_REMINDER_MIN_HOURS) < diff < timedelta(hours=_REMINDER_MAX_HOURS):
                if _is_snoozed(user.id):
                    continue
                if not _is_preferred_hour(user.id, now):
                    continue
                if redis.client and not redis.client.get(reminder_lock):
                    msg = await _build_reminder_message(user.id)
                    await context.bot.send_message(chat_id=user.telegram_id, text=msg)

                    # Pasang cooldown 24 jam agar tidak spam
                    if redis.client:
                        redis.client.setex(reminder_lock, 86400, "1")
        except Exception as e:
            logger.error(f"Reminder check failed for {user.id}: {e}")


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
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Detail Laporan", callback_data="report_monthly"),
            InlineKeyboardButton("💡 Tips Hemat", callback_data="suggest_insight")
        ],
        [
            InlineKeyboardButton("🎯 Target Tabungan", callback_data="list_targets"),
            InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=user.telegram_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

    if now.day in _VISUAL_REPORT_DAYS:
        await _try_send_visual_report(context, user)

    return True


def _build_digest_message(user, expense_txs: list, total_expense: float, now: datetime) -> str:
    """Compose the full digest text with Financial Health Score and Smart Tips."""

    # --- Category breakdown via pandas ---
    df = pd.DataFrame([{"amount": t.amount, "category": t.category} for t in expense_txs])
    cat_summary = df.groupby("category")["amount"].sum().sort_values(ascending=False)

    # --- 7-day trend ---
    trend = _compute_trend(user.id, total_expense)

    # --- Budget status for top category ---
    top_cat = cat_summary.index[0]
    budget_info = budget_mgr.check_budget_status(user.id, top_cat)

    # --- Financial Health Score ---
    health_score, health_label = _calculate_financial_health(user.id, expense_txs, now)

    # --- Smart Tips (AI-driven) ---
    smart_tip = _get_smart_tip(user.id)

    # --- Persona based adjustment ---
    persona = persona_mgr.get_persona(user.id)
    title = f"🌙 *{persona.name.upper()} DIGEST - {now.strftime('%d %B')}*"
    if persona.name == "Bestie Cuan":
        health_intro = f"Gimana kabarnya bestie? Dompetmu lagi {health_label}"
    elif persona.name == "Coach Finansial":
        health_intro = f"Evaluasi harian. Status finansialmu: {health_label}"
    else:
        health_intro = f"Laporan kesehatan keuangan: {health_label}"

    # --- Build message ---
    lines = [
        f"{title}\n",
        f"💰 Total Hari Ini: *Rp{total_expense:,.0f}*",
        f"🏥 Health Score: *{health_score}/100*\n└ {health_intro}",
    ]
    
    if trend:
        lines.append(f"📊 Tren: {trend}")
    
    lines.append("\n📂 *Breakdown Pengeluaran:*")
    for cat, amt in cat_summary.items():
        lines.append(f"  • {cat}: Rp{amt:,.0f}")
        
    if budget_info:
        lines.append(f"\n💡 *Budget Info ({top_cat}):*")
        lines.append(f"  {budget_info}")

    # --- Saving goal (first active one) ---
    goal_block = _build_goal_block(user.id, now)
    if goal_block:
        lines.append(goal_block)

    if smart_tip:
        lines.append(f"\n🧠 *AI Smart Tip:*\n{smart_tip}")

    return "\n".join(lines)


def _calculate_financial_health(user_id: int, today_txs: list, now: datetime) -> tuple[int, str]:
    """
    Calculates a score from 0-100 based on:
    1. Budget adherence (linear drift)
    2. Daily spend vs monthly average
    3. Savings rate (if income is known)
    """
    score = 80 # Default starting point
    
    try:
        # 1. Check for budget drift (major impact)
        budgets = db.get_user_budgets(user_id)
        day_pct = (now.day / 30) * 100
        
        drift_penalty = 0
        for b in budgets:
            if b.limit_amount > 0:
                usage_pct = (b.current_usage / b.limit_amount) * 100
                if usage_pct > day_pct + 10:
                    drift_penalty += 5
                if usage_pct > 100:
                    drift_penalty += 15
        
        score -= min(30, drift_penalty)
        
        # 2. Daily spending vs 7-day average
        last_7 = db.get_sliding_window_transactions(user_id, days=7)
        if last_7:
            daily_total = sum(t.amount for t in today_txs if t.type == "expense")
            avg_daily = sum(t.amount for t in last_7 if t.type == "expense") / 7
            if daily_total > avg_daily * 1.5:
                score -= 10
            elif daily_total < avg_daily * 0.8:
                score += 5
                
        # 3. Savings Rate check
        latest_income = db.get_latest_income(user_id)
        if latest_income and latest_income.amount > 0:
            monthly_expenses = sum(b.current_usage for b in budgets)
            savings_rate = (latest_income.amount - monthly_expenses) / latest_income.amount
            if savings_rate < 0.1:
                score -= 10
            elif savings_rate > 0.3:
                score += 10
                
        score = max(0, min(100, score))
        
        if score >= 85: label = "Sangat Sehat 🌟"
        elif score >= 70: label = "Sehat 👍"
        elif score >= 50: label = "Waspada ⚠️"
        else: label = "Kritis 🚨"
        
        return int(score), label
        
    except Exception as e:
        logger.error(f"Health score calculation failed: {e}")
        return 70, "Cukup Baik"


def _get_smart_tip(user_id: int) -> str:
    """Gets a short, punchy AI tip based on spending patterns."""
    try:
        from modules.analysis import ExpenseAnalyzer
        analyzer_obj = ExpenseAnalyzer(db)
        insights = analyzer_obj.analyze_patterns(user_id)
        
        # Extract a single relevant line or just return a snippet
        lines = [l for l in insights.split('\n') if l.startswith('•')]
        if lines:
            return random.choice(lines).replace('• ', '')
        
        # Fallback to general tips
        tips = [
            "Coba masak di rumah besok untuk hemat kategori Makanan!",
            "Hari ini pengeluaranmu cukup tinggi, coba 'No Spend Day' besok.",
            "Ingat target menabungmu! Sedikit-sedikit lama-lama jadi bukit.",
            "Cek budget kategori paling boros minggu ini di menu Summary.",
            "Langganan yang jarang dipakai sebaiknya dihentikan saja."
        ]
        return random.choice(tips)
    except Exception:
        return "Pertahankan pencatatan rutinmu untuk finansial yang lebih tertata!"


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
        if _is_snoozed(user.id):
            return
        if not _is_preferred_hour(user.id, datetime.now()):
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
        pref_str = pref.decode() if isinstance(pref, (bytes, bytearray)) else str(pref)
        return pref_str != "0"
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

    tone = "santai"
    try:
        redis = RedisManager()
        if redis.client:
            raw_tone = redis.client.get(f"user:{user_id}:reminder_tone")
            if raw_tone is not None:
                tone = (raw_tone.decode() if isinstance(raw_tone, (bytes, bytearray)) else str(raw_tone)).lower()
    except Exception:
        pass

    if tone == "tegas":
        return "Pengingat tegas: catat transaksi terbaru kamu sekarang."
    if tone == "formal":
        return "Pengingat resmi: mohon lakukan pencatatan transaksi terkini."

    # 1. Choose based on time of day
    now = datetime.now()
    if 5 <= now.hour < 11:
        return "Semangat pagi! ☀️ Sudah ada rencana pengeluaran hari ini? Catat di sini ya!"
    elif 11 <= now.hour < 15:
        return "Siang! 🍱 Jangan lupa catat biaya makan siangmu hari ini ya!"
    elif 18 <= now.hour < 23:
        return "Malam! 🌙 Sambil santai, yuk rekap pengeluaranmu hari ini biar gak numpuk."
    
    # 2. Random fallback if no specific time match
    return random.choice(_FALLBACK_REMINDERS)
