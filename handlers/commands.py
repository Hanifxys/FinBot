from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, analyzer, ai
import logging

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)
    
    welcome_msg = (
        f"👋 **Halo {user.first_name}!**\n\n"
        "Selamat datang di **FinBot Pro**, asisten keuangan cerdas kamu. "
        "Aku bisa bantu kamu catat pengeluaran, pantau budget, dan kasih analisa cerdas biar kamu makin hemat!\n\n"
        "**Cara Mulai:**\n"
        "1. Ketik: `makan 20rb` (Catat cepat)\n"
        "2. Kirim: Foto struk 📸 (Scan otomatis)\n"
        "3. Ketik: `/setgaji 5jt` (Atur budget bulanan)\n\n"
        "Gunakan menu di bawah untuk akses cepat! 👇"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 **FINBOT PRO - COMMAND CENTER**\n\n"
        "**💸 PENCATATAN**\n"
        "- Langsung ketik: `kopi 25rb` atau `gaji 10jt`\n"
        "- Kirim foto struk 📸 untuk scan otomatis\n"
        "- `/undo`: Batal transaksi terakhir\n"
        "- `/hapus [ID]`: Hapus transaksi spesifik\n\n"
        "**🎯 SAVING GOALS**\n"
        "- `/target [Nama] [Nominal]`: Buat target baru\n"
        "- `/nabung [ID] [Nominal]`: Tambah tabungan ke target\n"
        "- `/list_target`: Lihat semua target menabung\n\n"
        "**📊 LAPORAN & EXPORT**\n"
        "- `/history`: Riwayat transaksi (bisa filter `cat:`, `min:`)\n"
        "- `/insight`: Analisis cerdas pola pengeluaran 🧠\n"
        "- `/export`: Download data transaksi ke CSV/Excel 📥\n\n"
        "**⚙️ PENGATURAN**\n"
        "- `/setgaji [Nominal]`: Atur pendapatan bulanan\n"
        "- `/setbudget [Kategori] [Nominal]`: Atur limit budget\n\n"
        "💡 *Tips: Dashboard terupdate otomatis di pesan yang di-pin!*"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
