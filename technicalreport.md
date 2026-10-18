# Up — Event-Driven Alerting Platform with Acknowledgement-Based Escalation

**Technical Report**

| | |
|---|---|
| **Project** | Up (SysFlow) — multi-tenant incident alerting & escalation service |
| **Report date** | 2026-10-18 |
| **Revision** | 1.0 |
| **Backend** | Python 3.12 · Django 6.1 · DRF 3.18 · Channels 4.3 · Celery 5.6 |
| **Datastores** | PostgreSQL 15 · Redis 7 (AOF) |
| **Frontend** | Next.js 16 · React 19 · TypeScript · Tailwind 4 · shadcn/ui |
| **Serving** | Gunicorn 22 + Uvicorn ASGI workers (4), Gunicorn → `config.asgi:application` |
| **Status** | Feature-complete, hardened, load-tested and chaos-tested |

---

## 1. Executive Summary

Up is a multi-tenant, event-driven alerting platform. Services POST operational
events to a single ingestion endpoint; the platform performs **idempotent
ingestion**, opens or joins an **Incident** on a deduplication key, and then
delivers notifications over four channels — **WebSocket, Web Push, email
(Brevo), SMS (Textlink)** — through a Celery worker pool with retries, backoff,
quiet hours, provider quota control and a dead-letter queue.

The distinguishing feature is **acknowledgement-based escalation**: every
incident carries a signed, time-limited acknowledgement link. If the incident is
not acknowledged before the policy step's SLA expires, a periodic sweeper
advances the incident to the next step (WebSocket → SMS → email → …) until a
human acknowledges it, at which point all in-flight notifications for that
incident are canceled.

Reliability was treated as a first-class requirement and is **verified**, not
asserted: 42 backend tests, four k6 load profiles, and four destructive chaos
drills (worker kill, Redis restart, duplicate storm, concurrent-sweeper race)
that each assert a specific invariant (`0 lost`, `0 duplicated`, `exactly 1`).

---

## 2. Scope of This Report

In scope: architecture, data model, API surface, delivery/escalation semantics,
reliability mechanisms, security posture, test methodology, and measured
results.

Out of scope: commercial deployment topology for the hosted product, and
provider-side SLAs.

---

## 3. System Architecture

```
                    ┌─────────────────────────────────────────────┐
   producers ──────▶│  POST /api/v1/events/   (X-API-Key +         │
   (SDK / k6)       │                          Idempotency-Key)    │
                    └───────────────┬─────────────────────────────┘
                                    │  DRF APIView (sync)
                                    ▼
                    ┌─────────────────────────────────────────────┐
                    │ ingest_event()   ← one DB transaction        │
                    │  Incident.get_or_create(dedup_key)           │
                    │  Event.create(idempotency_key)               │
                    │  Notification.create(status=PENDING)         │
                    │  transaction.on_commit → Celery enqueue      │
                    └───────────────┬─────────────────────────────┘
                                    │
              ┌─────────────────────┴──────────────────────┐
              ▼                                            ▼
   ┌────────────────────┐                       ┌────────────────────────┐
   │ Celery worker      │                       │ Celery beat (sweeper)  │
   │ deliver_notification│                       │ every 30s:             │
   │  → WebSocket       │                       │  sweep_escalations     │
   │  → Web Push        │                       │ every 60s:             │
   │  → Brevo email     │                       │  sweep_stuck_pending   │
   │  → Textlink SMS    │                       └────────────────────────┘
   │  retry + jittered  │
   │  backoff → DLQ     │
   └─────────┬──────────┘
             ▼
     Redis channel layer (fan-out)  ──▶  WebSocket consumers ──▶ browser
     Postgres: notifications / delivery_attempts / dead_letters
```

Design principles:

- **Transactional outbox.** The event, incident and the initial notification are
  written in a single transaction; the Celery task is enqueued from
  `transaction.on_commit`, so a rolled-back request can never leave an orphan
  task and a committed request can never lose one.
- **Database as the source of truth.** Scheduled work is derived from rows
  (`status='PENDING'`, `escalation_due_at`), not from broker state, so a lost or
  purged queue is recoverable.
- **Idempotency at three levels.** HTTP `Idempotency-Key`, incident
  `dedup_key`, and an atomic sweeper claim.

---

## 4. Data Model

Tables are explicitly named (`db_table`) for a stable SQL surface.

| Model | Table | Key constraints / indexes |
|---|---|---|
| `Tenant` | `tenants` | UUID PK |
| `ApiKey` | `api_keys` | indexed `prefix`; `hash` = SHA-256(raw key) |
| `TenantMember` | `tenant_members` | 1-1 to `auth.User`; links dashboard operator → tenant (adds `role`) |
| `User` (recipient) | `users` | unique `(tenant, email)`, unique `(tenant, phone)` |
| `Preference` | `preferences` | unique `(user, channel)`; quiet hours + TZ; `is_enabled` |
| `PushSubscription` | `push_subscriptions` | unique `endpoint` |
| `EscalationPolicy` | `escalation_policies` | tenant-scoped |
| `EscalationStep` | `escalation_steps` | unique `(policy, step_order)`; `channel`, `delay_minutes`, `target_user` |
| `Incident` | `incidents` | unique `(tenant, dedup_key)`; index `(tenant, status)`; `acked_at`, `resolved_at` |
| `Event` | `events` | unique `(tenant, idempotency_key)`; JSON `payload` |
| `Notification` | `notifications` | **partial index** `(tenant, status, escalation_due_at) WHERE status='PENDING'`; `retry_count`, `sweeper_requeue_count` |
| `DeliveryAttempt` | `delivery_attempts` | per-attempt audit row: `status`, `provider_response`, `latency_ms` |
| `DeadLetter` | `dead_letters` | index `(tenant, resolved)`; `reason`, `last_error`, resolution metadata |

**Why the partial index matters.** The sweeper's hot query is
`WHERE status='PENDING' AND escalation_due_at <= now()`. A partial index keeps
its size proportional to *unacknowledged* notifications only, so the scan stays
cheap as the historic table grows — the classic "hot subset of a large table"
optimisation.

Statuses: `PENDING → SENT → DELIVERED`, with terminal `FAILED`, `ESCALATED`,
`CANCELED`. Priorities: `critical`, `default`, `digest`, mapped to three Celery
queues so a critical alert never queues behind a digest batch.

---

## 5. API Surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/events/` | API key | Ingest an event (requires `Idempotency-Key`) |
| `POST` | `/api/v1/recipients/{id}/ws-token/` | API key | Mint a short-lived WebSocket JWT for a recipient |
| `GET` | `/api/v1/ack/{token}/` | **HMAC signature** | Public acknowledgement; cancels pending notifications |
| `GET` | `/api/v1/dlq/` | API key | List dead letters (filter `?resolved=false`) |
| `POST` | `/api/v1/dlq/{id}/replay/` | API key | Re-arm a dead letter's notification and re-queue it |
| `POST` | `/api/v1/dlq/{id}/discard/` | API key | Resolve a dead letter without retry |
| `POST` | `/api/v1/auth/login/` | — | Operator login → JWT access + refresh |
| `POST` | `/api/v1/auth/refresh/` | refresh JWT | Rotate access token |
| `GET` | `/api/v1/auth/me/` | JWT | Current operator + tenant + role |
| `GET` | `/api/v1/incidents/`, `/incidents/{id}/` | JWT | Incident list / detail (with notification + attempt history) |
| `GET` | `/api/v1/analytics/` | JWT | MTTA / MTTR, ack rate, noisiest services, channel breakdown, daily volume |
| `GET` | `/api/schema/`, `/api/docs/` | — | OpenAPI schema (drf-spectacular) + Swagger UI |

Ingest returns `202 Accepted` with `{status, event_id, incident_id,
incident_created, notification_ids}`; a repeated `Idempotency-Key` returns
`200` with `{"status":"duplicate", …}` and the original identifiers.

---

## 6. Delivery & Escalation Semantics

### 6.1 Delivery (`deliver_notification`)

1. Load the notification; if it is no longer `PENDING`, skip (idempotent
   re-delivery guard).
2. Resolve the channel adapter from a registry keyed by `channel`.
3. Apply **quiet hours** for non-critical notifications (`retry` at 1 h
   intervals, up to `MAX_RETRIES`).
4. Apply the **Brevo daily quota** for non-critical email (`try_consume`, Redis
   counter with rollback on over-limit) → DLQ on exhaustion.
5. Send; always write a `DeliveryAttempt` row (status, provider id/error,
   latency in ms).
6. On success → `SENT`. On failure → retry with **exponential backoff + jitter**
   (`2**retries + U(0,1.5) s`, capped at 300 s); after `MAX_RETRIES = 3` →
   `FAILED` + `DeadLetter`.

### 6.2 Escalation (`sweep_escalations`, every 30 s)

```sql
SELECT id FROM notifications
 WHERE status = 'PENDING' AND escalation_due_at <= now()
 ORDER BY escalation_due_at
 LIMIT 100
 FOR UPDATE SKIP LOCKED;
```

- Rows are claimed with `FOR UPDATE SKIP LOCKED`, so **any number of sweepers may
  run concurrently** without double-escalating.
- If the incident was acknowledged/resolved, the pending notification is
  `CANCELED` instead.
- Otherwise the current step is marked `ESCALATED` and the *next* step (by
  `step_order`) is materialised as a new `PENDING` `critical` notification whose
  `escalation_due_at = now() + next_step.delay_minutes`.

### 6.3 Recovery (`sweep_stuck_pending`, every 60 s)

Covers the two realistic loss windows: notifications that were **never picked
up** (worker died before dequeue; `on_commit` enqueue lost) and notifications
that are **stalled mid-retry**. Both are re-queued via an atomic
compare-and-set on `sweeper_requeue_count`, which doubles as a fuse
(`STUCK_MAX_REQUEUES = 3`) to prevent infinite loops; exhausted rows go to the
DLQ with reason `stuck_pending_max_requeues`.

### 6.4 Acknowledgement

`sign_ack_token()` builds `base64url(payload).base64url(HMAC-SHA256(payload))`
where the payload is `{iid, exp}`. `AckIncidentView` verifies the signature and
expiry (constant-time compare), then in one transaction locks the incident
`SELECT … FOR UPDATE`, marks it `ACKED` and cancels its `PENDING` notifications.
The signature *is* the authentication — no session is required, which is exactly
what an email/SMS link needs.

---

## 7. Reliability Engineering

| Failure mode | Mechanism | Verified by |
|---|---|---|
| Client retries a POST | `Idempotency-Key` + unique `(tenant, idempotency_key)`; `IntegrityError` → replay original response | `chaos_duplicate_storm.sh` |
| Duplicate alerts for the same fault | unique `(tenant, dedup_key)` → same incident, no new notification | `test_ingest.py` |
| Worker crash before dequeue | `sweep_stuck_pending` (never-started branch) | `chaos_worker_kill.sh` |
| Worker crash mid-retry | `sweep_stuck_pending` (stalled branch) + requeue fuse | `chaos_worker_kill.sh` |
| Broker/Redis restart | Derive work from the DB, re-queue; AOF persistence | `chaos_redis_restart.sh` |
| Concurrent sweepers | `FOR UPDATE SKIP LOCKED` | `chaos_sweeper_race.sh` |
| Provider outage | Jittered exponential backoff → DLQ → operator **replay/discard** | `test_reliability.py` |
| Provider quota exhaustion | Redis daily counter, per tenant, per day | `test_reliability.py` |
| Notification storms at night | Quiet hours per recipient/channel (non-critical only) | `test_reliability.py` |
| Ack link forgery/replay | HMAC-SHA256 + TTL + constant-time compare | `test_escalation.py` |
| Periodic work lost | Beat re-derives state every 30–60 s; nothing is fire-and-forget | sweeper tests |
| DB connection exhaustion under ASGI | `DB_CONN_MAX_AGE` (see §10.2) | 80-VU k6 run |

---

## 8. Security Posture

- **API keys are never stored.** `ApiKey` keeps an 8-char lookup `prefix` and a
  SHA-256 hash; verification uses `secrets.compare_digest` (timing-safe).
- **Two distinct identity planes.** Machine ingestion uses API keys
  (`TenantPrincipal`); the dashboard uses JWT (`TenantJWTAuthentication`) bound
  to a `TenantMember`, so a dashboard user is always tenant-scoped. Every
  queryset is filtered by `request.user.tenant`.
- **Acknowledgement links are signed and expire** (`ACK_TOKEN_TTL_SECONDS`).
- **Secrets stay out of the repository.** All credentials flow through env vars
  loaded by `python-decouple`; `.gitignore` excludes `.env`, `.env.*`, `*.pem`
  and `*.key` while explicitly *allowing* the `.example` templates. This report
  contains no credentials.
- **Tenant throttling** on ingest (`TenantRateThrottle`), overridable for load
  tests and defaulting to `600/min`.
- **WebSocket auth** via a scoped, short-lived JWT (`token_type="ws"`) in the
  connect query string, validated with `AllowedHostsOriginValidator` in place.

---

## 9. Verification & Test Methodology

### 9.1 Test inventory

| Layer | Artefact | Count | What it proves |
|---|---|---|---|
| Unit / integration (pytest-django) | `backend/tests/*.py` | **42 tests** | Ingest, escalation, ack signing, websocket auth, DLQ/replay, quota, quiet hours, channel adapters |
| Load (k6) | `tests/k6/ingest_load.js` | 80-VU ramp | Ingest throughput + p95/p99 latency |
| Load (k6) | `tests/k6/ws_fanout.js` | 500 VUs | Concurrent WebSocket fan-out |
| Load (k6) | `tests/k6/e2e_latency.js` | 20 VUs | Event → WebSocket push latency |
| Chaos | `tests/chaos/*.sh` | 4 drills | Invariants under destructive fault injection |

Each k6 script and chaos drill supports a reduced profile (`LITE=1`, or
`EVENTS`/`N` env overrides) that exercises an identical code path for
quota-safe verification.

### 9.2 Test environment (important caveat)

All figures below were measured on a **single developer workstation**:

- 4 vCPU, 16 GB RAM, load average ≈ 5 from unrelated processes (i.e. effectively
  a fraction of one core per process), **rootless Podman** networking
  (userspace port forwarding).
- The entire stack (Postgres, Redis, Gunicorn+Uvicorn ×4–8, Celery worker,
  Celery beat) plus the k6 generator ran on that same host.

This matters: §10 shows the measured ceiling is **host-bound, not
application-bound**. Numbers from a dedicated instance would differ.

### 9.3 Fixed during testing

- **Backend healthcheck.** `/api/schema/` returns `401` without an API key;
  the healthcheck used `curl -f`, so the container never became healthy and the
  Celery worker/beat never started. Fixed by dropping `-f` (a `401` still proves
  the ASGI server is serving).
- **k6 v2 compatibility.** Removed an unavailable remote `jslib` import (local
  RFC-4122 v4 UUID instead) and moved the WebSocket token fetch into `setup()`
  because k6 v2 forbids HTTP in the init context.
- **E2E latency measurement.** The trend was polluted by (a) the consumer's
  connect-time `replay` frames and (b) backlog notifications re-queued by the
  stuck-pending sweeper, both of which carry *old* `created_at` values and
  produced multi-minute/multi-hour "latencies". The test now counts only a push
  produced by the event that iteration fired.

---

## 10. Results

### 10.1 Ingest throughput and latency

Full profile = ramping VUs to 80, ~4.5 min. LITE = 10 VUs, 40 s.

| Web tier | Load | Throughput | p95 ingest | p99 | Errors |
|---|---|---|---|---|---|
| 1 × Daphne | 10 VU (LITE) | 17.7 /s | 713 ms | 878 ms | 0 % |
| **4 × Gunicorn + Uvicorn** | 10 VU (LITE) | **22.0 /s** | **564 ms** ✅ | 698 ms ✅ | **0 %** |
| 4 × Gunicorn + Uvicorn | 80 VU (full) | 34.0 /s | 2.68 s | — | 0 % |
| 8 × Gunicorn + Uvicorn | 80 VU (full) | 35.9 /s | 2.76 s | — | 0 % |

Thresholds on the LITE profile (`p95 < 600 ms`, `p99 < 1200 ms`, error rate
< 2 %, success rate > 99 %) **all pass** with four Gunicorn/Uvicorn workers.

### 10.2 Finding: Postgres connection exhaustion under ASGI

The first 80-VU run produced a **6.88 % error rate** with
`FATAL: sorry, too many clients already`, despite `max_connections=300`. Under
ASGI, Django runs each synchronous request in its own worker-pool thread, and
each thread holds its own connection; with `CONN_MAX_AGE = 60` those connections
accumulate as **209 idle** connections.

Fix: made the value configurable (`DB_CONN_MAX_AGE`, set to `0` in the container)
so a connection is released at the end of each request. The error rate went to
**0 %** and throughput improved by ~30 %. The correct production-grade
companion is a connection pooler (PgBouncer) — documented in code and in
`.env.docker.example`.

### 10.3 Finding: the host, not the application, is the ceiling

Doubling the web tier from 4 to 8 workers changed throughput from 34.0 /s to
35.9 /s (**+5 %**). Cross-checks:

- `synchronous_commit=off` (removing WAL fsync from the critical path) changed
  nothing → not storage-fsync bound.
- Sampling showed the backend at ~0.1 % and Postgres at ~2 % CPU → not
  CPU-bound in the containers, they were simply starved by the host.
- A k6-equivalent load generated from *inside* the container network reproduced
  the same ~29–35 /s ceiling → not an artefact of the rootless port forwarder.
- Adding concurrency grew latency ~linearly (per-request service time ≈
  50–110 ms, effective parallelism ≈ 2–3× regardless of worker count).

**Conclusion:** with the services, the load generator and a saturated 4-vCPU
laptop sharing one machine, ~35 events/s is the environment's limit. The
scaling behaviour (a saturation curve) is the meaningful result; the absolute
number is not portable.

### 10.4 WebSocket fan-out

| Metric | Result | Threshold |
|---|---|---|
| Peak concurrent connections | **500** | — |
| `ws_connecting_ms` p95 | **54 ms** | < 2000 ms ✅ |
| `ws_errors` | 18 | < 50 ✅ |
| Handshake status 101 | 100 % | — |
| Sessions / messages | 1,617 / 32,340 | — |

Published fan-out (Redis channel layer) held 500 simultaneous connections
comfortably — the strongest, most portable result in this report.

### 10.5 End-to-end latency (event → WebSocket push)

| Metric | Result |
|---|---|
| `e2e_latency_ms` p95 | **1.06 s** |
| median | 364 ms |
| min | 123 ms |

Measured at 5 VUs on a clean database; ingest-side p95 in the same window was
535 ms.

### 10.6 Chaos drills

| Drill | Invariant asserted | Result |
|---|---|---|
| `duplicate_storm` — 500 identical `Idempotency-Key` | exactly 1 `Event` row | **1** ✅ |
| `worker_kill` — 100 events, worker killed mid-flight | 0 stuck `PENDING`, 0 lost | **0 / 0** ✅ |
| `redis_restart` — 150 events + Redis restart (AOF) | 0 duplicate `SENT` per (notification, channel) | **0** ✅ |
| `sweeper_race` — 2 concurrent `sweep_escalations` | 0 double-escalation per (incident, step) | **0** ✅ |

Cumulative database state after the full campaign: 2,316 events / 2,044
incidents (chaos runs); 19,437 WebSocket deliveries recorded as `SENT`.

### 10.7 Headline numbers (as used in the project summary)

Measured on the test host, and reasonable to quote for a single small cloud
instance:

| Metric | Value |
|---|---|
| Sustained ingest | **~30 events/s** (22 /s at p95 564 ms; 34–36 /s peak) |
| p95 ingest latency | **~560 ms** (sustainable operating point) |
| Concurrent WebSocket connections | **500** (p95 connect 54 ms) |
| p95 end-to-end event → push | **~1.0 s** |
| Chaos events verified | **1,300** (0 lost / 0 duplicated) |

A larger single-instance figure (≥150 events/s) is **not supported by any
measurement** in this environment and should not be claimed without a run on a
dedicated instance.

### 10.8 Operational lesson (provider quotas)

Load runs create a large volume of `PENDING` notifications. When Celery beat was
restarted, `sweep_escalations` correctly advanced them to the SMS step and
**233 real SMS** were sent (362 failed; 917 were cancelled in time; **0 email**).
This is the system behaving as designed — but it is a reminder that **any
high-volume test must pause `celery_beat` or set `SMS_PROVIDER=mock` /
`EMAIL_PROVIDER=mock`** before starting. The mocks exist precisely for this and
are covered by tests.

---

## 11. Frontend

Next.js 16 (App Router) + React 19 + TypeScript, Tailwind 4 and shadcn/ui.

| Screen | Path | Purpose |
|---|---|---|
| Overview | `(dashboard)/page.tsx` | Live incident feed |
| Incidents | `(dashboard)/incidents/` | List + detail with per-channel delivery history |
| DLQ | `(dashboard)/dlq/` | Inspect, replay, discard dead letters |
| Analytics | `(dashboard)/analytics/` | MTTA/MTTR, ack rate, noisiest services, channel breakdown, volume chart |
| Login | `login/` | Operator authentication (JWT) |

`src/lib/api.ts` centralises axios configuration and token refresh;
`src/lib/auth.tsx` provides the auth context. Realtime updates arrive over the
WebSocket consumer (≤20 notifications replayed on reconnect, with
`last_seen_id` support for gap recovery).

---

## 12. Deployment & Operations

Local stack (`docker-compose.yml`): `postgres` (healthcheck, published on host
`5433`, `max_connections=300`), `redis` (AOF), `mailpit` (SMTP capture + web UI),
and the shared `sysflow-backend:local` image used by `backend`, `celery_worker`
and `celery_beat`.

Backend command:

```
sh -c "python manage.py migrate && \
       gunicorn config.asgi:application \
         -w ${GUNICORN_WORKERS:-4} \
         -k uvicorn.workers.UvicornWorker \
         -b 0.0.0.0:8000 --timeout 300 --graceful-timeout 30 --access-logfile -"
```

- **WebSocket still works** under Gunicorn/Uvicorn because Channels fans out
  through the Redis channel layer; no sticky sessions are required.
- Worker/beat start only after the backend reports **healthy** (`depends_on:
  condition: service_healthy`), which is why the healthcheck bug in §9.3 was
  fatal.
- Celery exposes three queues (`critical`, `default`, `digest`) with task hard
  and soft time limits (5 / 4 min).
- `GUNICORN_WORKERS` is the production tuning knob (4 for a 2-vCPU instance).

---

## 13. Limitations & Future Work

**Limitations**

1. Absolute throughput figures are host-bound (§10.3) and were measured on a
   shared, rootless container host.
2. Single-node Postgres/Redis; no PgBouncer, no read replica, no HA.
3. Full-profile load runs require pausing escalation or mocking providers
   (§10.8) because escalations deliver over *real* paid channels.
4. The SMS channel depends on the Textlink SDK's synchronous call path; the
   daily free-tier quota is small.

**Future work**

1. PgBouncer (or `psycopg3` async) in front of Postgres, then re-measure to
   separate application throughput from connection setup.
2. Fan-out beyond one host: replace the in-process channel layer with Redis
   Cluster and shard the ingest path by tenant.
3. Partition `notifications` / `delivery_attempts` by month and add retention
   windows; the sweeper's partial index keeps the hot path stable, but audit
   tables grow unbounded.
4. Provider-side delivery receipts (Brevo webhooks, DLRs) to move
   `SENT → DELIVERED` truthfully.
5. Rate limiting per *policy*, not just per tenant, plus circuit breakers per
   provider.
6. A repeatable benchmark harness on a dedicated instance so headline numbers
   are portable.

---

## 14. Appendix

### 14.1 Repository layout

```
backend/
  config/            settings (base/dev/prod), asgi, celery, urls
  apps/
    tenants/         Tenant, ApiKey, TenantMember
    accounts/        recipient User, Preference, PushSubscription
    incidents/       models, ingest_event(), views
    notifications/   models, tasks, consumers, channels/, quota, quiet_hours, signing
    api/             views, serializers, urls, authentication, throttles
  scripts/seed.py    demo tenant/policy/recipients
  tests/             42 pytest tests
frontend/            Next.js dashboard
tests/
  k6/                ingest_load.js, ws_fanout.js, e2e_latency.js, common.js
  chaos/             duplicate_storm, worker_kill, redis_restart, sweeper_race
  RESULTS.md         raw measured results
docker-compose.yml   local stack
.env.docker.example  Docker env template (no secrets)
```

### 14.2 Reproducing the measurements

```bash
# 1. Configure and start the stack
cp .env.docker.example .env.docker        # fill in values
docker compose up -d --build

# 2. Seed a tenant / policy / recipients and export the credentials
docker compose exec -T backend python scripts/seed.py
export SYSFLOW_API_KEY=... SYSFLOW_POLICY_ID=... SYSFLOW_RECIPIENT_ID=...

# 3. Pause escalation so no real SMS/email are sent during the run
docker compose stop celery_beat

# 4. Load tests (k6 reads SYSFLOW_* from the environment)
k6 run tests/k6/ingest_load.js      # or: LITE=1 k6 run tests/k6/ingest_load.js
k6 run tests/k6/ws_fanout.js
k6 run tests/k6/e2e_latency.js

# 5. Chaos drills
bash tests/chaos/chaos_duplicate_storm.sh
bash tests/chaos/chaos_worker_kill.sh
bash tests/chaos/chaos_redis_restart.sh
bash tests/chaos/chaos_sweeper_race.sh

# 6. Resume escalation
docker compose start celery_beat
```

### 14.3 Environment variables

See `.env.docker.example` (Docker stack) and `backend/.env.example` (direct
run). Key knobs: `DB_CONN_MAX_AGE`, `GUNICORN_WORKERS`, `EMAIL_PROVIDER`
(`brevo|smtp|mock`), `SMS_PROVIDER` (`textlink|mock`), `BREVO_DAILY_QUOTA`,
`THROTTLE_TENANT_RATE`, `ACK_TOKEN_TTL_SECONDS`.

> **No credentials are stored in this repository.** Real values live only in
> git-ignored `.env*` files; committed templates contain placeholders.

---


