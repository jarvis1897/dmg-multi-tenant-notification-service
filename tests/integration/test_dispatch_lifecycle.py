from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.common.config import settings
from app.common.enums import DeliveryStatus, NotificationStatus
from app.delivery.dispatch import claim_and_send
from app.delivery.models import AuditLog, DeliveryAttempt
from app.notifications.models import NotificationChannel
from tests.seed import create_due_delivery_attempt, create_tenant


class ScriptedProvider:
    """Returns a pre-programmed sequence of outcomes instead of real randomness."""

    def __init__(self, outcomes: list[bool]):
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, str | None, str]] = []

    async def send(self, recipient: str, subject: str | None, body: str) -> bool:
        self.calls.append((recipient, subject, body))
        return self._outcomes.pop(0)


async def _audit_chain(session, entity_id: str) -> list[tuple[str, str]]:
    result = await session.execute(
        select(AuditLog.old_state, AuditLog.new_state)
        .where(AuditLog.entity_type == "delivery_attempt", AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at)
    )
    return [(row[0], row[1]) for row in result.all()]


async def _unblock_retry(session, attempt_id: str) -> None:
    """Simulate the backoff window having elapsed, without a real sleep."""
    attempt = await session.get(DeliveryAttempt, attempt_id)
    attempt.next_attempt_at = None
    await session.commit()


@pytest.mark.asyncio
async def test_happy_path_first_attempt_succeeds(db_session):
    tenant = await create_tenant(db_session, name="HappyPath", slug="happy-path")
    attempt = await create_due_delivery_attempt(db_session, tenant.id)
    await db_session.commit()

    provider = ScriptedProvider([True])
    result = await claim_and_send(attempt.id, db_session, provider)

    assert result == DeliveryStatus.SENT

    refreshed = await db_session.get(DeliveryAttempt, attempt.id)
    assert refreshed.status == DeliveryStatus.SENT.value
    assert refreshed.attempt_count == 0
    assert refreshed.sent_at is not None
    assert refreshed.last_error is None

    assert await _audit_chain(db_session, attempt.id) == [
        ("PENDING", "SENDING"),
        ("SENDING", "SENT"),
    ]

    channel = await db_session.get(NotificationChannel, refreshed.notification_channel_id)
    assert channel.status == NotificationStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_success_after_a_few_retries_with_exponential_backoff(db_session, monkeypatch):
    monkeypatch.setattr(settings, "base_backoff_seconds", 2.0)
    monkeypatch.setattr(settings, "max_backoff_seconds", 1000.0)
    monkeypatch.setattr(settings, "retry_jitter_seconds", 1.0)

    tenant = await create_tenant(db_session, name="RetrySuccess", slug="retry-success")
    attempt = await create_due_delivery_attempt(db_session, tenant.id, max_attempts=5)
    await db_session.commit()

    provider = ScriptedProvider([False, False, True])

    # Attempt 1: fails -> RETRYING
    result = await claim_and_send(attempt.id, db_session, provider)
    assert result == DeliveryStatus.RETRYING
    a = await db_session.get(DeliveryAttempt, attempt.id)
    assert a.attempt_count == 1
    backoff_1 = (a.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    # base * 2**1 = 4, plus jitter in [0,1) => expect roughly [3, 5]
    assert 3.0 <= backoff_1 <= 5.5
    await _unblock_retry(db_session, attempt.id)

    # Attempt 2: fails again -> RETRYING, backoff grows
    result = await claim_and_send(attempt.id, db_session, provider)
    assert result == DeliveryStatus.RETRYING
    a = await db_session.get(DeliveryAttempt, attempt.id)
    assert a.attempt_count == 2
    backoff_2 = (a.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    # base * 2**2 = 8, plus jitter in [0,1) => expect roughly [7, 9]
    assert 7.0 <= backoff_2 <= 9.5
    assert backoff_2 > backoff_1
    await _unblock_retry(db_session, attempt.id)

    # Attempt 3: succeeds -> SENT
    result = await claim_and_send(attempt.id, db_session, provider)
    assert result == DeliveryStatus.SENT
    a = await db_session.get(DeliveryAttempt, attempt.id)
    assert a.status == DeliveryStatus.SENT.value
    assert a.attempt_count == 2  # unchanged by the successful attempt

    assert await _audit_chain(db_session, attempt.id) == [
        ("PENDING", "SENDING"),
        ("SENDING", "FAILED"),
        ("FAILED", "RETRYING"),
        ("RETRYING", "SENDING"),
        ("SENDING", "FAILED"),
        ("FAILED", "RETRYING"),
        ("RETRYING", "SENDING"),
        ("SENDING", "SENT"),
    ]

    channel = await db_session.get(NotificationChannel, a.notification_channel_id)
    assert channel.status == NotificationStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_failure_exhausts_retries_and_dead_letters(db_session):
    tenant = await create_tenant(db_session, name="DeadLetter", slug="dead-letter")
    attempt = await create_due_delivery_attempt(db_session, tenant.id, max_attempts=2)
    await db_session.commit()

    provider = ScriptedProvider([False, False])

    result = await claim_and_send(attempt.id, db_session, provider)
    assert result == DeliveryStatus.RETRYING
    await _unblock_retry(db_session, attempt.id)

    result = await claim_and_send(attempt.id, db_session, provider)
    assert result == DeliveryStatus.DEAD_LETTERED

    a = await db_session.get(DeliveryAttempt, attempt.id)
    assert a.status == DeliveryStatus.DEAD_LETTERED.value
    assert a.attempt_count == 2
    assert a.next_attempt_at is None

    assert await _audit_chain(db_session, attempt.id) == [
        ("PENDING", "SENDING"),
        ("SENDING", "FAILED"),
        ("FAILED", "RETRYING"),
        ("RETRYING", "SENDING"),
        ("SENDING", "FAILED"),
        ("FAILED", "DEAD_LETTERED"),
    ]

    channel = await db_session.get(NotificationChannel, a.notification_channel_id)
    assert channel.status == NotificationStatus.FAILED.value

    # A claim attempt on an already-dead row is a no-op, not an error.
    audit_count_before = len(await _audit_chain(db_session, attempt.id))
    result = await claim_and_send(attempt.id, db_session, provider)
    assert result is None
    assert len(await _audit_chain(db_session, attempt.id)) == audit_count_before


@pytest.mark.asyncio
async def test_claim_lost_on_row_not_pending_or_retrying_is_a_silent_noop(db_session):
    tenant = await create_tenant(db_session, name="ClaimLost", slug="claim-lost")
    attempt = await create_due_delivery_attempt(db_session, tenant.id, status=DeliveryStatus.SENDING)
    await db_session.commit()

    provider = ScriptedProvider([True])
    result = await claim_and_send(attempt.id, db_session, provider)

    assert result is None
    assert provider.calls == []  # never even called the provider
    assert await _audit_chain(db_session, attempt.id) == []
