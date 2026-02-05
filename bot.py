import logging
import os
import threading
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, TypeHandler
from datetime import time, datetime
import pytz

from config import TELEGRAM_BOT_TOKEN
from core import init_components, db, ocr, nlp, ai, budget_mgr, analyzer, rules, visual_reporter
from handlers.commands import start, help_command
from handlers.finance import set_gaji, set_budget, get_ai_insight
from handlers.transactions import undo, hapus_transaksi, history, export_data
from handlers.saving import set_target, add_savings, list_targets
from handlers.messages import handle_message, handle_photo
from handlers.callbacks import handle_callback
from handlers.digest import daily_digest
from middlewares.logging import log_update
from telegram import BotCommand

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_check_server():
    try:
        port = int(os.getenv("PORT", 8000))
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        logging.info(f"✅ Health check server started on port {port}")
        sys.stdout.flush()
        server.serve_forever()
    except Exception as e:
        logging.error(f"❌ Failed to start health check server: {e}")
        sys.stdout.flush()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"Exception while handling an update: {context.error}")
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logging.error("CRITICAL: Conflict error detected! Another instance is running with the same token.")

async def post_init(application):
    commands = [
        BotCommand("start", "Mulai bot & Registrasi"),
        BotCommand("help", "Tampilkan menu bantuan"),
        BotCommand("setgaji", "Atur pendapatan bulanan"),
        BotCommand("setbudget", "Atur limit budget kategori"),
        BotCommand("undo", "Batalkan transaksi terakhir"),
        BotCommand("hapus", "Hapus transaksi spesifik"),
        BotCommand("history", "Lihat riwayat transaksi"),
        BotCommand("target", "Buat target menabung baru"),
        BotCommand("nabung", "Tambah tabungan ke target"),
        BotCommand("list_target", "Lihat semua target menabung"),
        BotCommand("export", "Download data transaksi CSV"),
        BotCommand("insight", "Analisis cerdas pola pengeluaran"),
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()
    
    init_components()
    
    if not TELEGRAM_BOT_TOKEN:
        logging.error("Error: TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
        exit(1)
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    application.add_error_handler(error_handler)
    
    job_queue = application.job_queue
    job_queue.run_daily(daily_digest, time(hour=14, minute=0, tzinfo=pytz.UTC))
    
    # Logging Middleware (Group -1 runs before other groups)
    application.add_handler(TypeHandler(object, log_update), group=-1)
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setgaji", set_gaji))
    application.add_handler(CommandHandler("setbudget", set_budget))
    application.add_handler(CommandHandler("undo", undo))
    application.add_handler(CommandHandler("hapus", hapus_transaksi))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("target", set_target))
    application.add_handler(CommandHandler("nabung", add_savings))
    application.add_handler(CommandHandler("list_target", list_targets))
    application.add_handler(CommandHandler("export", export_data))
    application.add_handler(CommandHandler("insight", get_ai_insight))
    application.add_handler(CommandHandler("rekomendasi", set_gaji))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("FinBot sedang berjalan...")
    application.run_polling(drop_pending_updates=True)
