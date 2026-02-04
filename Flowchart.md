# Flowchart Bisnis FinBot

Berikut adalah alur proses bisnis dari FinBot menggunakan diagram Mermaid:

```mermaid
graph TD
    A[User Mengirim Input] --> B{Tipe Input?}
    
    B -- Foto Struk --> C[Modul OCR]
    B -- Pesan Teks --> D[Modul NLP]
    
    C --> E[Ekstraksi Nominal & Item]
    D --> F[Identifikasi Perintah/Transaksi]
    
    E --> G[Kategorisasi Otomatis]
    F --> G
    
    G --> H{Apakah Transaksi?}
    H -- Ya --> I[Simpan ke Database]
    H -- Tidak/Query --> J[Proses Laporan/Informasi]
    
    I --> K[Update Sisa Budget]
    K --> L{Melebihi Limit?}
    
    L -- Ya --> M[Kirim Notifikasi Peringatan]
    L -- Tidak --> N[Kirim Konfirmasi Berhasil]
    
    J --> O[Kirim Data Laporan/Sisa Budget]
    M --> P[Selesai]
    N --> P
    O --> P
```

### Penjelasan Singkat:
1. **Input**: User bisa mengirimkan gambar struk atau teks biasa.
2. **Processing**: Sistem membedakan antara kebutuhan ekstraksi data (OCR) atau pemahaman bahasa (NLP).
3. **Categorization**: Data yang didapat diklasifikasikan ke kategori yang sesuai.
4. **Database**: Semua data transaksi disimpan untuk pelacakan jangka panjang.
5. **Budget Check**: Setiap transaksi divalidasi terhadap limit anggaran yang sudah diatur user.
6. **Output**: Bot memberikan respon balik berupa konfirmasi, peringatan, atau laporan yang diminta.
