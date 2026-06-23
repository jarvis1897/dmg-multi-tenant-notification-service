from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.config import settings
from app.common.enums import Channel, DeliveryStatus, NotificationStatus
from app.common.exceptions import ConflictError, NotFoundError, ValidationError
from app.delivery.models import AuditLog, DeliveryAttempt
from app.notifications.models import NotificationChannel, NotificationRequest
from app.notifications.schemas import NotificationRequestCreate
from app.recipients.models import Recipient, RecipientChannelAddress
from app.templates.models import Template
from app.templates.rendering import render


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, tenant_id: str, data: NotificationRequestCreate, created_by: str
    ) -> NotificationRequest:
        channels = list(dict.fromkeys(data.channels))
        recipient_ids = list(dict.fromkeys(data.recipient_ids))

        if data.idempotency_key:
            conflict = await self.db.execute(
                select(NotificationRequest).where(
                    NotificationRequest.tenant_id == tenant_id,
                    NotificationRequest.idempotency_key == data.idempotency_key,
                )
            )
            if conflict.scalar_one_or_none() is not None:
                raise ConflictError(
                    f"A notification request with idempotency_key '{data.idempotency_key}' already exists"
                )

        templates_by_channel = await self._resolve_templates(tenant_id, data.template_name, channels)
        await self._validate_recipients_exist(tenant_id, recipient_ids)
        self._validate_variables_complete(templates_by_channel, data.variables)
        addresses_by_channel = await self._resolve_addresses(
            tenant_id, channels, recipient_ids
        )

        is_scheduled = data.scheduled_at is not None
        request_status = NotificationStatus.SCHEDULED if is_scheduled else NotificationStatus.CREATED
        attempt_status = DeliveryStatus.SCHEDULED if is_scheduled else DeliveryStatus.PENDING

        notification_request = NotificationRequest(
            tenant_id=tenant_id,
            template_name=data.template_name,
            channels=[c.value for c in channels],
            recipient_ids=recipient_ids,
            variables=data.variables,
            scheduled_at=data.scheduled_at,
            status=request_status.value,
            idempotency_key=data.idempotency_key,
            created_by=created_by,
        )
        self.db.add(notification_request)
        await self.db.flush()
        self._audit(
            tenant_id, "notification_request", notification_request.id, created_by, notification_request.status
        )

        any_channel_succeeded = False
        for channel in channels:
            template = templates_by_channel[channel]
            channel_addresses = addresses_by_channel[channel]

            skipped_recipients: dict[str, str] = {}
            recipients_with_address: list[str] = []
            for recipient_id in recipient_ids:
                if recipient_id in channel_addresses:
                    recipients_with_address.append(recipient_id)
                else:
                    skipped_recipients[recipient_id] = (
                        f"no {channel.value} address registered for this recipient"
                    )

            if recipients_with_address:
                any_channel_succeeded = True
                channel_status = request_status
            else:
                channel_status = NotificationStatus.FAILED

            notification_channel = NotificationChannel(
                notification_request_id=notification_request.id,
                tenant_id=tenant_id,
                channel=channel.value,
                template_id=template.id,
                rendered_subject=render(template.subject, data.variables) if template.subject else None,
                rendered_body=render(template.body, data.variables),
                status=channel_status.value,
                skipped_recipients=skipped_recipients,
            )
            self.db.add(notification_channel)
            await self.db.flush()
            self._audit(
                tenant_id, "notification_channel", notification_channel.id, created_by, notification_channel.status
            )

            for recipient_id in recipients_with_address:
                self.db.add(
                    DeliveryAttempt(
                        notification_channel_id=notification_channel.id,
                        tenant_id=tenant_id,
                        channel=channel.value,
                        recipient_id=recipient_id,
                        address=channel_addresses[recipient_id],
                        status=attempt_status.value,
                        next_attempt_at=data.scheduled_at,
                        max_attempts=settings.max_attempts,
                    )
                )

        if not any_channel_succeeded:
            notification_request.status = NotificationStatus.FAILED.value

        await self.db.flush()
        return await self.get_by_id(tenant_id, notification_request.id)

    async def get_by_id(self, tenant_id: str, request_id: str) -> NotificationRequest:
        result = await self.db.execute(
            select(NotificationRequest)
            .where(NotificationRequest.id == request_id, NotificationRequest.tenant_id == tenant_id)
            .options(selectinload(NotificationRequest.notification_channels))
        )
        notification_request = result.scalar_one_or_none()
        if notification_request is None:
            raise NotFoundError(f"NotificationRequest '{request_id}' not found")
        return notification_request

    async def get_delivery_attempt_counts(self, notification_request: NotificationRequest) -> dict[str, int]:
        channel_ids = [c.id for c in notification_request.notification_channels]
        if not channel_ids:
            return {}
        result = await self.db.execute(
            select(DeliveryAttempt.notification_channel_id, func.count(DeliveryAttempt.id))
            .where(DeliveryAttempt.notification_channel_id.in_(channel_ids))
            .group_by(DeliveryAttempt.notification_channel_id)
        )
        return dict(result.all())

    async def _resolve_templates(
        self, tenant_id: str, template_name: str, channels: list[Channel]
    ) -> dict[Channel, Template]:
        templates_by_channel: dict[Channel, Template] = {}
        missing: list[str] = []
        for channel in channels:
            result = await self.db.execute(
                select(Template).where(
                    Template.tenant_id == tenant_id,
                    Template.name == template_name,
                    Template.channel == channel.value,
                    Template.is_active.is_(True),
                )
            )
            template = result.scalar_one_or_none()
            if template is None:
                missing.append(channel.value)
            else:
                templates_by_channel[channel] = template

        if missing:
            raise NotFoundError(
                f"No active template named '{template_name}' for channel(s): {', '.join(missing)}"
            )
        return templates_by_channel

    async def _validate_recipients_exist(self, tenant_id: str, recipient_ids: list[str]) -> None:
        result = await self.db.execute(
            select(Recipient.id).where(Recipient.tenant_id == tenant_id, Recipient.id.in_(recipient_ids))
        )
        found = {row[0] for row in result.all()}
        missing = [rid for rid in recipient_ids if rid not in found]
        if missing:
            raise NotFoundError(f"Recipient(s) not found for this tenant: {', '.join(missing)}")

    def _validate_variables_complete(
        self, templates_by_channel: dict[Channel, Template], variables: dict
    ) -> None:
        for channel, template in templates_by_channel.items():
            missing_vars = [v for v in template.variables if v not in variables]
            if missing_vars:
                raise ValidationError(
                    f"Missing variable(s) for channel '{channel.value}': {', '.join(missing_vars)}"
                )

    async def _resolve_addresses(
        self, tenant_id: str, channels: list[Channel], recipient_ids: list[str]
    ) -> dict[Channel, dict[str, str]]:
        addresses_by_channel: dict[Channel, dict[str, str]] = {}
        for channel in channels:
            result = await self.db.execute(
                select(RecipientChannelAddress.recipient_id, RecipientChannelAddress.address).where(
                    RecipientChannelAddress.tenant_id == tenant_id,
                    RecipientChannelAddress.channel == channel.value,
                    RecipientChannelAddress.recipient_id.in_(recipient_ids),
                )
            )
            addresses_by_channel[channel] = dict(result.all())
        return addresses_by_channel

    def _audit(self, tenant_id: str, entity_type: str, entity_id: str, actor_id: str, new_state: str) -> None:
        self.db.add(
            AuditLog(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_id=actor_id,
                action="created",
                old_state=None,
                new_state=new_state,
            )
        )
