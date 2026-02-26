from telegram import Update
from telegram.ext import ContextTypes
from core import db
from utils.dashboard import update_pinned_dashboard
import os
from datetime import datetime
import logging
from database.models import Tables

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
    for tx in txs[:15]: # Show last 15
        type_icon = "🔻" if tx.type == 'expense' else "🔹"
        msg += f"{type_icon} `#{tx.id}` | {tx.date.strftime('%d/%m')} | {tx.category} | **Rp{tx.amount:,.0f}**\n_{tx.description or '-'}_\n"
    
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

    filename = f"export_transaksi_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    
    try:
        import io
        import pandas as pd

        response = db.supabase.table(Tables.TRANSACTIONS).select("*").eq("user_id", user_db.id).order("date", desc=True).execute()
        if response.data:
            def parse_date(date_str):
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    return date_str

            df = pd.DataFrame([{
                'Tanggal': (lambda d: d.strftime('%Y-%m-%d %H:%M') if isinstance(d, datetime) else str(d))(parse_date(tx['date'])),
                'Tipe': 'Pengeluaran' if tx['type'] == 'expense' else 'Pemasukan',
                'Kategori': tx['category'],
                'Nominal': f"Rp{tx['amount']:,.0f}",
                'Catatan': (db.crypto.decrypt(tx['description']) if tx.get('description') else '-') 
            } for tx in response.data])

            buf = io.StringIO()
            df.to_csv(buf, index=False)
            bio = io.BytesIO(buf.getvalue().encode("utf-8"))
            bio.name = filename
            await msg.reply_document(document=bio, filename=filename, caption="📊 Ini data transaksi kamu dalam format CSV.")
        else:
            await msg.reply_text("Belum ada data transaksi untuk diekspor. Yuk mulai catat! 📝")
    except Exception as e:
        await msg.reply_text(f"Gagal mengekspor data: {e}")
