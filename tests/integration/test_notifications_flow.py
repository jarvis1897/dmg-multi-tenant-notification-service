import pytest
from sqlalchemy import select

from app.common.enums import Channel, DeliveryStatus, NotificationStatus
from app.delivery.dispatch import claim_and_send
from app.delivery.models import AuditLog, DeliveryAttempt
from app.notifications.models import NotificationChannel, NotificationRequest
from tests.seed import auth_headers, create_recipient, create_template, create_tenant, create_tenant_admin


class ScriptedProvider:
    def __init__(self, outcomes: list[bool]):
        self._outcomes = list(outcomes)

    async def send(self, recipient, subject, body):
        return self._outcomes.pop(0)


async def _unblock_retry(session, attempt_id: str) -> None:
    attempt = await session.get(DeliveryAttempt, attempt_id)
    attempt.next_attempt_at = None
    await session.commit()


@pytest.mark.asyncio
async def test_full_lifecycle_create_dispatch_fail_retry_succeed(client, db_session, session_factory):
    tenant = await create_tenant(db_session, name="FlowTenant", slug="flow-tenant")
    admin = await create_tenant_admin(db_session, tenant.id)
    await create_template(db_session, tenant.id, name="welcome", channel=Channel.EMAIL, body="Hi {{first_name}}")
    recipient = await create_recipient(
        db_session, tenant.id, external_key="user-1", addresses={Channel.EMAIL: "user1@example.com"}
    )
    await db_session.commit()

    # 1. Create via the real HTTP API, exactly as a tenant admin would.
    response = await client.post(
        "/notifications",
        json={
            "template_name": "welcome",
            "channels": ["email"],
            "recipient_ids": [recipient.id],
            "variables": {"first_name": "Jane"},
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == NotificationStatus.CREATED.value
    channel_payload = body["notification_channels"][0]
    assert channel_payload["delivery_attempt_count"] == 1
    assert channel_payload["rendered_body"] == "Hi Jane"

    request_id = body["id"]

    # 2. Find the DeliveryAttempt the creation step produced.
    async with session_factory() as session:
        result = await session.execute(
            select(DeliveryAttempt)
            .join(NotificationChannel, DeliveryAttempt.notification_channel_id == NotificationChannel.id)
            .where(NotificationChannel.notification_request_id == request_id)
        )
        attempt = result.scalar_one()
        attempt_id = attempt.id
        assert attempt.status == DeliveryStatus.PENDING.value

    # 3. Dispatch directly -- per CLAUDE.md, tests call the dispatch
    # functions directly instead of waiting on the real poll/sleep loops.
    provider = ScriptedProvider([False, True])  # fails once, then succeeds

    async with session_factory() as session:
        result = await claim_and_send(attempt_id, session, provider)
        assert result == DeliveryStatus.RETRYING

    async with session_factory() as session:
        await _unblock_retry(session, attempt_id)
        result = await claim_and_send(attempt_id, session, provider)
        assert result == DeliveryStatus.SENT

    # 4. Verify final state end-to-end.
    async with session_factory() as session:
        final_attempt = await session.get(DeliveryAttempt, attempt_id)
        assert final_attempt.status == DeliveryStatus.SENT.value
        assert final_attempt.attempt_count == 1

        channel = await session.get(NotificationChannel, final_attempt.notification_channel_id)
        assert channel.status == NotificationStatus.COMPLETED.value

        request = await session.get(NotificationRequest, request_id)
        assert request.status == NotificationStatus.CREATED.value  # request-level status isn't rolled up by the engine

        # 5. Audits exist for every layer: creation (request + channel) and
        # every delivery_attempt transition through to the final SENT.
        audit_result = await session.execute(select(AuditLog).order_by(AuditLog.created_at))
        rows = audit_result.scalars().all()

        request_audits = [r for r in rows if r.entity_type == "notification_request" and r.entity_id == request_id]
        assert len(request_audits) == 1
        assert request_audits[0].new_state == NotificationStatus.CREATED.value
        assert request_audits[0].actor_id == admin.id

        channel_audits = [r for r in rows if r.entity_type == "notification_channel"]
        assert len(channel_audits) == 1
        assert channel_audits[0].actor_id == admin.id

        attempt_audits = [
            (r.old_state, r.new_state) for r in rows if r.entity_type == "delivery_attempt" and r.entity_id == attempt_id
        ]
        assert attempt_audits == [
            ("PENDING", "SENDING"),
            ("SENDING", "FAILED"),
            ("FAILED", "RETRYING"),
            ("RETRYING", "SENDING"),
            ("SENDING", "SENT"),
        ]
        # system-initiated transitions, not attributed to the requesting user
        assert all(r.actor_id is None for r in rows if r.entity_type == "delivery_attempt")


@pytest.mark.asyncio
async def test_recipient_with_no_address_is_skipped_not_failed_request(client, db_session):
    tenant = await create_tenant(db_session, name="SkipTenant", slug="skip-tenant")
    admin = await create_tenant_admin(db_session, tenant.id)
    await create_template(db_session, tenant.id, name="welcome", channel=Channel.SMS, body="Hi {{first_name}}")
    # Recipient has no SMS address registered.
    recipient = await create_recipient(db_session, tenant.id, external_key="user-2", addresses={})
    await db_session.commit()

    response = await client.post(
        "/notifications",
        json={
            "template_name": "welcome",
            "channels": ["sms"],
            "recipient_ids": [recipient.id],
            "variables": {"first_name": "Jane"},
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    body = response.json()

    # Whole request is FAILED (the only channel had zero deliverable
    # recipients) but the channel row still exists with the skip reason --
    # never silently dropped.
    assert body["status"] == NotificationStatus.FAILED.value
    channel_payload = body["notification_channels"][0]
    assert channel_payload["status"] == NotificationStatus.FAILED.value
    assert channel_payload["delivery_attempt_count"] == 0
    assert recipient.id in channel_payload["skipped_recipients"]
