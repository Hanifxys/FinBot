# A/B Testing Plan - UX Optimization

## Objective
Memvalidasi impact fitur UX terhadap conversion, kecepatan input, engagement, dan retention.

## Experiment Matrix

### A/B-1: Low-confidence confirmation copy
- Control: preview standar tanpa kalimat konfirmasi ringan.
- Variant: "Aku baca ini ..., bener?" + tombol `Ya, bener` / `Edit`.
- Primary metric: `preview -> confirm conversion`.
- Guardrail: cancel rate tidak naik > 5 poin.

### A/B-2: Recurring suggestion timing
- Control: tampil setelah setiap kandidat recurring terdeteksi.
- Variant: tampil hanya saat confidence tinggi (hits >= sensitivity + 1).
- Primary metric: acceptance rate recurring suggestion.
- Guardrail: tidak menurunkan total input completion.

### A/B-3: Budget autopilot CTA copy
- Control: CTA generik approve/reject.
- Variant: CTA dengan impact summary lebih eksplisit.
- Primary metric: autopilot approval rate.
- Guardrail: reject rate + user complaint tag.

### A/B-4: Voice draft confirmation UI
- Control: flow voice lama.
- Variant: one-tap confirmation + quick edit chips.
- Primary metric: median entry time reduction.
- Guardrail: edit-after-confirm rate.

### A/B-5: Weekly challenge reward framing
- Control: reward text standar.
- Variant: reward text + social share CTA.
- Primary metric: weekly engagement events per user.
- Guardrail: churn D7 tidak naik.

## Assignment Strategy
- Sticky assignment by hashed user id.
- 50:50 split default.
- Exclude users dengan telemetry opt-out.

## Measurement Windows
- Onboarding and funnel: daily aggregation.
- Retention: D1, D7, D30 cohorts.
- Challenge/reward: weekly cohorts.

## Instrumentation Requirements
- Track clicks: Yes/Edit/Cancel/Approve/Reject/Snooze.
- Track onboarding step completion.
- Track voice/manual latency per entry.
- Track experiment variant in event props (`exp`, `variant`).

## Analysis Method
- Conversion: z-test proporsi.
- Latency: Mann-Whitney U / percentile comparison.
- Retention: cohort delta and confidence interval.

## Rollout Criteria
- Promote variant bila:
  - primary metric signifikan positif
  - semua guardrail aman
  - tidak ada alert kritikal performa

## Post-rollout Monitoring
- 2 minggu observasi alert UX.
- Regression watchlist: cancel rate, error rate, response time.
