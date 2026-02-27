# Bug Findings (2026-02-27)

Berikut daftar bug yang ditemukan dari quick validation.

## Environment / Tooling

### 1) Pytest default config gagal tanpa plugin coverage
- **Severity**: Medium
- **Lokasi**: `pyproject.toml` (pytest `addopts`)
- **Repro**:
  ```bash
  pytest -q tests/test_basic.py tests/test_modules.py tests/test_amounts.py
  ```
- **Actual**: `pytest: error: unrecognized arguments: --cov=modules --cov=database --cov-report=term-missing`
- **Expected**: Test tetap bisa jalan pada environment minimal, atau dependency `pytest-cov` dipastikan ada.
- **Catatan**: Workaround saat ini `-o addopts=''`.

## Functional / API Mismatch

### 2) `GROQ_API_KEY` bisa `None` tapi test mengasumsikan selalu ada
- **Severity**: Low
- **Lokasi**: `config.py` + `tests/test_basic.py::test_environment_vars`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_basic.py
  ```
- **Actual**: Assertion gagal `assert GROQ_API_KEY is not None`.
- **Expected**: Default yang konsisten, atau test mengikuti kontrak baru (opsional).

### 3) Constructor `VisualReporter` tidak menerima argumen `output_dir`
- **Severity**: High
- **Lokasi**: `utils/visuals.py` vs `tests/test_modules.py::{test_visual_reporter,test_visual_reporter_empty}`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_visual_reporter
  ```
- **Actual**: `TypeError: VisualReporter.__init__() got an unexpected keyword argument 'output_dir'`
- **Expected**: API constructor sinkron dengan pemakaian/test.

### 4) `AIEngine.parse_transaction` async tapi dipakai sebagai sync di test
- **Severity**: High
- **Lokasi**: `modules/ai_engine.py` vs `tests/test_modules.py::test_ai_engine_no_client`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_ai_engine_no_client
  ```
- **Actual**: Return coroutine object, assertion `is None` gagal.
- **Expected**: Konsistensi interface (async end-to-end atau wrapper sync).

### 5) Property `AIEngine.client` tidak punya setter
- **Severity**: Medium
- **Lokasi**: `modules/ai_engine.py` vs `tests/test_modules.py::{test_ai_engine_parsing,test_ai_engine_insight}`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_ai_engine_parsing
  ```
- **Actual**: `AttributeError: property 'client' of 'AIEngine' object has no setter`
- **Expected**: Bisa dependency injection untuk testing, atau test diubah mengikuti API publik.

### 6) `NLPProcessor` tidak punya method `process_text`
- **Severity**: High
- **Lokasi**: `modules/nlp.py` vs `tests/test_modules.py::test_nlp_process_text`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_nlp_process_text
  ```
- **Actual**: `AttributeError: 'NLPProcessor' object has no attribute 'process_text'`
- **Expected**: Method tersedia atau nama method di test dipindah ke API yang benar.

### 7) Return type `RuleEngine.evaluate` tidak cocok dengan ekspektasi test
- **Severity**: Medium
- **Lokasi**: `modules/rules.py` vs `tests/test_modules.py::test_rule_engine`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_rule_engine
  ```
- **Actual**: Return list of dict, test cek string `'boros' in tags1` sehingga gagal.
- **Expected**: Kontrak output jelas (misalnya list string tag) atau test disesuaikan.

### 8) `BudgetManager.get_burn_rate` return `None` pada data burn-rate tinggi
- **Severity**: Medium
- **Lokasi**: `modules/budget.py` vs `tests/test_modules.py::test_budget_burn_rate`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py::test_budget_burn_rate
  ```
- **Actual**: `assert burn_msg is not None` gagal.
- **Expected**: Ada warning/rekomendasi burn-rate ketika usage sangat cepat.

## Stability / Maintainability

### 9) Warning deprecations dari matplotlib/pyparsing saat test
- **Severity**: Low
- **Lokasi**: dependency stack plotting
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py
  ```
- **Actual**: Banyak `PyparsingDeprecationWarning`.
- **Expected**: Dependency update atau warning filtering agar noise berkurang.

### 10) Ketergantungan env Redis memunculkan fallback warning di banyak test
- **Severity**: Low
- **Lokasi**: `modules/redis_mgr.py`
- **Repro**:
  ```bash
  pytest -q -o addopts='' tests/test_modules.py
  ```
- **Actual**: Warning `REDIS_URL not found. Using In-Memory Cache`.
- **Expected**: Dokumentasi test env atau fixture supaya behavior lebih deterministik.

---

## Aggregate Run
Command yang dipakai untuk menemukan sebagian besar issue di atas:

```bash
pytest -q -o addopts='' tests/test_basic.py tests/test_modules.py tests/test_amounts.py
```

Hasil: **9 failed, 10 passed**.
