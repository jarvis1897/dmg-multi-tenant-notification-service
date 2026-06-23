# Multi-tenant Notification Service — Project Memory

## Project Overview
FastAPI service supporting multi-tenant notification dispatch across
email/SMS/push/in-app channels, with templates, scheduling, per-tenant rate
limiting, retries with backoff, and delivery tracking. Built for a 48-hour
take-home assessment. No distributed systems, no external queues — single
process, asyncio-based concurrency, persistence via SQLite.

## Stack & Conventions
- Python 3.11+, FastAPI, Uvicorn (single worker — see Database Notes on why
  multiple processes would break SQLite write-claiming).
- Fully async: SQLAlchemy 2.0 async ORM + `aiosqlite` driver. No sync DB calls
  anywhere in request/worker paths.
- Migrations: Alembic.
- Package layout: `app/{tenants,users,templates,notifications,delivery,recipients,common}/`,
  each with `models.py`, `schemas.py` (Pydantic), `router.py`, `service.py`.
  (`users` is separate from `tenants` because platform admins aren't
  tenant-scoped — see User model's CHECK constraint.)
- Dependency injection via FastAPI's `Depends()` — services take their
  dependencies (DB session, settings) as constructor args, wired through a
  provider function, not instantiated ad hoc inside route handlers.
- All entities have a `tenant_id` column; every query must be tenant-scoped.
  Never write a query that can leak across tenants. `NotificationChannel`
  and `DeliveryAttempt` carry `tenant_id` denormalized from their parent
  `NotificationRequest` (set once at creation) — not just for the
  convention, but because the dispatch engine's poll query needs cheap
  per-tenant grouping on every tick; a join through 2 tables on every poll
  cycle is unnecessary overhead on the hot path.
- Timestamps: `datetime` objects, always timezone-aware UTC
  (`datetime.now(timezone.utc)`), stored as ISO 8601 strings or epoch — pick
  one and apply consistently, don't mix naive and aware datetimes.

## Database Notes (SQLite-specific — read before writing dispatch logic)
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

## Auth & RBAC (settled)
- JWT issued from `POST /login` (email + password, bcrypt-hashed password
  at rest). No OAuth/SSO/MFA — out of scope per PRD.
- `get_current_user` dependency decodes the JWT and loads the `User`.
  Separate `require_platform_admin` / `require_tenant_admin` dependencies
  wrap it for route-level role checks — don't scatter `if role == ...`
  checks inside route bodies.
- A `TENANT_ADMIN`'s tenant scope comes from their own `User.tenant_id`,
  never from a request body/query param — don't let a tenant admin pass a
  different `tenant_id` and act on it.

## Core Domain Decisions (do not re-derive these — they're settled)
- Three-level fan-out: `NotificationRequest` (the client's intent — template
  + variables + recipient list + optional `scheduled_at`) → one
  `NotificationChannel` per requested channel → one `DeliveryAttempt` per
  recipient on that channel. This is what lets one API call mean "email AND
  sms this group" while tracking each channel/recipient independently.
- `Recipient` (tenant-scoped) + `RecipientChannelAddress` (one row per
  channel a recipient is reachable on) replace raw address strings in the
  request body. A `NotificationRequest` carries a list of `recipient_id`s,
  not raw emails/phone numbers — same list reused across every requested
  channel.
- **Recipients without a registered address for a requested channel are
  skipped for that channel only** (no `DeliveryAttempt` created for that
  pair) rather than failing the whole request. Recorded in
  `NotificationChannel.skipped_recipients` (JSON: `{recipient_id: reason}`).
  This was an explicit PRD-scoping decision — document it in README.md.
- A `NotificationChannel` row is **always created for every channel
  requested**, even if every recipient ends up skipped for it (status
  resolves to `FAILED` in that case). Never silently omit a channel from
  the response/report just because nobody had an address for it — the
  tenant admin needs to see "you asked for SMS, zero recipients had a
  phone number" rather than the channel quietly not appearing.
- Delivery state machine: CREATED → SCHEDULED → PENDING → SENDING →
  SENT | FAILED → RETRYING → DEAD_LETTERED. Every transition is written to
  `audit_log` (who/what/when/old_state/new_state).
- No-duplicate-on-retry is enforced via atomic claim:
  `UPDATE delivery_attempt SET status='SENDING' WHERE id=? AND status='PENDING'`
  — proceed only if rows-affected = 1. Never use a SELECT-then-UPDATE pattern
  for claiming work. See Database Notes for SQLite-specific locking behavior.

## Dispatch Engine (settled — three-stage pipeline)
By the time the dispatch engine runs, `DeliveryAttempt` rows already exist
at `PENDING` (created during `POST /notifications`, where channel/recipient
address resolution already happened). The dispatch engine's only job is:
find PENDING/RETRYING rows and actually try to send them. Don't re-derive
the routing/skip logic here — that's already done upstream.

1. **Poll loop** — plain `asyncio` background task, `while True: await
   asyncio.sleep(POLL_INTERVAL_SECONDS)`. Each tick: query
   `DeliveryAttempt WHERE status IN ('PENDING','RETRYING') AND
   (next_attempt_at IS NULL OR next_attempt_at <= now)`, group by
   `tenant_id`, push onto that tenant's `asyncio.Queue` (lazily created,
   held in `dict[tenant_id, Queue]`). Track an in-memory
   `in_flight: set[delivery_attempt_id]` so a slow item isn't re-queued by
   the next tick before a worker finishes it — remove from the set when a
   worker completes.
2. **Dispatcher** (single coroutine — fairness AND rate-limiting meet
   here, not two separate systems). Round-robins across tenant queues with
   items waiting. Per tenant's turn: peek the front item, check the token
   bucket for `(tenant_id, channel)` (in-memory, `asyncio.Lock`-guarded —
   not `threading.Lock`, everything runs on one event loop). Token
   available → pop it onto a shared `work_queue` for workers. No token →
   leave it queued, move to the next tenant's turn instead of blocking. A
   rate-limited tenant gets skipped that round, not starved or stalling
   the rotation.
3. **Worker pool** — bounded, `WORKER_POOL_SIZE` coroutines (default 10,
   sized via `asyncio.Semaphore`, not OS threads). Each worker:
   `await work_queue.get()` → atomic claim, check rowcount == 1 → claim
   lost (0 rows) → drop silently, no error (shouldn't happen often given
   the in-flight set, but the claim is the real correctness guarantee, not
   the set) → claim won → call the mocked provider (see below) → on
   success: `SENT`; on failure: increment `attempt_number`, compute
   backoff (`min(BASE_BACKOFF_SECONDS * 2 ** attempt_number +
   random.uniform(0, jitter), MAX_BACKOFF_SECONDS)`), set
   `next_attempt_at`, status → `RETRYING`; attempt_number >=
   `MAX_ATTEMPTS` → `DEAD_LETTERED` instead. Every transition writes an
   `AuditLog` row, regardless of outcome. After a terminal transition,
   recompute the parent `NotificationChannel`'s aggregate status by
   recounting its children (no event bus needed at this scale): any
   PENDING/RETRYING left → PROCESSING; all SENT → COMPLETED; mix of SENT
   and FAILED/DEAD_LETTERED/skipped → PARTIALLY_FAILED; none SENT →
   FAILED.

**Mocked provider**: one interface (`async def send(recipient, subject,
body) -> bool`), one implementation per channel, each with a configurable
simulated failure rate (`SIMULATE_FAILURE_RATE` env var, default 0.1) —
this is what actually exercises retry/backoff/DLQ logic under test instead
of every send trivially succeeding.

**Default tunables** (override via env vars, don't hardcode):
`POLL_INTERVAL_SECONDS=3`, `WORKER_POOL_SIZE=10`, `MAX_ATTEMPTS=5`,
`BASE_BACKOFF_SECONDS=2`, `MAX_BACKOFF_SECONDS=60`.

**Structure as separate, independently-callable functions** — not one
combined `run_dispatch_cycle()`. Each stage gets its own `async def` that
a test can call directly without waiting on real sleeps or real queue
timing:
- `async def poll_due_attempts(session) -> dict[tenant_id, list[DeliveryAttempt]]`
- `async def dispatch_round(tenant_queues, token_buckets, work_queue) -> None`
  (one round of the round-robin — a test can call this directly and assert
  on `work_queue` contents instead of running the real loop)
- `async def claim_and_send(delivery_attempt_id, session, provider) -> DeliveryStatus`
  (the actual atomic-claim + provider-call + state-transition unit — this
  is what the concurrent-claim test calls from N tasks at once)
The `while True: sleep(...)` loops (poll loop, dispatcher loop, worker
loop) are then thin wrappers that just call these functions in a cycle —
keep them so small there's nothing in them worth unit testing directly.

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

## Open Decisions (update as resolved — keep this section short-lived)
- Webhook callback endpoint for async provider delivery confirmation: build
  if time allows after core flows are solid.