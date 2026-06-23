from app.common.auth import create_access_token, hash_password
from app.common.enums import Channel, DeliveryStatus, NotificationStatus, UserRole
from app.delivery.models import DeliveryAttempt
from app.notifications.models import NotificationChannel, NotificationRequest
from app.recipients.models import Recipient, RecipientChannelAddress
from app.templates.models import Template
from app.tenants.models import Tenant
from app.users.models import User


async def create_tenant(session, name="Acme", slug="acme", **overrides) -> Tenant:
    tenant = Tenant(
        name=name,
        slug=slug,
        api_key_hash=hash_password("test-api-key"),
        rate_limit_email=overrides.pop("rate_limit_email", 1000),
        rate_limit_sms=overrides.pop("rate_limit_sms", 1000),
        rate_limit_push=overrides.pop("rate_limit_push", 1000),
        rate_limit_in_app=overrides.pop("rate_limit_in_app", 1000),
        **overrides,
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def create_tenant_admin(session, tenant_id: str, email="tadmin@test.com") -> User:
    user = User(
        tenant_id=tenant_id,
        email=email,
        hashed_password=hash_password("password123"),
        role=UserRole.TENANT_ADMIN,
    )
    session.add(user)
    await session.flush()
    return user


async def create_platform_admin(session, email="admin@test.com") -> User:
    user = User(
        tenant_id=None,
        email=email,
        hashed_password=hash_password("password123"),
        role=UserRole.PLATFORM_ADMIN,
    )
    session.add(user)
    await session.flush()
    return user


def auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.role, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


async def create_template(
    session,
    tenant_id: str,
    name="welcome",
    channel: Channel = Channel.EMAIL,
    body="Hi {{first_name}}",
    subject="Welcome",
    variables=None,
) -> Template:
    template = Template(
        tenant_id=tenant_id,
        name=name,
        channel=channel.value,
        subject=subject if channel == Channel.EMAIL else None,
        body=body,
        variables=variables if variables is not None else ["first_name"],
    )
    session.add(template)
    await session.flush()
    return template


async def create_recipient(
    session, tenant_id: str, external_key="r1", addresses: dict[Channel, str] | None = None
) -> Recipient:
    recipient = Recipient(tenant_id=tenant_id, external_key=external_key, display_name=external_key)
    session.add(recipient)
    await session.flush()

    for channel, address in (addresses or {}).items():
        session.add(
            RecipientChannelAddress(
                recipient_id=recipient.id, tenant_id=tenant_id, channel=channel.value, address=address
            )
        )
    await session.flush()
    return recipient


async def create_due_delivery_attempt(
    session,
    tenant_id: str,
    channel: Channel = Channel.EMAIL,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    attempt_count: int = 0,
    max_attempts: int = 5,
    next_attempt_at=None,
    address="recipient@example.com",
) -> DeliveryAttempt:
    """
    Seeds a full Recipient + NotificationRequest -> NotificationChannel ->
    DeliveryAttempt chain directly (bypassing POST /notifications) so
    dispatch-engine tests can exercise claim_and_send / poll_due_attempts
    in isolation.
    """
    recipient = await create_recipient(session, tenant_id, external_key=f"r-{address}")

    request = NotificationRequest(
        tenant_id=tenant_id,
        template_name="test-template",
        channels=[channel.value],
        recipient_ids=[recipient.id],
        variables={},
        status=NotificationStatus.CREATED.value,
    )
    session.add(request)
    await session.flush()

    notification_channel = NotificationChannel(
        notification_request_id=request.id,
        tenant_id=tenant_id,
        channel=channel.value,
        rendered_subject=None,
        rendered_body="test body",
        status=NotificationStatus.CREATED.value,
        skipped_recipients={},
    )
    session.add(notification_channel)
    await session.flush()

    attempt = DeliveryAttempt(
        notification_channel_id=notification_channel.id,
        tenant_id=tenant_id,
        channel=channel.value,
        recipient_id=recipient.id,
        address=address,
        status=status.value,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        next_attempt_at=next_attempt_at,
    )
    session.add(attempt)
    await session.flush()
    return attempt
