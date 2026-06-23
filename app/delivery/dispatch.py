from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import settings
from app.common.enums import DeliveryStatus, NotificationStatus
from app.delivery.backoff import compute_backoff
from app.delivery.models import AuditLog, DeliveryAttempt
from app.delivery.provider import Provider
from app.delivery.rate_limit import TokenBucket
from app.notifications.models import NotificationChannel


@dataclass(frozen=True)
class DueAttempt:
    id: str
    channel: str


async def poll_due_attempts(session: AsyncSession) -> dict[str, list[DeliveryAttempt]]:
    """
    Find DeliveryAttempt rows ready to be worked: PENDING (never tried) or
    RETRYING whose backoff has elapsed. Grouped by tenant_id. Rows are
    expunged from the session before being returned — the caller may hold
    onto them (via queues) far longer than this session lives.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(DeliveryAttempt).where(
            DeliveryAttempt.status.in_([DeliveryStatus.PENDING.value, DeliveryStatus.RETRYING.value]),
            or_(DeliveryAttempt.next_attempt_at.is_(None), DeliveryAttempt.next_attempt_at <= now),
        )
    )
    attempts = list(result.scalars().all())
    for attempt in attempts:
        session.expunge(attempt)

    by_tenant: dict[str, list[DeliveryAttempt]] = defaultdict(list)
    for attempt in attempts:
        by_tenant[attempt.tenant_id].append(attempt)
    return dict(by_tenant)


async def dispatch_round(
    tenant_queues: dict[str, asyncio.Queue[DueAttempt]],
    token_buckets: dict[tuple[str, str], TokenBucket],
    work_queue: asyncio.Queue[DueAttempt],
) -> None:
    """
    One round of round-robin across tenant queues with items waiting.
    Per tenant's turn: peek the front item, check the (tenant_id, channel)
    token bucket. Token available -> pop it onto work_queue. No token ->
    leave it queued, move to the next tenant's turn instead of blocking.
    """
    now = datetime.now(timezone.utc)

    for tenant_id, queue in list(tenant_queues.items()):
        if queue.empty():
            continue

        # asyncio.Queue has no public peek; it wraps a collections.deque
        # internally as _queue, which we read (never mutate) to inspect
        # the front item without removing it.
        item: DueAttempt = queue._queue[0]  # type: ignore[attr-defined]
        bucket = token_buckets.get((tenant_id, item.channel))
        if bucket is None:
            # The poll loop is responsible for creating a correctly-sized
            # bucket before enqueueing; this should not normally happen.
            continue

        async with bucket.lock:
            acquired = bucket.try_acquire(now)

        if acquired:
            queue.get_nowait()
            await work_queue.put(item)
        # else: rate-limited this round — stay queued, move to next tenant


async def claim_and_send(
    delivery_attempt_id: str, session: AsyncSession, provider: Provider
) -> DeliveryStatus | None:
    """
    The atomic-claim + provider-call + state-transition unit. Claims from
    PENDING or RETRYING (matching what poll_due_attempts selects) via a
    single UPDATE...WHERE, proceeding only if exactly one row was affected.
    Returns None if the claim was lost — another worker beat us to it —
    matching the "drop silently, no error" behavior in the spec.
    """
    now = datetime.now(timezone.utc)
    claim_result = await session.execute(
        text(
            "UPDATE delivery_attempts SET status = :sending, updated_at = :now "
            "WHERE id = :id AND status IN (:pending, :retrying)"
        ),
        {
            "sending": DeliveryStatus.SENDING.value,
            "now": now,
            "id": delivery_attempt_id,
            "pending": DeliveryStatus.PENDING.value,
            "retrying": DeliveryStatus.RETRYING.value,
        },
    )
    if claim_result.rowcount != 1:
        await session.commit()
        return None

    attempt = await session.get(DeliveryAttempt, delivery_attempt_id)
    old_state = DeliveryStatus.PENDING.value if attempt.attempt_count == 0 else DeliveryStatus.RETRYING.value
    _write_audit(session, attempt.tenant_id, attempt.id, old_state, DeliveryStatus.SENDING.value)
    await session.commit()

    channel = await session.get(NotificationChannel, attempt.notification_channel_id)

    try:
        success = await provider.send(attempt.address, channel.rendered_subject, channel.rendered_body)
    except Exception:
        success = False

    if success:
        attempt.status = DeliveryStatus.SENT.value
        attempt.sent_at = now
        attempt.last_error = None
        new_state = DeliveryStatus.SENT.value
        final_old_state = DeliveryStatus.SENDING.value
    else:
        attempt.attempt_count += 1
        attempt.last_error = f"provider send failed (attempt {attempt.attempt_count})"
        # FAILED is never persisted on the row — it's the conceptual
        # midpoint between SENDING and RETRYING/DEAD_LETTERED, recorded
        # only in the audit trail, since nothing else ever queries for it.
        _write_audit(
            session, attempt.tenant_id, attempt.id, DeliveryStatus.SENDING.value, DeliveryStatus.FAILED.value
        )

        if attempt.attempt_count >= attempt.max_attempts:
            attempt.status = DeliveryStatus.DEAD_LETTERED.value
            attempt.next_attempt_at = None
            new_state = DeliveryStatus.DEAD_LETTERED.value
        else:
            backoff = compute_backoff(
                attempt.attempt_count,
                settings.base_backoff_seconds,
                settings.max_backoff_seconds,
                settings.retry_jitter_seconds,
            )
            attempt.status = DeliveryStatus.RETRYING.value
            attempt.next_attempt_at = now + timedelta(seconds=backoff)
            new_state = DeliveryStatus.RETRYING.value
        final_old_state = DeliveryStatus.FAILED.value

    _write_audit(session, attempt.tenant_id, attempt.id, final_old_state, new_state)
    await session.commit()

    await _recompute_channel_status(session, attempt.notification_channel_id)
    await session.commit()

    return DeliveryStatus(new_state)


async def _recompute_channel_status(session: AsyncSession, notification_channel_id: str) -> None:
    """
    Recount this channel's DeliveryAttempts (no event bus needed at this
    scale): any PENDING/SCHEDULED/SENDING/RETRYING left -> PROCESSING; all
    SENT and nobody skipped -> COMPLETED; some SENT mixed with
    DEAD_LETTERED or skipped recipients -> PARTIALLY_FAILED; none SENT ->
    FAILED. Not itself audit-logged — only DeliveryAttempt transitions are.
    """
    result = await session.execute(
        select(DeliveryAttempt.status).where(DeliveryAttempt.notification_channel_id == notification_channel_id)
    )
    statuses = [row[0] for row in result.all()]
    if not statuses:
        return

    channel = await session.get(NotificationChannel, notification_channel_id)
    has_skipped = bool(channel.skipped_recipients)

    in_progress = {
        DeliveryStatus.SCHEDULED.value,
        DeliveryStatus.PENDING.value,
        DeliveryStatus.SENDING.value,
        DeliveryStatus.RETRYING.value,
    }
    sent_count = sum(1 for s in statuses if s == DeliveryStatus.SENT.value)

    if any(s in in_progress for s in statuses):
        new_status = NotificationStatus.PROCESSING
    elif sent_count == len(statuses) and not has_skipped:
        new_status = NotificationStatus.COMPLETED
    elif sent_count > 0:
        new_status = NotificationStatus.PARTIALLY_FAILED
    else:
        new_status = NotificationStatus.FAILED

    channel.status = new_status.value


def _write_audit(session: AsyncSession, tenant_id: str, entity_id: str, old_state: str, new_state: str) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            entity_type="delivery_attempt",
            entity_id=entity_id,
            actor_id=None,
            action="state_transition",
            old_state=old_state,
            new_state=new_state,
        )
    )
