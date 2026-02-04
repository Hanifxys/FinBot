# Product Requirements Document (PRD) - FinBot: Asisten Keuangan Pribadi Telegram

## 1. Pendahuluan
FinBot adalah bot Telegram yang dirancang untuk membantu pengguna mengelola keuangan pribadi secara otomatis. Bot ini mengintegrasikan teknologi OCR, NLP, dan manajemen budget untuk memberikan pengalaman pelacakan keuangan yang seamless.

## 2. Tujuan
- Memudahkan pencatatan pengeluaran tanpa input manual yang rumit.
- Memberikan visibilitas real-time terhadap sisa anggaran (budget).
- Menganalisis kebiasaan belanja pengguna melalui laporan periodik.

## 3. Fitur Utama
### 3.1. Pencatatan Transaksi Otomatis
- **OCR Struk Belanja**: Pengguna mengirimkan foto struk, bot mengekstrak total nominal dan item (jika memungkinkan).
- **Parsing Notifikasi Bank (Simulasi)**: Membaca teks transfer atau riwayat pembayaran yang dikirim pengguna.
- **Kategorisasi Otomatis**: Transaksi dikelompokkan ke dalam kategori (Makanan, Transportasi, Belanja, Gaji, dll).

### 3.2. Manajemen Budget & Alokasi Otomatis
- **Input Gaji**: Pengguna dapat memasukkan gaji bulanan.
- **Rekomendasi Otomatis**: Sistem memberikan saran alokasi berdasarkan aturan 50/20/10/20 (Kebutuhan, Tabungan, Investasi, Hiburan).
- **Set Limit**: Pengguna dapat menetapkan batas anggaran per kategori.
- **Real-time Tracking**: Setiap transaksi baru akan memotong sisa budget kategori terkait.
- **Alert System**: Notifikasi saat pengeluaran mencapai 80% dan 100% dari limit.

### 3.3. Analisis Pola (Machine Learning)
- **Pattern Analysis**: Menganalisis kategori pengeluaran terbesar dan tren harian.
- **Personalized Suggestions**: Memberikan saran penghematan atau pengalokasian dana berdasarkan pola belanja.

### 3.4. Pelaporan Visual
- **Grafik Pie**: Visualisasi proporsi pengeluaran per kategori.
- **Laporan Periodik**: Laporan harian, mingguan, dan bulanan dalam format teks dan gambar.

## 4. Spesifikasi Teknis
- **Bahasa Pemrograman**: Python 3.10+
- **Library Bot**: `python-telegram-bot`
- **Database**: SQLite (untuk penyimpanan lokal yang ringan)
- **OCR Engine**: Tesseract OCR atau EasyOCR (Open Source)
- **NLP**: Rule-based matching & Regex (untuk efisiensi bahasa Indonesia)
- **Hosting**: Kompatibel dengan VPS atau server lokal (Linux/Windows)

## 5. Flow Bisnis (Ringkasan)
1. User mengirim input (Gambar/Teks).
2. Bot mendeteksi tipe input.
3. Jika Gambar -> Proses OCR -> Ekstrak Nominal & Kategori.
4. Jika Teks -> Proses NLP -> Ekstrak Perintah/Transaksi.
5. Simpan ke Database.
6. Update Budget & Beri feedback ke User.

## 6. Kriteria Keberhasilan
- Akurasi OCR > 80% pada struk yang jelas.
- Waktu respon bot < 3 detik.
- Data tersimpan aman dan konsisten di database.
