from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from core import db, analyzer, ai, budget_mgr
import logging
import os
import hmac, hashlib, time, base64
from datetime import datetime

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

def get_interactive_help_keyboard():
    """UI Baru: Menggantikan slash command dengan tombol interaktif yang menarik"""
    keyboard = [
        [
            InlineKeyboardButton("💸 Catat Manual", callback_data="manual_add"),
            InlineKeyboardButton("📸 Scan Struk", callback_data="scan_receipt")
        ],
        [
            InlineKeyboardButton("🎯 Target Nabung", callback_data="list_target"),
            InlineKeyboardButton("💰 Atur Gaji", callback_data="set_gaji_menu")
        ],
        [
            InlineKeyboardButton("📊 Laporan Lengkap", callback_data="get_report"),
            InlineKeyboardButton("🧠 AI Insights", callback_data="get_ai_insight")
        ],
        [
            InlineKeyboardButton("👤 Profil & Rank", callback_data="get_profile"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")
        ],
        [
            InlineKeyboardButton("📥 Export CSV", callback_data="export_csv")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)
    
    welcome_msg = (
        f"👋 **Halo {user.first_name}!**\n\n"
        "Selamat datang di **FinBot Pro v2.0** dengan engine real-time.\n"
        "Aku asisten keuangan cerdas kamu yang sekarang jauh lebih responsif!\n\n"
        "**Apa yang baru?**\n"
        "✅ **Real-time Dashboard**: Pantau budget secara live.\n"
        "✅ **Gamification**: Naik level dengan mencatat keuangan!\n"
        "✅ **Smart UI**: Gunakan tombol interaktif di bawah.\n\n"
        "Silakan pilih menu di bawah ini untuk memulai! 👇"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_interactive_help_keyboard())

async def reminder_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Toggle 24-hour reminders.
    Usage: /reminder on OR /reminder off
    """
    user = update.effective_user
    args = context.args
    
    if not args:
        await update.message.reply_text("Gunakan `/reminder on` atau `/reminder off`", parse_mode='Markdown')
        return

    action = args[0].lower()
    if action not in ["on", "off"]:
        await update.message.reply_text("Gunakan `/reminder on` atau `/reminder off`", parse_mode='Markdown')
        return
        
    try:
        # Toggle preference in DB/Redis
        # Ideally stored in user_settings table, but for now we can use Redis key
        from core import db
        # We need a way to store this. Let's use Redis for simplicity or DB if available.
        # Assuming we can use RedisManager
        from modules.redis_mgr import RedisManager
        redis = RedisManager()
        
        key = f"user:{user.id}:reminder_enabled"
        if action == "on":
            redis.client.set(key, "1")
            await update.message.reply_text("✅ Reminder harian diaktifkan! Saya akan ingatkan kalau kamu lupa mencatat. 🚀")
        else:
            redis.client.set(key, "0")
            await update.message.reply_text("🔕 Reminder harian dimatikan. Jangan lupa catat sendiri ya! 😉")
            
    except Exception as e:
        await update.message.reply_text(f"Gagal mengubah pengaturan: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 **FINBOT PRO - INTERACTIVE COMMAND CENTER**\n\n"
        "Gunakan tombol di bawah ini untuk mengelola keuanganmu secara instan.\n"
        "Sistem kami sekarang didukung oleh **Redis Pub/Sub** untuk kecepatan maksimal.\n\n"
        "**💡 Tips Cepat:**\n"
        "Ketik `kopi 25rb` untuk mencatat transaksi tanpa buka menu."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=get_interactive_help_keyboard())
    else:
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_interactive_help_keyboard())

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Issue a short-lived web token so user can login to the web app.
    """
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)
    secret = os.getenv("WEB_JWT_SECRET", "")
    if not secret:
        await update.message.reply_text("Auth sedang tidak tersedia (secret belum dikonfigurasi).")
        return
    exp = int(time.time()) + 3600
    payload = f"{user.id}.{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    token = f"{payload}.{base64.urlsafe_b64encode(sig).decode()}"
    await update.message.reply_text(
        "Token login web (berlaku 1 jam):\n"
        f"{token}\n\n"
        "Gunakan sebagai Bearer token di aplikasi web.",
        disable_web_page_preview=True
    )

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Show monthly or yearly summary.
    Usage: /summary monthly OR /summary yearly 2026
    """
    user = update.effective_user
    user_db = db.get_or_create_user(user.id, user.username)
    args = context.args or []
    try:
        if len(args) == 0 or args[0].lower() == "monthly":
            msg = budget_mgr.generate_report(user_db.id, "monthly")
            await update.message.reply_text(msg)
        elif args[0].lower() == "yearly":
            year = int(args[1]) if len(args) > 1 else datetime.now().year
            # msg = budget_mgr.generate_report(user_db.id, "yearly", year=year) # Assuming supported
            msg = "Laporan tahunan belum tersedia."
            await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Gagal membuat laporan: {e}")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user gamification profile"""
    user = update.effective_user
    from core import gamify
    
    profile = await gamify.get_user_profile(user.id)
    
    level = profile.get("level", 1)
    xp = profile.get("xp", 0)
    title = profile.get("title", "Pemula")
    next_xp = profile.get("next_level_xp", 100)
    progress = profile.get("progress_percent", 0)
    streak = profile.get("streak", 0)
    badges = profile.get("badges", [])
    health_score = profile.get("health_score", 0)
    
    badges_str = " ".join(badges) if badges else "Belum ada badge"
    
    # Visual Progress Bar
    bar_length = 10
    filled_length = int(bar_length * progress // 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    
    # Health Score Indicator
    health_icon = "🟢" if health_score >= 80 else "🟡" if health_score >= 50 else "🔴"
    
    msg = (
        f"👤 **PROFIL PENGGUNA: {user.first_name}**\n\n"
        f"🏆 **Level {level}: {title}**\n"
        f"✨ XP: {xp} / {next_xp}\n"
        f"[{bar}] {progress}%\n\n"
        f"🏥 **Financial Health:** {health_icon} {health_score}/100\n"
        f"🔥 **Daily Streak:** {streak} hari\n"
        f"🏅 **Badges:**\n{badges_str}\n\n"
        f"_Terus aktif mencatat keuangan untuk naik level!_ 🚀"
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

async def set_persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Switch AI Persona Mode.
    Usage: /mode coach | buddy | analyst
    """
    args = context.args
    if not args:
        await update.message.reply_text(
            "Pilih mode personalitas AI:\n"
            "- `/mode coach`: Galak & Disiplin 😤\n"
            "- `/mode buddy`: Santai & Bestie 🥰\n"
            "- `/mode analyst`: Formal & Data 🧐",
            parse_mode='Markdown'
        )
        return

    mode = args[0].lower()
    if mode not in ["coach", "buddy", "analyst"]:
        await update.message.reply_text("Mode tidak valid. Pilih: coach, buddy, atau analyst.")
        return
        
    user_id = update.effective_user.id
    from core import premium_ai
    
    new_p = premium_ai.persona_mgr.set_persona(user_id, mode)
    
    await update.message.reply_text(f"✅ Mode ganti ke: **{new_p.name}**\n_{new_p.tone}_", parse_mode='Markdown')
