# Multi-tenant Notification Service

A multi-tenant notification service supporting email/SMS/push/in-app
delivery, tenant-defined templates, scheduled and immediate sends,
per-tenant rate limiting and fairness under load, automatic retries with
backoff, and a full delivery audit trail.

Built as a 48-hour take-home assessment. The PRD was intentionally
open-ended — this README documents the scoping decisions made along the
way and the reasoning behind them.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI + Uvicorn (single worker) | Async-native, minimal ceremony for a 48h scope |
| ORM | SQLAlchemy 2.0 (async) | First-class `async`/`await` support, no sync calls anywhere on the request or dispatch path |
| Database | SQLite (`aiosqlite` driver) | Zero external dependencies, fits the "no distributed systems" constraint directly — see [Concurrency Model](#concurrency-model-and-sqlite) below for the tradeoff this implies |
| Migrations | Alembic | Standard, async-template-compatible |
| Auth | JWT from `POST /auth/login` | Simplest defensible RBAC without OAuth/SSO (explicitly out of scope) |
| Testing | pytest + pytest-asyncio + httpx | Async-native test client, no separate test DB process needed |

## Domain Model

```
Tenant
 ├── User                  (role: PLATFORM_ADMIN | TENANT_ADMIN)
 ├── ChannelConfig          (per channel: enabled + provider config; rate limits live on Tenant, not here)
 ├── Template               (per channel)
 └── Recipient
      └── RecipientChannelAddress   (one row per channel they're reachable on)

NotificationRequest         (template + variables + recipient_ids + optional scheduled_at)
 └── NotificationChannel    (one per requested channel)
      └── DeliveryAttempt   (one per recipient on that channel — the retry/claim unit)

AuditLog                    (polymorphic: logs NotificationRequest/NotificationChannel
                              creation and every DeliveryAttempt state transition —
                              not nested under any one entity)
```

**Why a three-level fan-out instead of a flat list of deliveries?** A
single `POST /notifications` call can mean "email *and* SMS this group" —
`NotificationChannel` is what lets each requested channel track its own
aggregate status independently, while `DeliveryAttempt` is what lets each
*recipient* within a channel retry independently without one slow/failing
recipient blocking the others.

**Delivery state machine:**

```
CREATED → SCHEDULED → PENDING → SENDING → SENT
                                    ↓
                                 FAILED → RETRYING → DEAD_LETTERED
```

Every `DeliveryAttempt` transition writes an `AuditLog` row (from-state,
to-state, actor, timestamp) — this is the audit trail required by the PRD.
(`NotificationChannel`'s own aggregate status, recomputed after each
attempt settles, is *not* separately audit-logged — it's a derived
rollup, not an independent transition.)

## Concurrency Model and SQLite

The dispatch engine is a three-stage `asyncio` pipeline, no external queue
or broker:

1. **Poll loop** — every `POLL_INTERVAL_SECONDS`, finds `DeliveryAttempt`
   rows that are due (`status IN ('PENDING','RETRYING') AND next_attempt_at
   <= now`) and routes them into per-tenant queues.
2. **Dispatcher** — round-robins across tenant queues. For each tenant's
   turn, it checks an in-memory token bucket for `(tenant_id, channel)`; if
   a token's available, the item moves to a shared work queue, otherwise
   it's skipped *for that round only* and the rotation continues. This is
   where fairness and rate limiting meet — a flooding tenant gets
   throttled without ever blocking other tenants' turns.
3. **Worker pool** — a bounded set of coroutines pull from the work queue,
   perform an atomic claim
   (`UPDATE ... WHERE status IN ('PENDING','RETRYING') AND id=?`,
   proceeding only if exactly one row was affected — `RETRYING` has to be
   claimable too, or a retried attempt could never be re-sent), call a
   mocked provider, and apply the result with exponential backoff + jitter
   on failure, eventually dead-lettering after `MAX_ATTEMPTS`.

**Explicit assumption — SQLite write serialization.** SQLite allows
concurrent readers but only one writer at a time, even with WAL mode
enabled (WAL removes reader/writer blocking, not writer/writer
serialization). That means "concurrent dispatch" in this system refers to
concurrent `asyncio` tasks *contending* for claims, not concurrent
*throughput* at the storage layer — writes still serialize underneath. The
correctness guarantee (no duplicate delivery) holds regardless, since the
atomic claim is what enforces it, not parallelism. This is a deliberate
tradeoff for a single-process, no-distributed-systems scope, not an
oversight — and it's why the app runs as a single Uvicorn worker against
one SQLite file rather than multiple processes, which would only add lock
contention without adding real throughput.

**Scheduling reuses the retry mechanism.** `NotificationRequest.scheduled_at`
is copied onto every resulting `DeliveryAttempt.next_attempt_at` at
creation time. The poll loop's existing `next_attempt_at <= now` filter
then handles scheduled sends "for free" — no separate scheduler component
was needed.

## Recipients and Partial Channel Failure

Recipients are modeled as a first-class, tenant-scoped entity
(`Recipient` + one `RecipientChannelAddress` row per channel they're
reachable on) rather than raw address strings in the request body. A
`NotificationRequest` carries a list of recipient IDs, reused across every
requested channel — which raises an edge case worth calling out:

- **If a recipient has no registered address for a requested channel**,
  that `(channel, recipient)` pair is skipped — no `DeliveryAttempt` is
  created for it — rather than failing the entire request. The skip is
  recorded on `NotificationChannel.skipped_recipients`.
- **A `NotificationChannel` row is always created for every channel
  requested**, even if every recipient on it gets skipped (its status
  resolves to `FAILED` in that case). It's never silently omitted from
  reports — a tenant admin who requests SMS for a group with no phone
  numbers on file should see that explicitly, not see SMS quietly absent
  from the results.

## API Overview

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/register/platform-admin` (one-time bootstrap, 403s once any platform admin exists) |
| Platform admin | `POST/GET /tenants`, `GET/PATCH /tenants/{id}`, `POST/GET /tenants/{id}/users` (rate limits are updated via the same `PATCH /tenants/{id}` as every other tenant field — there is no separate `/limits` endpoint) |
| Tenant admin | `POST/GET /templates`, `GET/PATCH/DELETE /templates/{id}`; `POST/GET /recipients`, `GET/PATCH/DELETE /recipients/{id}`, `PUT/DELETE /recipients/{id}/addresses/{channel}`; `GET /channel-configs`, `GET/PUT/DELETE /channel-configs/{channel}` (`PUT` upserts — channel is a fixed enum, so there's no separate create) |
| Sending | `POST /notifications` |

**Not built**: a `GET` endpoint to look up a `NotificationRequest` (or its
deliveries) after creation, and a dedicated delivery-reports endpoint —
the PRD's "view delivery reports" tenant-admin capability is satisfied
today only by the data returned synchronously from `POST /notifications`,
plus direct DB inspection. Read endpoints over `NotificationRequest`/
`DeliveryAttempt` would be the natural next addition.

RBAC is enforced via FastAPI dependencies (`require_platform_admin`,
`require_tenant_admin`) wrapping JWT decoding. Every tenant-admin route
additionally goes through `get_current_tenant_id`, which derives the
tenant scope from the caller's own token and rejects platform admins
outright (they have no `tenant_id` of their own) — a tenant admin's scope
is never taken from a path/body parameter, so one tenant can't act on
another's data by passing a different `tenant_id`.

## Setup & Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

### Configuration (env vars, all optional with sane defaults)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./notifications.db` | DB connection |
| `POLL_INTERVAL_SECONDS` | `3` | Dispatch poll frequency |
| `WORKER_POOL_SIZE` | `10` | Bounded concurrent dispatch workers |
| `MAX_ATTEMPTS` | `5` | Attempts before `DEAD_LETTERED` |
| `BASE_BACKOFF_SECONDS` | `2` | Backoff base for exponential retry delay |
| `MAX_BACKOFF_SECONDS` | `60` | Backoff cap |
| `RETRY_JITTER_SECONDS` | `1` | Max random jitter added to each backoff (`uniform(0, jitter)`) |
| `SIMULATE_FAILURE_RATE` | `0.1` | Mocked provider's simulated failure rate, for exercising retry logic |

## Testing

```bash
pytest -q
```

22 tests, covering:
- **Unit**: rate-limiter token bucket (burst, exhaustion, refill, cap),
  backoff calculator (growth, cap, jitter bounds), template variable
  substitution.
- **Integration**: full dispatch lifecycle (happy path, retry-then-succeed
  with backoff timing assertions, exhaustion to `DEAD_LETTERED`, lost-claim
  no-op), a 20-task concurrent claim race asserting exactly one winner, a
  fairness test asserting a throttled tenant never blocks another tenant's
  item in the same dispatch round, and a full HTTP-to-DB notification flow
  including the skipped-recipient case.

Each run uses a fresh SQLite database — no external services or
Testcontainers needed.

## Known Limitations / Explicitly Out of Scope

Per the assessment instructions, the following were not built: UI/frontend,
Docker/CI-CD, OAuth/SSO/MFA, distributed systems or microservices,
production-grade observability/monitoring/alerting.

Additionally, not built within the 48-hour window:
- A webhook callback endpoint for simulating async provider delivery
  confirmation (would model real-world providers that confirm delivery
  out-of-band rather than synchronously).

## AI-Assisted Development

This project was built with Claude (via Claude Code) as a development
collaborator. `CLAUDE.md` in this repo is the running decision log used
throughout development — every architectural choice, scoping decision, and
the one concrete bug it helped catch (a stale ORM object after a raw-SQL
claim update bypassed SQLAlchemy's session identity map) are documented
there with reasoning, not just outcomes.

No custom Agent Skills were used; project context was managed entirely
through CLAUDE.md.

Raw development session transcripts are included under
`docs/transcripts/` for reference.