import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///database/finbot.db")

# Fix for Heroku/Railway PostgreSQL URL (replace postgres:// with postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
TESSERACT_PATH = os.getenv("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# Categories for classification
CATEGORIES = ["Makanan", "Transportasi", "Belanja", "Tagihan", "Investasi", "Gaji", "Lain-lain"]

# Allocation Rules (50/20/10/20 standard)
ALLOCATION_RULES = {
    "Kebutuhan Pokok": 0.50, # Makanan + Transport + Tagihan
    "Tabungan": 0.20,
    "Investasi": 0.10,
    "Hiburan/Fleksibel": 0.20
}
