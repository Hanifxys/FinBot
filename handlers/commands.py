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

from core import ai, analyzer, budget_mgr, db

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
        "Halo! Aku asisten finansialmu. Kamu bisa mengelola keuangan dengan mudah di sini.\n\n"
        "✨ *Cara Cepat Pencatatan:*\n"
        "Langsung ketik saja, contoh:\n"
        "• `kopi 25rb`\n"
        "• `gaji masuk 10jt`\n"
        "• `bayar listrik 200k`\n\n"
        "Gunakan menu di bawah untuk fitur lainnya! 👇"
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

    if not args or args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            "Gunakan `/reminder on` atau `/reminder off`",
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
    Usage: /mode coach | buddy | analyst
    """
    args = context.args or []

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