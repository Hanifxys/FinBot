from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from core import db, analyzer, ai
import logging

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
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"),
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
        "✅ **Smart UI**: Gunakan tombol interaktif di bawah.\n"
        "✅ **Dua Arah**: Bot bisa kasih notifikasi instan!\n\n"
        "Silakan pilih menu di bawah ini untuk memulai! 👇"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_interactive_help_keyboard())

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
