# k6 + Chaos Results

Stack: Docker (rootless podman) — Postgres 15, Redis 7 (AOF), Celery, and the
ASGI app. Providers wired to the **real** Brevo + Textlink accounts.
Dev host: 4 vCPU laptop, load average ≈5 (shared), user-space networking.

## Ingest throughput (`tests/k6/ingest_load.js`, 80 VUs peak)

| web tier | concurrent | throughput | p95 latency | errors |
|---|---|---|---|---|
| 1 × Daphne | 10 VUs | 17.7 /s | 713 ms | 0% |
| **4 × Gunicorn+Uvicorn** | 10 VUs | **22.0 /s** | **564 ms** ✓ | **0%** |
| 4 × Gunicorn+Uvicorn | 80 VUs | 34.0 /s | 2.68 s | 0% |
| 8 × Gunicorn+Uvicorn | 80 VUs | 35.9 /s | 2.76 s | 0% |

Per-request service time ≈ 50–110 ms. Adding workers beyond 4 gave no gain →
the **host** (CPU/IO, not the web tier) is the ceiling at ≈35 /s here.

Note: under the default `CONN_MAX_AGE=60`, an 80-VU run produced **6.9% 500s**
(`FATAL: sorry, too many clients already`, 209 idle connections). Setting
`DB_CONN_MAX_AGE=0` (connections are per-request async threads) removed the
errors entirely.

## WebSocket fan-out (`tests/k6/ws_fanout.js`, full profile)
- **500 concurrent WebSocket connections** held (peak VUs = 500)
- `ws_connecting_ms` p95 = **54 ms** (threshold <2000 ✓)
- `ws_errors` = 18 (threshold <50 ✓), 100% `status 101`
- 1,617 sessions, 32,340 messages received

## End-to-end latency (`tests/k6/e2e_latency.js`, 5 VUs)
- `e2e_latency_ms` p95 = **1.06 s**, median 364 ms, min 123 ms
- (fixed twice: the test counted consumer *replay* frames and then backlog
  deliveries as pushes → bogus multi-minute/hours "latencies")

## Chaos drills (reduced counts, quota-safe)
| drill | invariant | result |
|---|---|---|
| duplicate_storm — 500 identical `Idempotency-Key` | exactly 1 Event | **1** ✓ |
| worker_kill — 100 events, worker killed 5 s | 0 stuck PENDING / 0 lost | **0 / 0** ✓ |
| redis_restart — 150 events + Redis restart (AOF) | 0 duplicate SENT per (notification, channel) | **0** ✓ |
| sweeper_race — 2 concurrent `sweep_escalations` | 0 double-escalation per (incident, step_order) | **0** ✓ |

## Provider side-effects (real accounts) — IMPORTANT
The load runs created ~19k PENDING notifications. When `celery_beat` was
restarted, `sweep_escalations` advanced them to step 2 → **233 real SMS were
sent** and 362 failed; 917 more were caught and canceled before sending.
**0 email** (Brevo untouched). Pause/disable `celery_beat` (or mock the SMS
provider) before any high-volume load test.
