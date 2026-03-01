from datetime import time, datetime, timezone
import logging
import os
import threading
import sys
import asyncio
import time as _time
import uuid
import atexit
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, TypeHandler

from config import TELEGRAM_BOT_TOKEN
from core import init_components, db, ocr, nlp, ai, budget_mgr, analyzer, rules, visual_reporter
from modules.redis_mgr import RedisManager
from handlers.commands import (
    start, help_command, auth_command, summary_command, profile_command,
    reminder_settings, set_persona_command, challenge_command, rewards_command, telemetry_command,
    recurring_settings_command,
    memory_insight_command, realintel_command, financial_persona_command,
    debt_optimizer_command, scenario_command, networth_command,
    set_asset_command, set_liability_command,
)
from handlers.finance import set_gaji, set_budget, get_ai_insight, set_budget_alerts
from handlers.transactions import undo, hapus_transaksi, history, export_data
from handlers.saving import set_target, add_savings, list_targets
from handlers.text_handler import handle_text
from handlers.media_handler import handle_photo, handle_voice, handle_document
from handlers.callbacks import handle_callback
from handlers.digest import daily_digest, smart_reminder_check, monthly_wrapper_job
from middlewares.logging import log_update
from telegram import BotCommand

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

_POLLING_LOCK_KEY = None
_POLLING_LOCK_VALUE = None
_POLLING_LOCK_REDIS = None

def _release_polling_lock():
    global _POLLING_LOCK_KEY, _POLLING_LOCK_VALUE, _POLLING_LOCK_REDIS
    try:
        if _POLLING_LOCK_REDIS and _POLLING_LOCK_KEY and _POLLING_LOCK_VALUE:
            current = _POLLING_LOCK_REDIS.get(_POLLING_LOCK_KEY)
            if current == _POLLING_LOCK_VALUE:
                _POLLING_LOCK_REDIS.delete(_POLLING_LOCK_KEY)
    except Exception:
        pass

atexit.register(_release_polling_lock)

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
            _release_polling_lock()
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
        BotCommand("challenge", "Lihat weekly challenge"),
        BotCommand("rewards", "Redeem reward dari XP"),
        BotCommand("telemetry", "On/off analytics anonymized"),
        BotCommand("recurring", "Atur sensitivitas recurring suggestion"),
        BotCommand("memory", "AI long-term financial narrative"),
        BotCommand("realintel", "Inflasi & lifestyle creep intelligence"),
        BotCommand("fpersona", "Set financial risk persona"),
        BotCommand("debt", "Debt optimizer snowball vs avalanche"),
        BotCommand("simulate", "Scenario simulation finansial"),
        BotCommand("networth", "Lihat net worth aset-liabilitas"),
        BotCommand("asset", "Set nilai aset"),
        BotCommand("liability", "Set nilai liability"),
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
        lock_ttl = int(os.getenv("POLLING_LOCK_TTL_SECONDS", "30"))
        retry_s = int(os.getenv("POLLING_LOCK_RETRY_SECONDS", "5"))
        instance_id = os.getenv("KOYEB_INSTANCE_ID", "") or str(uuid.uuid4())
        lock_value = f"{instance_id}:{os.getpid()}:{int(_time.time())}"

        while True:
            try:
                acquired = rm.client.set(lock_key, lock_value, nx=True, ex=lock_ttl)
            except Exception:
                acquired = False
            if acquired:
                break
            try:
                ttl = rm.client.ttl(lock_key)
            except Exception:
                ttl = None
            if isinstance(ttl, int) and ttl > 0:
                logging.error(f"Polling lock is held; waiting ~{ttl}s.")
            else:
                logging.error("Polling lock is held; bot polling is waiting.")
            _time.sleep(max(5, retry_s))

        _POLLING_LOCK_KEY = lock_key
        _POLLING_LOCK_VALUE = lock_value
        _POLLING_LOCK_REDIS = rm.client

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
    
    # Register bot instance to monitor dependencies for broadcast/DM support
    try:
        from modules.monitor import set_bot_instance
        set_bot_instance(application.bot)
        logging.info("Bot registered to Monitor system successfully.")
    except Exception as e:
        logging.error(f"Failed to register bot to monitor: {e}")

    application.add_error_handler(error_handler)
    
    # Enhanced Logging for Startup
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"--- FinBot Pro Startup at {now_str} ---")
    logging.info(f"Instance ID: {os.getenv('KOYEB_INSTANCE_ID', 'Local')}")
    
    job_queue = application.job_queue
    # Daily Digest at 21:00 WIB (14:00 UTC)
    job_queue.run_daily(daily_digest, time(hour=14, minute=0, tzinfo=timezone.utc))
    # Monthly Wrapper on 1st of every month at 09:00 WIB (02:00 UTC)
    job_queue.run_monthly(monthly_wrapper_job, when=time(hour=2, minute=0, tzinfo=timezone.utc), day=1)
    # 24-hour Intelligent Reminder Check (runs every hour to check inactive users)
    job_queue.run_repeating(smart_reminder_check, interval=3600, first=60)
    
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
    application.add_handler(CommandHandler("reminder", reminder_settings))
    application.add_handler(CommandHandler("mode", set_persona_command))
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("rewards", rewards_command))
    application.add_handler(CommandHandler("telemetry", telemetry_command))
    application.add_handler(CommandHandler("recurring", recurring_settings_command))
    application.add_handler(CommandHandler("memory", memory_insight_command))
    application.add_handler(CommandHandler("realintel", realintel_command))
    application.add_handler(CommandHandler("fpersona", financial_persona_command))
    application.add_handler(CommandHandler("debt", debt_optimizer_command))
    application.add_handler(CommandHandler("simulate", scenario_command))
    application.add_handler(CommandHandler("networth", networth_command))
    application.add_handler(CommandHandler("asset", set_asset_command))
    application.add_handler(CommandHandler("liability", set_liability_command))
    application.add_handler(CommandHandler("rekomendasi", set_gaji))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logging.info("FinBot sedang berjalan...")
    sys.stdout.flush()
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logging.error(f"Bot exited with error: {e}")
    finally:
        pass
