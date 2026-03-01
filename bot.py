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
    # Register Commands for UI Menu Hint only (Slash commands still work as fallback but are deprecated)
    commands = [
        BotCommand("start", "Mulai bot & Registrasi"),
        BotCommand("help", "Tampilkan menu bantuan"),
        BotCommand("menu", "Menu Utama"),
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    # Initialize Core Components (includes Database, AI, and Monitoring Server)
    init_components()
    
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN is missing! Check .env file.")
        sys.exit(1)

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # --- Handlers Registration ---
    
    # 1. Global Message Handler (The Brain) - Handles Text & Commands via NLP
    # We remove specific CommandHandlers to force everything through NLP engine
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # 2. Legacy Command Fallback (Optional: keep for /start, /help specifically)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # 3. Media Handlers
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # 4. Callback Query Handler (Buttons)
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # 5. Error Handler
    application.add_error_handler(error_handler)

    # 6. Scheduled Jobs
    job_queue = application.job_queue
    if job_queue:
        # Daily Digest at 07:00 WIB (00:00 UTC)
        job_queue.run_daily(daily_digest, time=time(0, 0, tzinfo=timezone.utc), name="daily_digest")
        # Smart Reminder Check every hour
        job_queue.run_repeating(smart_reminder_check, interval=3600, first=60, name="smart_reminders")
        # Monthly Wrapper at 1st of month
        job_queue.run_monthly(monthly_wrapper_job, when=time(1, 0, tzinfo=timezone.utc), day=1, name="monthly_wrapper")

    logging.info("🤖 FinBot Pro is RUNNING (Natural Language Mode)...")
    
    # Start Polling with Conflict Resolution
    # ... (existing lock logic)
    
    logging.info("FinBot sedang berjalan...")
    sys.stdout.flush()
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logging.error(f"Bot exited with error: {e}")
    finally:
        pass
