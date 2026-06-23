import asyncio

import pytest
from sqlalchemy import select

from app.common.enums import DeliveryStatus
from app.delivery.dispatch import claim_and_send
from app.delivery.models import AuditLog, DeliveryAttempt
from tests.seed import create_due_delivery_attempt, create_tenant


class AlwaysSucceedProvider:
    async def send(self, recipient, subject, body):
        return True


@pytest.mark.asyncio
async def test_exactly_one_winner_when_n_tasks_race_to_claim_the_same_row(session_factory):
    async with session_factory() as setup_session:
        tenant = await create_tenant(setup_session, name="RaceTenant", slug="race-tenant")
        attempt = await create_due_delivery_attempt(setup_session, tenant.id)
        await setup_session.commit()
        attempt_id = attempt.id

    # Each task gets its own session, matching production: every worker
    # opens a fresh AsyncSessionLocal() per item (see engine.py's
    # _worker_loop) -- never a session shared across concurrent claims.
    async def attempt_claim():
        async with session_factory() as session:
            provider = AlwaysSucceedProvider()
            return await claim_and_send(attempt_id, session, provider)

    results = await asyncio.gather(*(attempt_claim() for _ in range(20)))

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1
    assert len(losers) == 19
    assert winners[0] == DeliveryStatus.SENT

    async with session_factory() as session:
        final = await session.get(DeliveryAttempt, attempt_id)
        assert final.status == DeliveryStatus.SENT.value

        audit_result = await session.execute(
            select(AuditLog).where(AuditLog.entity_type == "delivery_attempt", AuditLog.entity_id == attempt_id)
        )
        audit_rows = audit_result.scalars().all()
        # Exactly one claim's worth of audit entries -- losers wrote none.
        assert len(audit_rows) == 2
        assert {(r.old_state, r.new_state) for r in audit_rows} == {
            ("PENDING", "SENDING"),
            ("SENDING", "SENT"),
        }
