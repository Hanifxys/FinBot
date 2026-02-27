import csv
import io
import logging
from telegram import Update
from telegram.ext import ContextTypes
from core import db
from utils.dashboard import update_pinned_dashboard
from datetime import datetime
from database.models import Tables

logger = logging.getLogger(__name__)

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    success = db.undo_last_transaction(user_db.id)
    if success:
        await update.message.reply_text("✅ Transaksi terakhir berhasil dibatalkan!")
        await update_pinned_dashboard(update, context)
    else:
        await update.message.reply_text("❌ Tidak ada transaksi yang bisa dibatalkan.")

async def hapus_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if not context.args:
        await update.message.reply_text("Gunakan `/hapus [ID]`\nCek ID di `/history`", parse_mode='Markdown')
        return

    try:
        tx_id = int(context.args[0])
        success = db.delete_transaction(user_db.id, tx_id)
        if success:
            await update.message.reply_text(f"✅ Transaksi #{tx_id} berhasil dihapus.")
            await update_pinned_dashboard(update, context)
        else:
            await update.message.reply_text(f"❌ Transaksi #{tx_id} tidak ditemukan atau bukan milikmu.")
    except ValueError:
        await update.message.reply_text("ID harus berupa angka.")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    # Simple history for now
    txs = db.get_monthly_report(user_db.id, datetime.now().month, datetime.now().year)
    if not txs:
        await update.message.reply_text("Belum ada riwayat transaksi bulan ini.")
        return

    msg = "📜 **RIWAYAT TRANSAKSI BULAN INI**\n\n"
    from utils.visuals import format_currency
    for tx in txs[:15]: # Show last 15
        type_icon = "🔻" if tx.type == 'expense' else "🔹"
        date_str = tx.date.strftime('%d/%m') if hasattr(tx.date, 'strftime') else str(tx.date)[:10]
        msg += f"{type_icon} `#{tx.id}` | {date_str} | {tx.category} | **{format_currency(tx.amount)}**\n_{tx.description or '-'}_\n"
    
    if len(txs) > 15:
        msg += f"\n...dan {len(txs)-15} transaksi lainnya. Gunakan `/export` untuk data lengkap."
        
    await update.message.reply_text(msg, parse_mode='Markdown')

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    await msg.reply_text("⏳ **Sedang menyiapkan data...**", parse_mode='Markdown')
    
    filename = f"export_transaksi_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    
    try:
        response = db.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_db.id).order("date", desc=True).execute()
        if response.data:
            # Use CSV module instead of pandas for lighter memory usage
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['Tanggal', 'Tipe', 'Kategori', 'Nominal', 'Catatan'])
            
            for tx in response.data:
                # Parse date safely
                date_val = tx['date']
                try:
                    if isinstance(date_val, str):
                        dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d %H:%M')
                    else:
                        date_str = str(date_val)
                except:
                    date_str = str(date_val)

                tipe = 'Pengeluaran' if tx['type'] == 'expense' else 'Pemasukan'
                
                # Decrypt description if needed
                desc = tx.get('description') or ''
                if desc:
                    try:
                        desc = db.crypto.decrypt(desc)
                    except:
                        pass
                
                writer.writerow([
                    date_str,
                    tipe,
                    tx['category'],
                    tx['amount'],
                    desc or '-'
                ])

            output.seek(0)
            bio = io.BytesIO(output.getvalue().encode("utf-8"))
            bio.name = filename
            
            await msg.reply_document(document=bio, filename=filename, caption="📊 Ini data transaksi kamu dalam format CSV.")
        else:
            await msg.reply_text("Belum ada data transaksi untuk diekspor. Yuk mulai catat! 📝")
    except Exception as e:
        logger.error(f"Export Error: {e}")
        await msg.reply_text("Maaf, gagal mengekspor data saat ini. Coba lagi nanti ya.")
