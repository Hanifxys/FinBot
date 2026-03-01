import csv
import io
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core import db
from database.models import Tables
from utils.dashboard import update_pinned_dashboard

logger = logging.getLogger(__name__)


def _history_filter_kb(active_filter: str = "all", active_category: str = "") -> InlineKeyboardMarkup:
    cat_label = f"Kategori: {active_category}" if active_category else "Kategori"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Hari ini", callback_data="hist:today"),
                InlineKeyboardButton("Minggu ini", callback_data="hist:week"),
            ],
            [
                InlineKeyboardButton("Nominal terbesar", callback_data="hist:top"),
                InlineKeyboardButton(cat_label, callback_data="hist:cat"),
            ],
            [InlineKeyboardButton("Semua", callback_data="hist:all")],
        ]
    )


def _tx_action_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Edit", callback_data=f"hist:item:{tx_id}:edit"),
                InlineKeyboardButton("Hapus", callback_data=f"hist:item:{tx_id}:delete"),
                InlineKeyboardButton("Duplikat", callback_data=f"hist:item:{tx_id}:dup"),
            ]
        ]
    )


def _fetch_filtered_history(user_db_id: int, filter_name: str, category_filter: str = ""):
    now = datetime.now()
    start_date = None
    min_amount = None

    if filter_name == "today":
        start_date = datetime(now.year, now.month, now.day)
    elif filter_name == "week":
        start_date = now - timedelta(days=7)
    elif filter_name == "top":
        min_amount = 100_000

    txs = db.get_transactions_history(
        user_db_id,
        limit=50,
        category=category_filter or None,
        start_date=start_date,
        min_amount=min_amount,
    )
    if filter_name == "top":
        txs = sorted(txs, key=lambda t: float(getattr(t, "amount", 0) or 0), reverse=True)
    return txs


def _render_tx_line(tx) -> str:
    from utils.visuals import format_currency

    type_icon = "🔻" if tx.type == "expense" else "🔹"
    date_str = tx.date.strftime("%d/%m %H:%M") if hasattr(tx.date, "strftime") else str(tx.date)[:16]
    return (
        f"{type_icon} `#{tx.id}` | {date_str}\n"
        f"{tx.category} | **{format_currency(tx.amount)}**\n"
        f"_{tx.description or '-'}_"
    )


def _find_tx_by_id(user_db_id: int, tx_id: int):
    txs = db.get_transactions_history(user_db_id, limit=200)
    for tx in txs:
        if int(getattr(tx, "id", 0) or 0) == int(tx_id):
            return tx
    return None


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    success = db.undo_last_transaction(user_db.id)
    if success:
        await update.message.reply_text("✅ Transaksi terakhir berhasil dibatalkan.")
        await update_pinned_dashboard(update, context)
    else:
        await update.message.reply_text("❌ Tidak ada transaksi yang bisa dibatalkan.")


async def hapus_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    if not context.args:
        await update.message.reply_text("Gunakan `/hapus [ID]`\nCek ID di `/history`", parse_mode="Markdown")
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
    if not user_db:
        return

    msg_target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg_target:
        return

    filter_name = (context.user_data.get("history_filter") or "all").strip().lower()
    category_filter = (context.user_data.get("history_category") or "").strip()

    txs = _fetch_filtered_history(user_db.id, filter_name, category_filter)
    if not txs:
        await msg_target.reply_text(
            "Belum ada riwayat sesuai filter ini.",
            reply_markup=_history_filter_kb(filter_name, category_filter),
        )
        return

    titles = {
        "today": "RIWAYAT: HARI INI",
        "week": "RIWAYAT: MINGGU INI",
        "top": "RIWAYAT: NOMINAL TERBESAR",
        "all": "RIWAYAT: SEMUA",
    }
    title = titles.get(filter_name, "RIWAYAT")
    if category_filter:
        title += f" ({category_filter})"

    await msg_target.reply_text(
        f"📜 **{title}**\nPilih filter cepat di bawah.",
        parse_mode="Markdown",
        reply_markup=_history_filter_kb(filter_name, category_filter),
    )

    for tx in txs[:10]:
        await msg_target.reply_text(
            _render_tx_line(tx),
            parse_mode="Markdown",
            reply_markup=_tx_action_kb(int(getattr(tx, "id", 0) or 0)),
        )

    if len(txs) > 10:
        await msg_target.reply_text(f"...dan {len(txs) - 10} transaksi lainnya.")


async def duplicate_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: int):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return False

    tx = _find_tx_by_id(user_db.id, tx_id)
    if not tx:
        return False

    db.add_transaction(
        user_id=user_db.id,
        amount=float(getattr(tx, "amount", 0) or 0),
        category=getattr(tx, "category", "Lain-lain"),
        description=getattr(tx, "description", "Duplikat transaksi"),
        trans_type=getattr(tx, "type", "expense"),
        trans_date=datetime.now(),
    )
    return True


def load_pending_update(context: ContextTypes.DEFAULT_TYPE, user_db_id: int, tx_id: int) -> bool:
    tx = _find_tx_by_id(user_db_id, tx_id)
    if not tx:
        return False
    context.user_data["pending_update"] = {
        "amount": float(getattr(tx, "amount", 0) or 0),
        "category": getattr(tx, "category", "Lain-lain"),
        "merchant": getattr(tx, "description", "Transaksi"),
        "date": getattr(tx, "date", datetime.now()).strftime("%Y-%m-%d") if hasattr(getattr(tx, "date", None), "strftime") else str(getattr(tx, "date", datetime.now()))[:10],
        "type": getattr(tx, "type", "expense"),
        "id": int(getattr(tx, "id", tx_id) or tx_id),
    }
    return True


async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db:
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    await msg.reply_text("⏳ **Sedang menyiapkan data...**", parse_mode="Markdown")
    filename = f"export_transaksi_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"

    try:
        response = (
            db.supabase.table(Tables.TRANSACTIONS)
            .select("*")
            .eq("user_id", user_db.id)
            .order("date", desc=True)
            .execute()
        )
        if not response.data:
            await msg.reply_text("Belum ada data transaksi untuk diekspor.")
            return

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Tanggal", "Tipe", "Kategori", "Nominal", "Catatan"])

        for tx in response.data:
            date_val = tx["date"]
            try:
                if isinstance(date_val, str):
                    dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = str(date_val)
            except Exception:
                date_str = str(date_val)

            tipe = "Pengeluaran" if tx["type"] == "expense" else "Pemasukan"
            desc = tx.get("description") or ""
            if desc:
                try:
                    desc = db.crypto.decrypt(desc)
                except Exception:
                    pass
            writer.writerow([date_str, tipe, tx["category"], tx["amount"], desc or "-"])

        output.seek(0)
        bio = io.BytesIO(output.getvalue().encode("utf-8"))
        bio.name = filename
        await msg.reply_document(document=bio, filename=filename, caption="Ini data transaksi kamu (CSV).")
    except Exception as exc:
        logger.error("Export Error: %s", exc)
        await msg.reply_text("Maaf, gagal mengekspor data saat ini.")

