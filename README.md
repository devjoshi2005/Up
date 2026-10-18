# Up (SysFlow)

Event-driven alerting with acknowledgement-based escalation.

Producers emit events over an API key; incidents escalate through a policy
(WebSocket → SMS → email); responders acknowledge via an HMAC magic link; the
dashboard shows traces, analytics and the dead-letter queue.

## Architecture (RBAC)

| Role | Prod auth | Can do |
| --- | --- | --- |
| **Producer** (service) | `X-API-Key` | `POST /api/v1/events/` only — no dashboard |
| **Responder** (on-call) | HMAC magic link | `GET /api/v1/ack/<token>/` — no login needed |
| **Operator / Admin** (dashboard) | JWT (`TenantMember`) | traces, analytics, escalate, resolve, DLQ (admin) |

Roles live on `TenantMember.role`: `admin`, `operator`, `viewer`, plus the
demo-only `producer` / `responder` personas that let you drive each console
from a browser (production producers/responders never log in).

## Demo logins

Password for all seed accounts is `demo1234`:

| Email | Role | Console |
| --- | --- | --- |
| `producer@up.test` | producer | `/produce` — emit alerts |
| `responder@up.test` | responder | `/inbox` — acknowledge / escalate |
| `demo@up.test` | admin | `/` — full dashboard + resolve + DLQ |
| `op@up.test` | operator | `/` — incidents, escalate, resolve |
| `view@up.test` | viewer | `/` — read-only dashboard |

## Who can do what

| Endpoint | Producer | Responder | Viewer | Operator | Admin |
| --- | :---: | :---: | :---: | :---: | :---: |
| `POST /events/` (`X-API-Key`) | ✅ | – | – | – | – |
| `GET /ack/<token>/` (HMAC link) | anyone holding the link | | | | |
| `GET /demo/produce/`, `POST /demo/produce/` | ✅ | ❌ | ❌ | ✅ | ✅ |
| `GET /demo/inbox/` | ❌ | ✅ | ❌ | ✅ | ✅ |
| `POST /incidents/{id}/escalate/` | ❌ | ✅ | ❌ | ✅ | ✅ |
| `POST /incidents/{id}/resolve/` | ❌ | ❌ | ❌ | ✅ | ✅ |
| `GET /incidents/`, `/analytics/`, `/dlq/` | ❌ | ❌ | ✅ | ✅ | ✅ |
| `POST /dlq/{id}/replay/`, `/discard/` | ❌ | ❌ | ❌ | ❌ | ✅ |

Role tiers live in `backend/apps/api/permissions.py`. Producers/responders log
in here only for the demo console — in production they use an API key / magic
link and never reach a dashboard.

## Lifecycle of an incident

1. **Producer** emits `POST /api/v1/events/` → event is deduped into an
   `Incident` (status `OPEN`) → **step 1** of the policy is created `PENDING`
   and delivered (WebSocket/SMS/email) with an HMAC acknowledgement link.
2. **Nobody acks** → Celery beat's `sweep_escalations` runs every 30s: a
   `PENDING` notification past its `escalation_due_at` becomes `ESCALATED` and
   the **next** policy step is created `PENDING`. Repeat until the final step.
3. **Responder acknowledges** → clicks the magic link (`GET /api/v1/ack/<token>/`)
   or the inbox button → incident becomes `ACKED`, `acked_at` is stamped
   (MTTA), and **every pending escalation is canceled** — the page stops.
4. **Responder can't handle it** → *Escalate* → the next step fires
   **immediately** (skipping its `delay_minutes`), so the on-call chain moves
   on. The trace shows the skipped step as `ESCALATED`.
5. **Operator/Admin resolves** → incident becomes `RESOLVED`, `resolved_at`
   is stamped (MTTR), remaining pending notifications are canceled. Responders
   get `403` here — closing the incident is an operator/admin action.

## Run locally

Backend (three terminals, from `backend/`):

```bash
.venv/bin/daphne -b 0.0.0.0 -p 8000 config.asgi:application
.venv/bin/celery -A config worker -Q critical,default,digest -l info
.venv/bin/celery -A config beat -l info
```

Frontend (from `frontend/`):

```bash
npm run dev    # http://localhost:3000
```

One-off setup:

```bash
cd backend && .venv/bin/python manage.py migrate
cd backend && .venv/bin/python manage.py shell -c "exec(open('scripts/seed.py').read())"
```
