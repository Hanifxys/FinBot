# UX Optimization System

## Scope
Dokumen ini menjelaskan arsitektur dan decision tree untuk:
- UX Funnel Analytics
- Smart Recurring Detection
- Budget Autopilot
- Voice-First Fast Entry
- Weekly Challenge + Rewards

## 1) UX Funnel Analytics

### Event taxonomy
Event utama:
- `preview_shown`
- `confirm`
- `edit`
- `cancel`
- `history_filter_used`
- `insight_action_clicked`
- `reminder_snooze`

Event tambahan pendukung:
- `voice_entry_processed`
- `manual_entry_processed`
- `onboarding_step_done`
- recurring/autopilot suggestion events

### Privacy model (GDPR/CCPA-aligned)
- User identifier di-hash (`sha256`, truncated) sebelum disimpan telemetry.
- Consent model: default ON, user bisa opt-out via `/telemetry off`.
- Tidak menyimpan konten sensitif mentah sebagai primary key telemetry.
- Event queue offline tersimpan lokal, lalu di-flush saat Redis tersedia.

### Funnel metrics
- `preview -> confirm conversion`.
- `dropoff %` pada preview.
- `edit rate` dan `cancel rate`.

### Alerting rules
- Warning bila conversion `< 50%`.
- Warning bila cancel rate `> 25%`.

### Reporting
- Endpoint monitor:
  - `/ops/ux-funnel`
  - `/ops/ux-report`
  - `/ops/ux-alerts`
- Daily job (`daily_digest`) melakukan:
  - flush offline queue
  - compute actionable report
  - emit warning log untuk alert

## 2) Smart Recurring Detection

### Detection algorithm
Input: transaksi terbaru yang dikonfirmasi.
1. Bentuk signature: `category|description|rounded_amount`.
2. Ambil histori 7 hari terakhir pada kategori sama.
3. Hitung kemunculan signature.
4. Jika `hits >= sensitivity` (default 3), candidate recurring terbentuk.
5. Estimasi interval dari jarak antar transaksi historis.
6. Simpan template recurring + next due timestamp.

### Reminder logic
- Reminder recurring dikirim jika due dalam 24 jam ke depan.
- Dedupe dengan marker `last_reminded` selama 24 jam.

### Sensitivity setting
- `/recurring 2..6`
- Nilai kecil = lebih agresif menyarankan recurring.

### Success metric
- `recurring_suggestion_accepted / recurring_suggestion_shown`.

## 3) Budget Autopilot

### Decision tree
1. Deteksi kategori overspending (`usage/limit >= 0.9`).
2. Cari kategori underutilized (`usage/limit < 0.4`).
3. Buat proposal transfer budget (from underused -> overspent).
4. Tampilkan proposal + impact UI.
5. User `Approve`/`Reject`.
6. Simpan keputusan untuk learning sederhana (approval stats).

### Impact preview
- ratio target setelah transfer
- buffer source setelah transfer

### Success metric
- `autopilot_approved / autopilot_suggested`.

## 4) Voice-First Fast Entry

### Flow
1. User kirim voice.
2. STT transcribe (`premium_ai.transcribe_voice`).
3. NLP parsing amount/category/description.
4. Draft transaksi ditampilkan 1-tap confirm.
5. UX telemetry mencatat latency voice entry.

### Error handling
- Jika transkripsi gagal: fallback message + retry.
- Jika confidence rendah: UI konfirmasi ringan + tombol edit.

### KPI
- Bandingkan median latency `voice_entry_processed` vs `manual_entry_processed`.
- Target: voice median >= 50% lebih cepat dari manual.

## 5) Weekly Challenge + Rewards

### Challenge model
- Weekly assignment otomatis.
- Progress naik saat user confirm transaksi.
- Completion memicu XP reward.

### Marketplace
- XP bisa diredeem untuk item premium feature.

### Social share
- Action `challenge:share` menghasilkan template teks share.

### Success metrics
- Challenge completion rate.
- Reward redemption rate.
- Retention D7/D30 sebelum vs sesudah rollout.

## UX Copy Guidelines
- CTA utama konsisten: `Simpan`, `Edit`, `Batal`, `Ya, bener` (low confidence).
- Insight wajib punya 1 tindakan konkret (`Set limit ...`).
- Reminder tone: `Santai`, `Tegas`, `Formal`.

## Offline + Sync Strategy
- Telemetry: queue file (`temp_reports/ux_event_queue.jsonl`) saat Redis down.
- Sync: flush otomatis di daily digest.
- Feature state tetap di Redis fallback path sesuai modul (graceful degradation).

## Monitoring
- UX alert via `/ops/ux-alerts`.
- Log hook harian untuk report conversion/dropoff.
- Ops dapat mengintegrasikan log alert ke Slack/PagerDuty via pipeline existing.
