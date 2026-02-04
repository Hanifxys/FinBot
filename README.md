# FinBot: Telegram Personal Finance Assistant

FinBot adalah bot Telegram yang membantu Anda mencatat pengeluaran, mengelola budget, dan menganalisis transaksi keuangan secara otomatis menggunakan OCR dan NLP.

## Fitur Utama
- **Auto-OCR**: Kirim foto struk belanja, bot akan membaca totalnya.
- **Smart NLP**: Kirim pesan teks natural seperti "makan siang 50rb".
- **Budgeting**: Set limit bulanan per kategori dan terima peringatan real-time.
- **Reporting**: Laporan bulanan otomatis untuk melihat ringkasan pengeluaran.
- **Bank Integration (Simulasi)**: Mendukung pembacaan teks notifikasi bank/transfer.

## Teknologi
- Python 3.10+
- `python-telegram-bot` (Interface Bot)
- `EasyOCR` (Ekstraksi teks gambar)
- `SQLAlchemy` & `SQLite` (Penyimpanan data)
- `Pandas` (Analisis data & Laporan)

## Cara Instalasi

1. **Clone Repositori**:
   ```bash
   git clone <repository_url>
   cd finbot
   ```

2. **Instal Dependensi**:
   Pastikan Anda sudah memiliki Python dan pip terinstal.
   ```bash
   pip install -r requirements.txt
   ```

3. **Konfigurasi Environment**:
   Salin file `.env.example` menjadi `.env` dan isi token bot Telegram Anda.
   ```bash
   cp .env.example .env
   ```
   Dapatkan token dari [@BotFather](https://t.me/BotFather) di Telegram.

4. **Menjalankan Bot**:
   ```bash
   python bot.py
   ```

## Struktur Proyek
- `bot.py`: Entry point utama aplikasi.
- `modules/`: Modul logika (OCR, NLP, Budgeting).
- `database/`: Handler database dan model ORM.
- `utils/`: Fungsi pembantu (helpers).
- `tests/`: Unit testing.

## Lisensi
Proyek ini menggunakan teknologi Open Source dan tersedia secara gratis.
