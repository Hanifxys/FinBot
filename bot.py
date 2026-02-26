from datetime import time, datetime, timezone
import logging
import os
import threading
import sys
import asyncio
import time as _time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, TypeHandler

from config import TELEGRAM_BOT_TOKEN
from core import init_components, db, ocr, nlp, ai, budget_mgr, analyzer, rules, visual_reporter
from modules.redis_mgr import RedisManager
from handlers.commands import start, help_command, auth_command, summary_command, profile_command
from handlers.finance import set_gaji, set_budget, get_ai_insight, set_budget_alerts
from handlers.transactions import undo, hapus_transaksi, history, export_data
from handlers.saving import set_target, add_savings, list_targets
from handlers.messages import handle_message, handle_photo, handle_voice
from handlers.callbacks import handle_callback
from handlers.digest import daily_digest
from middlewares.logging import log_update
from telegram import BotCommand

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"Exception while handling an update: {context.error}")
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logging.error("CRITICAL: Conflict error detected! Another instance is running with the same token.")
        if os.getenv("EXIT_ON_CONFLICT", "1") == "1":
            try:
                rm = RedisManager()
                if rm.client:
                    backoff_s = int(os.getenv("CONFLICT_BACKOFF_SECONDS", "60"))
                    rm.client.set("finbot:polling_backoff_until", str(int(_time.time()) + backoff_s), ex=backoff_s)
            except Exception:
                pass
            try:
                await context.application.stop()
            except Exception:
                pass
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(2, lambda: os._exit(0))
            except Exception:
                os._exit(0)

async def post_init(application):
    commands = [
        BotCommand("start", "Mulai bot & Registrasi"),
        BotCommand("help", "Tampilkan menu bantuan"),
        BotCommand("profile", "Lihat level & XP gamification"),
        BotCommand("setgaji", "Atur pendapatan bulanan"),
        BotCommand("setbudget", "Atur limit budget kategori"),
        BotCommand("budgetalert", "Atur ambang peringatan budget"),
        BotCommand("undo", "Batalkan transaksi terakhir"),
        BotCommand("hapus", "Hapus transaksi spesifik"),
        BotCommand("history", "Lihat riwayat transaksi"),
        BotCommand("target", "Buat target menabung baru"),
        BotCommand("nabung", "Tambah tabungan ke target"),
        BotCommand("list_target", "Lihat semua target menabung"),
        BotCommand("export", "Download data transaksi CSV"),
        BotCommand("insight", "Analisis cerdas pola pengeluaran"),
        BotCommand("summary", "Ringkasan bulanan/tahunan"),
        BotCommand("auth", "Dapatkan token login web"),
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    # Initialize Core Components (includes Database, AI, and Monitoring Server)
    init_components()
    
    if not TELEGRAM_BOT_TOKEN:
        logging.error("Error: TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
        exit(1)

    rm = RedisManager()
    if rm.client and os.getenv("ENABLE_POLLING_LOCK", "1") == "1":
        try:
            backoff_until = rm.client.get("finbot:polling_backoff_until")
            if backoff_until and int(backoff_until) > int(_time.time()):
                sleep_s = int(backoff_until) - int(_time.time())
                logging.error(f"Polling paused due to recent Conflict. Sleeping {sleep_s}s.")
                _time.sleep(max(1, sleep_s))
        except Exception:
            pass

        lock_key = os.getenv("POLLING_LOCK_KEY", "finbot:polling_lock")
        lock_ttl = int(os.getenv("POLLING_LOCK_TTL_SECONDS", "90"))
        retry_s = int(os.getenv("POLLING_LOCK_RETRY_SECONDS", "20"))
        instance_id = os.getenv("KOYEB_INSTANCE_ID", "") or str(uuid.uuid4())
        lock_value = f"{instance_id}:{os.getpid()}:{int(_time.time())}"

        while True:
            try:
                acquired = rm.client.set(lock_key, lock_value, nx=True, ex=lock_ttl)
            except Exception:
                acquired = False
            if acquired:
                break
            logging.error("Polling lock is held by another instance; bot polling is waiting.")
            _time.sleep(max(5, retry_s))

        def _refresh_lock():
            while True:
                try:
                    current = rm.client.get(lock_key)
                    if current != lock_value:
                        return
                    rm.client.expire(lock_key, lock_ttl)
                except Exception:
                    pass
                _time.sleep(max(5, int(lock_ttl / 3)))

        threading.Thread(target=_refresh_lock, daemon=True).start()
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    application.add_error_handler(error_handler)
    
    job_queue = application.job_queue
    job_queue.run_daily(daily_digest, time(hour=14, minute=0, tzinfo=timezone.utc))
    
    # Logging Middleware (Group -1 runs before other groups)
    application.add_handler(TypeHandler(object, log_update), group=-1)
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("setgaji", set_gaji))
    application.add_handler(CommandHandler("setbudget", set_budget))
    application.add_handler(CommandHandler("budgetalert", set_budget_alerts))
    application.add_handler(CommandHandler("undo", undo))
    application.add_handler(CommandHandler("hapus", hapus_transaksi))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("target", set_target))
    application.add_handler(CommandHandler("nabung", add_savings))
    application.add_handler(CommandHandler("list_target", list_targets))
    application.add_handler(CommandHandler("export", export_data))
    application.add_handler(CommandHandler("insight", get_ai_insight))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(CommandHandler("rekomendasi", set_gaji))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logging.info("FinBot sedang berjalan...")
    sys.stdout.flush()
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logging.error(f"Bot exited with error: {e}")
    finally:
        pass
