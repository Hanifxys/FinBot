# 🚀 Panduan Deployment FinBot (Koyeb + Supabase)

Ikuti langkah-langkah ini agar bot kamu aktif 24/7 secara gratis!

## 1. Persiapan GitHub
1. Buat repository baru di GitHub (disarankan **Private**).
2. Upload semua file project kamu ke sana, **KECUALI** file `.env` dan folder `database/`.
   - File penting yang harus ada: `bot.py`, `config.py`, `requirements.txt`, `Procfile`, `runtime.txt`, dan folder `modules/`, `database/`, `utils/`.

## 2. Persiapan Database (Supabase)
1. Buka [Supabase](https://supabase.com/) dan buat project baru.
2. Pergi ke **Project Settings** > **Database**.
3. Copy **Connection String** (pilih mode **URI**).
   - Contoh: `postgresql://postgres:password@db.id.supabase.co:5432/postgres`

## 3. Deployment ke Koyeb
1. Daftar/Login di [Koyeb](https://app.koyeb.com/).
2. Klik **Create Service**.
3. Pilih **GitHub** sebagai deployment method.
4. Pilih repository FinBot kamu.
5. Di bagian **Environment Variables**, tambahkan:
   - `TELEGRAM_BOT_TOKEN`: (Token dari BotFather)
   - `DATABASE_URL`: (Link URI dari Supabase tadi)
6. Di bagian **Build and Run settings**:
   - Koyeb biasanya otomatis mendeteksi `Procfile`. Jika tidak, masukkan Command: `python bot.py`.
7. Klik **Deploy**.

## 4. Selesai!
Koyeb akan memproses build sekitar 2-5 menit. Setelah statusnya **Healthy**, bot kamu sudah aktif di Telegram selamanya!

---
**Catatan:** Karena kita pakai Supabase, data keuangan kamu aman tersimpan di sana meskipun server Koyeb di-restart.
