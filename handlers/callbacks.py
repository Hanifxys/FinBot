from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from core import db, budget_mgr, rules, visual_reporter
from utils.dashboard import update_pinned_dashboard
from utils.executor import execute_code
from config import CATEGORIES
from datetime import datetime
import os
import logging
import json

def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Cek Budget"), KeyboardButton("📈 Laporan")],
        [KeyboardButton("💡 Tips Hemat"), KeyboardButton("🚀 Menu Utama")]
    ], resize_keyboard=True)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_db = db.get_or_create_user(user_id, update.effective_user.username)
    user_data = context.user_data
    
    await query.answer()
    
    action = query.data
    pending = user_data.get('pending_tx')
    pending_cancel = user_data.get("pending_cancel")

    if action == "open_history":
        from handlers.transactions import history
        original_message = update.message
        update.message = query.message
        try:
            await history(update, context)
        finally:
            update.message = original_message
        return

    if action == "cancel_abort":
        user_data.pop("pending_cancel", None)
        await query.edit_message_text("Oke, pembatalan dibatalkan. ✅")
        return

    if action == "cancel_choose":
        if not pending_cancel or not pending_cancel.get("candidates"):
            await query.message.reply_text("Aku belum nemu kandidat transaksi. Coba tulis: `batal yang 25rb` atau `hapus #ID`.", parse_mode="Markdown")
            return
        keyboard = []
        for c in pending_cancel["candidates"][:5]:
            txid = c.get("id")
            amount = c.get("amount", 0)
            cat = c.get("category", "")
            desc = (c.get("description") or "-")
            if len(desc) > 28:
                desc = desc[:25] + "..."
            keyboard.append([InlineKeyboardButton(f"#{txid} Rp{amount:,.0f} · {cat}", callback_data=f"cancel_pick:{txid}")])
        keyboard.append([InlineKeyboardButton("❌ Tidak jadi", callback_data="cancel_abort")])
        await query.edit_message_text("Pilih transaksi yang mau dibatalkan:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if action.startswith("cancel_pick:"):
        if not pending_cancel:
            await query.message.reply_text("Session pembatalan sudah habis. Coba ulangi perintah pembatalan ya.")
            return
        try:
            tx_id = int(action.split(":", 1)[1])
        except Exception:
            tx_id = None
        if not tx_id:
            await query.message.reply_text("ID transaksi tidak valid.")
            return
        pending_cancel["selected_id"] = tx_id
        user_data["pending_cancel"] = pending_cancel
        keyboard = [
            [
                InlineKeyboardButton("✅ Batalkan (1-klik)", callback_data="cancel_confirm"),
                InlineKeyboardButton("🔁 Pilih lain", callback_data="cancel_choose"),
            ],
            [
                InlineKeyboardButton("📜 Riwayat", callback_data="open_history"),
                InlineKeyboardButton("❌ Tidak jadi", callback_data="cancel_abort"),
            ],
        ]
        await query.edit_message_text(
            f"Siap. Kamu mau membatalkan transaksi `#{tx_id}`. Lanjut?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if action == "cancel_confirm":
        if not pending_cancel or not pending_cancel.get("selected_id"):
            await query.message.reply_text("Aku belum tahu transaksi mana yang harus dibatalkan. Ketik: `batal transaksi terakhir` atau `hapus #ID`.")
            return

        tx_id = int(pending_cancel["selected_id"])
        reason = pending_cancel.get("reason") or ""
        eta_seconds = int(pending_cancel.get("eta_seconds") or 60)

        success = False
        try:
            success = db.delete_transaction(user_db.id, tx_id)
        except Exception as e:
            logging.error(f"Cancel delete failed: {e}")
            success = False

        if success:
            try:
                from core import premium_ai, ws_server
                audit = {
                    "tx_id": tx_id,
                    "reason": reason,
                    "eta_seconds": eta_seconds,
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
                premium_ai.redis.client.lpush(f"cancel_audit:{user_id}", json.dumps(audit))
                premium_ai.redis.client.ltrim(f"cancel_audit:{user_id}", 0, 200)
                if ws_server.loop and ws_server.loop.is_running():
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        ws_server.broadcast_to_user(
                            user_id=user_id,
                            message={
                                "event": "refund_status",
                                "data": {
                                    "tx_id": tx_id,
                                    "status": "success",
                                    "eta_seconds": eta_seconds,
                                },
                            },
                        ),
                        ws_server.loop,
                    )
            except Exception:
                pass

            user_data.pop("pending_cancel", None)
            await query.edit_message_text(
                f"✅ **Berhasil dibatalkan**: transaksi `#{tx_id}`\n⏱️ Estimasi refund: ≤ {eta_seconds} detik",
                parse_mode="Markdown",
            )
            try:
                await update_pinned_dashboard(context, user_id)
            except Exception:
                pass
        else:
            await query.edit_message_text(
                f"❌ Gagal membatalkan transaksi `#{tx_id}`. Coba cek `/history` lalu pakai `/hapus {tx_id}`.",
                parse_mode="Markdown",
            )
        return
    
    if action == "suggest_help":
        from handlers.commands import help_command
        await help_command(update, context)
        return

    if action == "suggest_budget":
        status = budget_mgr.check_budget_status(user_db.id, "Semua")
        await query.message.reply_text(status, reply_markup=get_main_menu_keyboard())
        return

    if action == "suggest_insight":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)
        return

    # --- NEW MENU HANDLERS ---
    if action == "manual_add":
        await query.message.reply_text("💸 **Catat Transaksi**\n\nKetik langsung: `Item Harga`\nContoh: `Kopi 25rb` atau `Gaji 10jt`", parse_mode='Markdown')
        return

    if action == "scan_receipt":
        await query.message.reply_text("📸 **Scan Struk**\n\nSilakan kirim foto struk belanjaan kamu sekarang!", parse_mode='Markdown')
        return

    if action == "list_target":
        from handlers.saving import list_targets
        await list_targets(update, context)
        return

    if action == "set_gaji_menu":
        await query.message.reply_text("💰 **Atur Gaji**\n\nKetik `/setgaji [Nominal]`\nContoh: `/setgaji 10jt`", parse_mode='Markdown')
        return

    if action == "get_report":
        msg = budget_mgr.generate_report(user_db.id, "monthly")
        await query.message.reply_text(msg)
        return

    if action == "get_ai_insight":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)
        return

    if action == "get_profile":
        from handlers.commands import profile_command
        await profile_command(update, context)
        return

    if action == "settings_menu":
        help_text = (
            "⚙️ **Pengaturan**\n\n"
            "• `/setbudget [Kat] [Jml]` - Atur limit kategori\n"
            "• `/budgetalert [Kat] [Warn%] [Limit%]` - Notifikasi\n"
            "• `/hapus [ID]` - Hapus transaksi\n"
            "• `/undo` - Batal transaksi terakhir"
        )
        await query.message.reply_text(help_text, parse_mode='Markdown')
        return

    if action == "export_csv":
        from handlers.transactions import export_data
        await export_data(update, context)
        return
    # -------------------------

    if action == "code_confirm":
        code_to_run = user_data.get('pending_code')
        if code_to_run:
            result = execute_code(code_to_run)
            msg = (
                "Thank you! Your code has been executed successfully. ✅\n\n"
                f"💻 **Output:**\n```\n{result}\n```"
            )
            await query.edit_message_text(msg, parse_mode='Markdown')
            await query.message.reply_text("Apa lagi yang bisa saya bantu? 😊", reply_markup=get_main_menu_keyboard())
            user_data.pop('pending_code', None)
        else:
            await query.edit_message_text("No code found to execute. ❌")
        return

    if action == "code_cancel":
        await query.edit_message_text("Edit cancelled. Feel free to ask again. 👍")
        await query.message.reply_text("Butuh bantuan lainnya?", reply_markup=get_main_menu_keyboard())
        user_data.pop('pending_code', None)
        return

    if action.startswith("report_"):
        period = action.replace("report_", "")
        report_msg = budget_mgr.generate_report(user_db.id, period=period)
        
        now = datetime.now()
        transactions = db.get_monthly_report(user_db.id, now.month, now.year)
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Detail Budget", callback_data="suggest_budget"),
                InlineKeyboardButton("💡 Tips Hemat", callback_data="suggest_insight")
            ],
            [
                InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")
            ]
        ]
        
        await query.edit_message_text(report_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
        photo_path = visual_reporter.generate_expense_pie(transactions, user_id)
        if photo_path:
            try:
                with open(photo_path, 'rb') as photo:
                    await query.message.reply_photo(photo, caption="Visualisasi Pengeluaran Anda")
            except Exception as e:
                logging.error(f"Error sending report photo: {e}")
            finally:
                if os.path.exists(photo_path):
                    os.remove(photo_path)
        return

    if action == "tx_confirm" and pending:
        tx_date = datetime.now()
        if pending.get('date'):
            try:
                date_clean = pending['date'].replace('/', '-')
                if len(date_clean.split('-')[0]) == 4:
                    tx_date = datetime.strptime(date_clean, "%Y-%m-%d")
                else:
                    tx_date = datetime.strptime(date_clean, "%d-%m-%Y")
            except:
                tx_date = datetime.now()

        tags = rules.evaluate({
            "amount": pending['amount'],
            "category": pending['category'],
            "hour": tx_date.hour
        })
        
        description = pending.get('merchant', 'Transaksi')
        if tags:
            description += f" ({', '.join(tags)})"

        db.add_transaction(
            user_id=user_db.id,
            amount=pending['amount'],
            category=pending['category'],
            trans_type='expense',
            description=description,
            trans_date=tx_date
        )
        
        budget_msg = budget_mgr.check_budget_status(user_db.id, pending['category'])
        
        final_msg = f"✅ Tersimpan: Rp{pending['amount']:,.0f} · {pending['category']}"
        if budget_msg:
            final_msg += f"\n\n{budget_msg}"
        else:
            final_msg += "\n\nMau catat transaksi lain atau cek laporan?"
            
        keyboard = [
            [
                InlineKeyboardButton("📊 Cek Budget", callback_data="suggest_budget"),
                InlineKeyboardButton("📈 Laporan", callback_data="report_monthly")
            ],
            [
                InlineKeyboardButton("🚀 Menu Utama", callback_data="suggest_help")
            ]
        ]
            
        await query.edit_message_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text("Ada lagi yang bisa saya bantu?", reply_markup=get_main_menu_keyboard())
        user_data.pop('pending_tx', None)
        user_data.pop('state', None)
        
        await update_pinned_dashboard(context, user_id)
        
    elif action == "tx_edit":
        keyboard = [
            [
                InlineKeyboardButton("Nominal", callback_data="edit_amount"),
                InlineKeyboardButton("Kategori", callback_data="edit_category")
            ],
            [
                InlineKeyboardButton("Tanggal", callback_data="edit_date"),
                InlineKeyboardButton("Abaikan", callback_data="tx_ignore")
            ]
        ]
        await query.edit_message_text("Pilih bagian yang ingin diubah:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "edit_amount":
        user_data['state'] = 'WAITING_EDIT_AMOUNT'
        await query.edit_message_text("Ketik nominal baru (contoh: 50rb atau 50000):")
        
    elif action == "edit_category":
        user_data['state'] = 'WAITING_EDIT_CATEGORY'
        keyboard = []
        for i in range(0, len(CATEGORIES), 2):
            row = [InlineKeyboardButton(cat, callback_data=f"set_cat_{cat}") for cat in CATEGORIES[i:i+2]]
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("Batal", callback_data="tx_edit")])
        await query.edit_message_text("Pilih kategori baru:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action.startswith("set_cat_"):
        new_cat = action.replace("set_cat_", "")
        if pending:
            pending['category'] = new_cat
            user_data['pending_tx'] = pending
            msg = f"Kategori diubah ke: {new_cat}\n\nRp{pending['amount']:,.0f} · {new_cat}"
            keyboard = [
                [
                    InlineKeyboardButton("✓ Simpan", callback_data="tx_confirm"),
                    InlineKeyboardButton("✎ Edit Lagi", callback_data="tx_edit")
                ]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "tx_ignore":
        user_data.pop('pending_tx', None)
        user_data.pop('state', None)
        await query.edit_message_text("Transaksi diabaikan. Ada lagi yang mau dicatat?")
        await query.message.reply_text("Silakan pilih menu di bawah:", reply_markup=get_main_menu_keyboard())

    elif action == "suggest_budget":
        # Handled above
        pass

    elif action == "report_monthly":
        # Already handled by report_ logic, but kept for direct calls
        report_msg = budget_mgr.generate_report(user_db.id, period='monthly')
        await query.message.reply_text(report_msg)

    elif action == "suggest_insight":
        from handlers.finance import get_ai_insight
        await get_ai_insight(update, context)

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Bulan Ini", callback_data="report_monthly"),
            InlineKeyboardButton("7 Hari Terakhir", callback_data="report_7days"),
            InlineKeyboardButton("30 Hari Terakhir", callback_data="report_30days")
        ]
    ]
    
    msg = "Pilih periode laporan:"
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
