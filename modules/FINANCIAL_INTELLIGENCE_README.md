# Financial Intelligence Module (Premium)

Sistem kecerdasan finansial tingkat lanjut untuk analisis pengeluaran, prediksi arus kas, dan deteksi anomali menggunakan Machine Learning.

## Fitur Utama

### 1. Analisis Dasar
- **Category Average**: Analisis time-series pengeluaran per kategori dengan perhitungan pertumbuhan bulanan.
- **Budget Drift**: Deteksi penyimpangan anggaran real-time berdasarkan progres waktu dalam bulan berjalan.
- **Anomaly Detection**: Menggunakan algoritma **Isolation Forest** untuk mendeteksi transaksi yang tidak wajar.

### 2. Prediksi & Skoring
- **Cashflow Forecast**: Proyeksi arus kas menggunakan metode **Holt-Winters Exponential Smoothing**.
- **Financial Health Score**: Penilaian kesehatan keuangan (0-1000) berdasarkan 4 parameter: Likuiditas, Rasio Tabungan, Kontrol Hutang, dan Diversifikasi Pengeluaran.

### 3. Advanced Analytics
- **Pattern Modelling**: Pengelompokan kebiasaan belanja menggunakan **K-Means Clustering**.
- **Behaviour Correlation**: Analisis korelasi antara waktu gajian (*payday*) dengan lonjakan pengeluaran.

## Teknologi & Spesifikasi
- **Machine Learning**: Scikit-learn (Isolation Forest, KMeans)
- **Time Series**: Statsmodels (Exponential Smoothing)
- **Caching**: Redis untuk pemrosesan real-time yang optimal.
- **Performance**: Implementasi penuh `async/await`.
- **Quality**: Tipe petunjuk (*type hints*), logging terstruktur (JSON), dan penanganan error komprehensif.

## Penggunaan

```python
from modules.financial_intelligence import FinancialIntelligenceEngine
from database.db_handler import DBHandler

db = DBHandler()
engine = FinancialIntelligenceEngine(db_handler=db)

# Mendapatkan skor kesehatan finansial
health = await engine.calculate_health_score(user_id=123)
print(f"Score: {health['total_score']} - Rating: {health['rating']}")

# Prediksi arus kas 30 hari ke depan
forecast = await engine.forecast_cashflow(user_id=123, days=30)
```

## Pengujian & Benchmark
Jalankan unit test:
```bash
pytest tests/test_financial_intelligence.py
```

Jalankan benchmark performa:
```bash
python scripts/benchmark_fin_intel.py
```
