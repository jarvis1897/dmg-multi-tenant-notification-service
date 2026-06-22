# Multi-tenant Notification Service — Project Memory

## Project Overview
FastAPI service supporting multi-tenant notification dispatch across
email/SMS/push/in-app channels, with templates, scheduling, per-tenant rate
limiting, retries with backoff, and delivery tracking. Built for a 48-hour
take-home assessment. No distributed systems, no external queues. Single
process, asyncio-based concurrency, persistence via SQLite.

## Stack & Conventions
- Python 3.11+, FastAPI, Uvicorn (single worker, see Database Notes on why
  multiple processes would break SQLite write-claiming).
- Fully async: SQLAlchemy 2.0 async ORM + `aiosqlite` driver. No sync DB calls
  anywhere in request/worker paths.
- Migrations: Alembic.
- Package layout: `app/{tenants,templates,notifications,delivery,common}/`,
  each with `models.py`, `schemas.py` (Pydantic V2), `router.py`, `service.py`.
- Dependency injection via FastAPI's `Depends()` — services take their
  dependencies (DB session, settings) as constructor args, wired through a
  provider function, not instantiated ad hoc inside route handlers.
- All entities have a `tenant_id` column; every query must be tenant-scoped.
  Never write a query that can leak across tenants.
- Timestamps: `datetime` objects, always timezone-aware UTC
  (`datetime.now(timezone.utc)`), stored as ISO 8601 strings or epoch: pick
  one and apply consistently, don't mix naive and aware datetimes.

## Database Notes (SQLite-specific: read before writing dispatch logic)
- Enable WAL mode (`PRAGMA journal_mode=WAL`) and a `busy_timeout` on every
  connection — SQLite allows concurrent readers but only one writer at a
  time; without WAL + busy_timeout, concurrent writers raise
  "database is locked" instead of waiting.
- The atomic claim pattern below still works correctly under SQLite's
  locking model (one writer succeeds, others get 0 rows affected) — it does
  NOT need row-level locking like `SELECT ... FOR UPDATE`, which SQLite
  doesn't support anyway.
- Because writes serialize at the DB level, "concurrent dispatch" here means
  concurrent asyncio tasks attempting claims, not concurrent DB throughput.
  Document this explicitly as an assumption in README.md — it's a deliberate
  tradeoff for a single-process, no-distributed-systems scope, not a bug.
- Run with a single Uvicorn worker process. Multiple processes against the
  same SQLite file multiply lock contention without adding real throughput.

## Core Domain Decisions (do not re-derive these — they're settled)
- `Notification` = the logical send request. `DeliveryAttempt` = one
  per-channel, per-recipient unit of work, independently retried/tracked.
- Delivery state machine: CREATED → SCHEDULED → PENDING → SENDING →
  SENT | FAILED → RETRYING → DEAD_LETTERED. Every transition is written to
  `audit_log` (who/what/when/old_state/new_state).
- No-duplicate-on-retry is enforced via atomic claim:
  `UPDATE delivery_attempt SET status='SENDING' WHERE id=? AND status='PENDING'`
  — proceed only if rows-affected = 1. Never use a SELECT-then-UPDATE pattern
  for claiming work. See Database Notes for SQLite-specific locking behavior.
- Rate limiting: in-memory token bucket per (tenant_id, channel), guarded by
  an `asyncio.Lock` per bucket (not `threading.Lock` — everything here runs
  on one event loop).
- Fairness: per-tenant `asyncio.Queue`s feeding a bounded pool of worker
  coroutines (size set by `asyncio.Semaphore`, not OS threads) via
  round-robin dispatch — never a single shared queue with no tenant
  isolation.
- Retry/backoff: exponential with jitter, `next_attempt_at` column, polled by
a plain asyncio background task started at app startup —
while True: await asyncio.sleep(POLL_INTERVAL_SECONDS), then query and
dispatch due rows each tick. No APScheduler, no external message broker —
this is the leanest option for a 48-hour scope and the easiest to test
(just call the poll function directly in tests instead of sleeping).

## Testing
- Unit tests for: token bucket math, backoff calculator, state machine
  transition validity, template variable substitution.
- Integration tests (`pytest` + `pytest-asyncio` + `httpx.AsyncClient` against
  the FastAPI app) for: full lifecycle create→dispatch→fail→retry→succeed;
  concurrent claim test asserting exactly one winner when multiple asyncio
  tasks race to claim the same row; fairness test asserting a flooding
  tenant doesn't starve others.
- Each test run gets a fresh SQLite file (or `sqlite+aiosqlite:///:memory:`
  with a shared connection for the test session) — no external DB process
  to spin up, so no Testcontainers needed.
- Run tests with: `pytest -q` (add `-m "not integration"` if you split
  unit/integration with markers).

## Workflow Preferences
- Before implementing anything non-trivial (new entity, new state machine
  transition, concurrency-sensitive code), propose the approach in 3-5
  bullets before writing code. Wait for go-ahead on anything touching the
  claim/retry logic specifically — that's the highest-risk code in this repo.
- Prefer explicit, named SQLAlchemy Core/`text()` queries over ORM-magic
  query-building for anything involving tenant scoping or the atomic claim
  update, so the locking behavior is visible in code review.
- When adding a feature not explicitly in the PRD's "in scope" list, flag it
  as a scoping decision and note it in README.md assumptions rather than
  silently building it.

## Out of Scope (per assessment instructions — do not build)
- UI/frontend, Docker/CI-CD, OAuth/SSO/MFA, distributed systems/microservices,
  production observability/alerting.

## Open Decisions
- Push/SMS/email "send" calls: Providers: fully mock. Create a MockProvider class that uses asyncio.sleep(0.1) to simulate network latency and randomly fails 10% of the time to trigger the retry logic.
- Webhook callback endpoint for async provider delivery confirmation: build
  if time allows after core flows are solid.