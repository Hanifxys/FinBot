"""
handlers.py — FinBot Pro Telegram Command & Callback Handlers
Refactored for safety, consistency, and maintainability.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime
from enum import Enum
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import (
    ai,
    analyzer,
    budget_mgr,
    db,
    weekly_challenges,
    gamify,
    ux_analytics,
    recurring_mgr,
    personal_finance_ai,
    premium_ai,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class PersonaMode(str, Enum):
    COACH = "coach"
    BUDDY = "buddy"
    ANALYST = "analyst"

    @classmethod
    def descriptions(cls) -> str:
        return (
            "Pilih mode personalitas AI:\n"
            "• `/mode coach` — Galak & Disiplin 😤\n"
            "• `/mode buddy` — Santai & Bestie 🥰\n"
            "• `/mode analyst` — Formal & Data 🧐"
        )


class FinancialPersonaMode(str, Enum):
    CONSERVATIVE = "conservative"
    GROWTH_AGGRESSIVE = "growth_aggressive"
    RISK_AVOIDER = "risk_avoider"
    OVER_SPENDER = "over_spender"


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
            [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")],
        ],
        resize_keyboard=True,
    )


def get_interactive_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💸 Catat Transaksi", callback_data="manual_add"),
                InlineKeyboardButton("📸 Scan Struk", callback_data="scan_receipt"),
            ],
            [
                InlineKeyboardButton("📊 Laporan", callback_data="get_report"),
                InlineKeyboardButton("💡 Tips Hemat", callback_data="get_tips"),
            ],
            [
                InlineKeyboardButton("🎯 Target Nabung", callback_data="list_target"),
                InlineKeyboardButton("👤 Profil", callback_data="get_profile"),
            ],
            [
                InlineKeyboardButton("⚙️ Pengaturan", callback_data="settings_menu"),
                InlineKeyboardButton("📥 Export", callback_data="export_csv"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

_TOKEN_VERSION = "v1"


def _issue_web_token(user_id: int, secret: str, ttl_seconds: int = 3_600) -> str:
    """Return a signed web login token using the same format as web_server.py."""
    exp = int(time.time()) + ttl_seconds
    payload = f"{_TOKEN_VERSION}.{user_id}.{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(sig).decode()}"


# ---------------------------------------------------------------------------
# Reply helpers — reduce boilerplate in every handler
# ---------------------------------------------------------------------------

async def _reply(update: Update, text: str, **kwargs) -> None:
    """
    Unified reply helper that works for both direct messages and callback queries.
    For callback queries it sends a NEW message (safer than always editing).
    """
    if update.callback_query:
        await update.callback_query.message.reply_text(text, **kwargs)
    elif update.message:
        await update.message.reply_text(text, **kwargs)
    else:
        logger.warning("_reply called but no message or callback_query found in update")


async def _edit_or_reply(update: Update, text: str, **kwargs) -> None:
    """
    Try to edit an existing callback message (avoids duplicate messages),
    fall back to a new reply if editing isn't possible.
    """
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, **kwargs)
            return
        except Exception:
            pass
    await _reply(update, text, **kwargs)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)

    welcome_msg = (
        f"👋 *Halo {user.first_name}!*\n\n"
        "Selamat datang di *FinBot Pro v2.0* dengan engine real-time.\n"
        "Aku asisten keuangan cerdas kamu yang sekarang jauh lebih responsif!\n\n"
        "*Apa yang baru?*\n"
        "✅ *Real-time Dashboard*: Pantau budget secara live.\n"
        "✅ *Gamification*: Naik level dengan mencatat keuangan\\!\n"
        "✅ *Smart UI*: Gunakan tombol interaktif di bawah.\n\n"
        "Silakan pilih menu di bawah ini untuk memulai\\! 👇"
    )
    await update.message.reply_text(
        welcome_msg,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=get_interactive_help_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "💡 *Pusat Bantuan FinBot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Halo! Aku asisten finansialmu. Kamu bisa mengobrol denganku secara natural atau menggunakan menu di bawah.\n\n"
        "✨ *Apa yang bisa aku bantu?*\n"
        "• *Catat*: `kopi 25rb` atau `gaji 10jt`\n"
        "• *Pantau*: `sisa budget` atau `laporan bulan ini`\n"
        "• *Kelola*: `riwayat transaksi` atau `hapus transaksi #123`\n"
        "• *Analisis*: `apa dampaknya kalo beli hp 5jt?`\n\n"
        "Gunakan tombol interaktif di bawah untuk akses cepat! 👇"
    )
    await _edit_or_reply(
        update,
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_interactive_help_keyboard(),
    )


async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Issue a short-lived web login token via /auth."""
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)

    secret = os.getenv("WEB_JWT_SECRET", "")
    if not secret:
        logger.error("WEB_JWT_SECRET not configured — cannot issue web token")
        await update.message.reply_text(
            "⚠️ Auth sedang tidak tersedia. Hubungi admin."
        )
        return

    token = _issue_web_token(user.id, secret)
    logger.info("Web token issued for telegram_id=%d", user.id)

    await update.message.reply_text(
        "🔐 *Token login web* \\(berlaku 1 jam\\):\n\n"
        f"`{token}`\n\n"
        "Gunakan sebagai Bearer token di aplikasi web\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Show monthly or yearly summary.
    Usage: /summary [monthly] | /summary yearly [YEAR]
    """
    user = update.effective_user
    user_db = db.get_or_create_user(user.id, user.username)
    args = context.args or []

    period = args[0].lower() if args else "monthly"

    try:
        if period == "monthly":
            msg = budget_mgr.generate_report(user_db.id, "monthly")

        elif period == "yearly":
            year = _parse_year(args[1] if len(args) > 1 else None)
            msg = budget_mgr.generate_report(user_db.id, "yearly", year=year)

        else:
            await update.message.reply_text(
                "Gunakan `/summary monthly` atau `/summary yearly [tahun]`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await update.message.reply_text(msg)

    except ValueError as exc:
        await update.message.reply_text(f"⚠️ Input tidak valid: {exc}")
    except Exception as exc:
        logger.exception("summary_command failed for user=%d", user.id)
        await update.message.reply_text("❌ Gagal membuat laporan. Coba lagi nanti.")


async def reminder_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Toggle 24-hour reminders.
    Usage: /reminder on | /reminder off
    """
    user = update.effective_user
    args = context.args or []

    if not args:
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
        await update.message.reply_text("Pengaturan reminder personal:", reply_markup=kb)
        return

    if args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            "Gunakan `/reminder` untuk menu lengkap, atau `/reminder on|off`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    action = args[0].lower()

    try:
        from modules.redis_mgr import RedisManager

        redis = RedisManager()
        if not redis.client:
            raise RuntimeError("Redis tidak tersedia saat ini.")

        key = f"user:{user.id}:reminder_enabled"
        redis.client.set(key, "1" if action == "on" else "0")

        if action == "on":
            msg = "✅ Reminder harian diaktifkan\\! Saya akan ingatkan kalau kamu lupa mencatat\\. 🚀"
        else:
            msg = "🔕 Reminder harian dimatikan\\. Jangan lupa catat sendiri ya\\! 😉"

        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("Reminder %s for user=%d", action, user.id)

    except Exception as exc:
        logger.error("reminder_settings failed user=%d: %s", user.id, exc)
        await update.message.reply_text("❌ Gagal mengubah pengaturan. Coba lagi nanti.")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user gamification profile."""
    user = update.effective_user

    try:
        from core import gamify

        profile = await gamify.get_user_profile(user.id)
    except Exception as exc:
        logger.exception("profile_command failed for user=%d", user.id)
        await _reply(update, "❌ Gagal memuat profil. Coba lagi nanti.")
        return

    level = profile.get("level", 1)
    xp = profile.get("xp", 0)
    title = profile.get("title", "Pemula")
    next_xp = profile.get("next_level_xp", 100)
    progress = int(profile.get("progress_percent", 0))
    streak = profile.get("streak", 0)
    badges = profile.get("badges", [])
    health_score = profile.get("health_score", 0)

    badges_str = " ".join(badges) if badges else "Belum ada badge"

    bar_length = 10
    filled = int(bar_length * progress / 100)
    bar = "█" * filled + "░" * (bar_length - filled)

    health_icon = "🟢" if health_score >= 80 else "🟡" if health_score >= 50 else "🔴"

    msg = (
        f"👤 **PROFIL: {user.first_name}**\n\n"
        f"🏆 **Level {level}: {title}**\n"
        f"✨ XP: {xp} / {next_xp}\n"
        f"[{bar}] {progress}%\n\n"
        f"🏥 **Financial Health:** {health_icon} {health_score}/100\n"
        f"🔥 **Daily Streak:** {streak} hari\n"
        f"🏅 **Badges:** {badges_str}\n\n"
        "_Terus aktif mencatat keuangan untuk naik level\\!_ 🚀"
    )

    await _reply(update, msg, parse_mode=ParseMode.MARKDOWN_V2)


async def set_persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Switch AI persona mode.
    Accessible via NLP: "ganti mode coach", "ubah ke buddy".
    """
    args = context.args or []

    # If no args, check if value was extracted from NLP
    if not args and "args" in context.user_data:
         # Try to recover args from user_data if passed from NLP handler
         # (though context.args is usually populated by message handler)
         pass

    if not args:
        await update.message.reply_text(
            PersonaMode.descriptions(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    mode_input = args[0].lower()
    try:
        mode = PersonaMode(mode_input)
    except ValueError:
        await update.message.reply_text(
            "Mode tidak valid. Pilih: `coach`, `buddy`, atau `analyst`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user_id = update.effective_user.id

    try:
        from core import premium_ai

        new_persona = premium_ai.persona_mgr.set_persona(user_id, mode.value)
        await update.message.reply_text(
            f"✅ Mode ganti ke: *{new_persona.name}*\n_{new_persona.tone}_",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info("Persona set to %s for user=%d", mode.value, user_id)

    except Exception as exc:
        logger.exception("set_persona_command failed for user=%d", user_id)
        await update.message.reply_text("❌ Gagal mengganti mode. Coba lagi nanti.")


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    item = weekly_challenges.get_current(user_id)
    msg = (
        f"Weekly Challenge: **{item.get('title', '-') }**\n"
        f"{item.get('description', '-')}\n\n"
        f"Progress: {item.get('progress', 0)}/{item.get('target', 1)}\n"
        f"Reward: +{item.get('reward_xp', 0)} XP"
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Share progress", callback_data="challenge:share")]]
    )
    await _reply(update, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    market = weekly_challenges.get_marketplace()
    profile = await gamify.get_user_profile(user_id)
    xp = int(profile.get("xp", 0))
    lines = [f"Reward Marketplace (XP kamu: {xp})", ""]
    kb_rows = []
    for item in market:
        lines.append(f"- {item['name']} ({item['cost_xp']} XP)")
        kb_rows.append([InlineKeyboardButton(item["name"], callback_data=f"reward:redeem:{item['id']}")])
    await _reply(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))


async def telemetry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await _reply(
            update,
            "Telemetry status default: ON (minimal anonymized metrics).\nGunakan `/telemetry off` untuk opt-out, `/telemetry on` untuk aktifkan.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    action = args[0].strip().lower()
    if action not in {"on", "off"}:
        await _reply(update, "Gunakan `/telemetry on` atau `/telemetry off`.", parse_mode=ParseMode.MARKDOWN)
        return
    user_id = update.effective_user.id
    ok = ux_analytics.set_consent(user_id, allowed=(action == "on"))
    if ok:
        await _reply(update, f"Telemetry {'diaktifkan' if action == 'on' else 'dinonaktifkan'} untuk akun kamu.")
    else:
        await _reply(update, "Gagal mengubah pengaturan telemetry saat ini.")


async def recurring_settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Configure recurring suggestion sensitivity.
    Usage: /recurring [2-6]
    """
    user_id = update.effective_user.id
    args = context.args or []

    if not args:
        current = recurring_mgr.get_sensitivity(user_id)
        await _reply(
            update,
            (
                "Sensitivity recurring suggestion kamu saat ini: "
                f"`{current}`\n"
                "Gunakan `/recurring 2` (lebih sensitif) s.d. `/recurring 6` (lebih ketat)."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        value = int(args[0])
    except ValueError:
        await _reply(update, "Gunakan angka 2 sampai 6. Contoh: `/recurring 3`.", parse_mode=ParseMode.MARKDOWN)
        return

    ok = recurring_mgr.set_sensitivity(user_id, value)
    if not ok:
        await _reply(update, "Gagal menyimpan pengaturan recurring saat ini.")
        return
    saved = recurring_mgr.get_sensitivity(user_id)
    await _reply(update, f"Sensitivity recurring di-set ke `{saved}`.", parse_mode=ParseMode.MARKDOWN)


async def memory_insight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    result = personal_finance_ai.long_term_narrative(user_id, user_db.id)
    lines = [
        "AI Memory Insight",
        f"- Save intent mentions: {result.get('save_intent_mentions', 0)}",
        f"- Weekend spending (recent): {result.get('weekend_spend_ratio_recent', 0)}%",
        f"- Weekend spending (previous): {result.get('weekend_spend_ratio_previous', 0)}%",
        "",
        "Narrative:",
    ]
    for n in result.get("narrative", []):
        lines.append(f"- {n}")
    await _reply(update, "\n".join(lines))


async def realintel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Financial Command Centre: Unified Intelligence View.
    """
    user_id = update.effective_user.id
    from core import fin_intel, market_data

    # Send typing action or loading message
    status_msg = await update.message.reply_text("⏳ *Mengakses satelit data finansial...*", parse_mode=ParseMode.MARKDOWN)

    try:
        # Fetch Intelligence
        intel = await fin_intel.get_financial_health_status(user_id, market_data)

        score = intel["score"]
        color = "🟢" if score >= 80 else "🟡" if score >= 50 else "🔴"
        
        survival = intel["survival_days"]
        survival_str = f"{survival} hari" if survival < 999 else "∞ (Aman)"
        
        deficit = intel["deficit_probability"]
        deficit_color = "🟢" if deficit < 20 else "🔴" if deficit > 50 else "🟡"

        savings = intel["savings_rate"]
        stress = intel["stress_index"]
        stress_color = "🟢" if stress == "Low" else "🔴" if stress == "High" else "🟡"

        macro = intel.get("macro_sensitivity", {})
        delta = intel.get("delta", 0)
        delta_str = f"({'+' if delta >= 0 else ''}{delta})"
        trajectory = intel.get("trajectory", "Stable")
        risk = intel.get("risk_profile", [])
        conf = intel.get("confidence", 0)
        
        # Actionable Insight
        action = "Pertahankan performa ini! 👍"
        if score < 50:
            action = "⚠️ **URGENT:** Kurangi pengeluaran non-esensial segera & lunasi utang berbunga tinggi."
        elif score < 80:
            action = "💡 **Saran:** Tingkatkan dana darurat hingga minimal 6 bulan pengeluaran."
            
        msg = (
            f"🛡️ **FINANCIAL COMMAND CENTRE**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"**Financial Stability Score**\n"
            f"__ {color} **{score}/100** {color} __ {delta_str}\n"
            f"📈 **Trajectory:** {trajectory}\n"
            f"🔐 **Confidence:** {conf}%\n\n"
            
            f"📊 **Kondisi Saat Ini:**\n"
            f"• **Survival Mode:** `{survival_str}`\n"
            f"• **Deficit Prob:** {deficit_color} `{deficit}%`\n"
            f"• **Savings Rate:** `{savings:.1f}%`\n"
            f"• **Stress Level:** {stress_color} `{stress}`\n\n"
            
            f"⚠️ **Risk Profile:**\n"
            f"{', '.join(risk) if risk else '✅ Low Risk'}\n\n"
            
            f"🚀 **Executive Action:**\n"
            f"{action}\n\n"
            
            f"🌍 **Personal Macro Sensitivity:**\n"
            f"🏦 **Suku Bunga:**\n_{macro.get('interest_rate', '-')}_\n\n"
            f"📈 **Inflasi:**\n_{macro.get('inflation', '-')}_\n\n"
            f"💸 **Kurs Rupiah:**\n_{macro.get('currency', '-')}_\n\n"
            f"📉 **Market Crash:**\n_{macro.get('market_crash', '-')}_\n"
        )
        
        # Delete loading message and send real report
        await status_msg.delete()
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"RealIntel failed: {e}")
        await status_msg.edit_text("❌ Gagal mengakses data intelijen. Coba lagi nanti.")


async def financial_persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args or []
    if not args:
        profile = premium_ai.persona_mgr.get_financial_profile(user_id=user_id)
        await _reply(
            update,
            (
                f"Financial Persona: {profile.get('persona')}\n"
                f"Risk tolerance: {profile.get('risk_tolerance')}\n"
                f"Strategy: {profile.get('strategy')}\n"
                f"Guardrails: {', '.join(profile.get('guardrails', []))}\n\n"
                "Gunakan `/fpersona conservative|growth_aggressive|risk_avoider|over_spender`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    choice = args[0].strip().lower()
    if choice not in {m.value for m in FinancialPersonaMode}:
        await _reply(update, "Pilihan invalid. Gunakan conservative/growth_aggressive/risk_avoider/over_spender.")
        return
    profile = premium_ai.persona_mgr.set_financial_persona(user_id, choice)
    await _reply(
        update,
        f"Financial persona di-set ke: {profile.get('persona')} (risk={profile.get('risk_tolerance')})",
    )


async def debt_optimizer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    extra = 500000.0
    if context.args:
        try:
            extra = float(context.args[0])
        except Exception:
            pass
    result = personal_finance_ai.debt_optimizer(user_db.id, extra_payment=extra)
    if not result.get("ok"):
        await _reply(update, result.get("msg", "Tidak ada data utang."))
        return
    msg = (
        "Debt Optimizer\n"
        f"- Recommended: {result['recommended']}\n"
        f"- Snowball: {result['snowball']['months']} bulan, interest ~{result['snowball']['interest_est']:.0f}\n"
        f"- Avalanche: {result['avalanche']['months']} bulan, interest ~{result['avalanche']['interest_est']:.0f}\n"
        f"- Est. interest savings: {result['interest_savings_est']:.0f}\n\n"
        "Debts:"
    )
    for d in result.get("debts", []):
        msg += f"\n- {d['name']}: balance {d['balance']:.0f}, APR {d['apr']*100:.1f}%, min {d['min_payment']:.0f}"
    await _reply(update, msg)


async def scenario_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    if not context.args:
        await _reply(
            update,
            "Gunakan: `/simulate [skenario]`\nContoh: `/simulate resign 6 bulan lagi`\natau `/simulate cicilan motor 2 juta/bulan`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    text = " ".join(context.args)
    result = personal_finance_ai.simulate_scenario(user_db.id, text)
    if not result.get("ok"):
        await _reply(update, result.get("msg", "Gagal simulasi."))
        return
    msg = (
        "Scenario Simulation\n"
        f"- Event: {result['event']}\n"
        f"- Avg income: {result['avg_income']:.0f}\n"
        f"- Avg expense: {result['avg_expense']:.0f}\n"
        f"- Burn rate: {result['burn_rate']:.0f}\n"
        f"- Income after scenario: {result['income_after']:.0f}\n"
        f"- Expense after scenario: {result['expense_after']:.0f}\n"
        f"- Emergency coverage: {result['emergency_coverage_months']} bulan\n"
        f"- Risk probability: {result['risk_probability']}"
    )
    await _reply(update, msg)


async def networth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    result = personal_finance_ai.net_worth(user_db.id)
    msg = (
        "Net Worth Tracker\n"
        f"- Total assets: {result['total_assets']:.0f}\n"
        f"- Total liabilities: {result['total_liabilities']:.0f}\n"
        f"- Net worth: {result['net_worth']:.0f}\n"
        f"- Monthly delta: {result['monthly_delta']:.0f} ({result['monthly_delta_pct']}%)"
    )
    await _reply(update, msg)


async def set_asset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    if len(context.args) < 2:
        await _reply(update, "Gunakan `/asset [nama] [nominal]` contoh `/asset crypto 1500000`", parse_mode=ParseMode.MARKDOWN)
        return
    name = context.args[0]
    try:
        amount = float(context.args[1])
    except Exception:
        await _reply(update, "Nominal tidak valid.")
        return
    ok = personal_finance_ai.set_asset(user_db.id, name, amount)
    await _reply(update, "Asset tersimpan." if ok else "Gagal simpan asset.")


async def set_liability_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    if len(context.args) < 2:
        await _reply(update, "Gunakan `/liability [nama] [nominal]` contoh `/liability cc 3000000`", parse_mode=ParseMode.MARKDOWN)
        return
    name = context.args[0]
    try:
        amount = float(context.args[1])
    except Exception:
        await _reply(update, "Nominal tidak valid.")
        return
    ok = personal_finance_ai.set_liability(user_db.id, name, amount)
    await _reply(update, "Liability tersimpan." if ok else "Gagal simpan liability.")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_year(raw: Optional[str]) -> int:
    """Parse a year string, defaulting to current year. Raises ValueError if invalid."""
    if raw is None:
        return datetime.now().year
    try:
        year = int(raw)
    except ValueError:
        raise ValueError(f"'{raw}' bukan tahun yang valid.")
    if not (2000 <= year <= 2100):
        raise ValueError(f"Tahun harus antara 2000–2100, bukan {year}.")
    return year
