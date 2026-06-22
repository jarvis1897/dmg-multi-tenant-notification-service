from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.enums import NotificationStatus
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.delivery.models import DeliveryAttempt
    from app.tenants.models import Tenant


class NotificationRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    The client's intent: one logical template, fanned out across a set of
    requested channels to a set of recipients. See NotificationChannel for
    the per-channel breakdown and DeliveryAttempt (app.delivery.models) for
    the per-recipient unit of work.
    """

    __tablename__ = "notification_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_notification_request_idempotency"
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Logical template name; resolved per-channel against
    # Template(tenant_id, name=template_name, channel) — see
    # uq_template_tenant_name_channel on the templates table.
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Requested channels, e.g. ["email", "sms"] — one NotificationChannel
    # row is created per entry.
    channels: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # recipients.id values; validated against the tenant's own recipients at
    # the service layer — SQLite cannot enforce a FK into JSON elements.
    recipient_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Template variables, applied uniformly across every requested channel.
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # NULL = send immediately; future datetime = schedule.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Aggregate status rolled up across all NotificationChannels.
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=NotificationStatus.CREATED.value, index=True
    )

    # Client-supplied dedup key; unique within tenant.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    tenant: Mapped[Tenant] = relationship(
        "Tenant", back_populates="notification_requests", lazy="noload"
    )
    notification_channels: Mapped[list[NotificationChannel]] = relationship(
        "NotificationChannel", back_populates="notification_request", lazy="noload"
    )


class NotificationChannel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One requested channel within a NotificationRequest. Holds the rendered
    content actually used for delivery — an immutable snapshot taken at
    creation time, independent of later edits to the underlying Template —
    and tracks recipients skipped on this channel because they have no
    registered RecipientChannelAddress for it.
    """

    __tablename__ = "notification_channels"
    __table_args__ = (
        UniqueConstraint(
            "notification_request_id", "channel", name="uq_notification_channel_request_channel"
        ),
    )

    notification_request_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("notification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for direct tenant-scoped queries without a join back
    # through notification_requests, consistent with delivery_attempts.
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)

    # The concrete Template resolved for (tenant_id, template_name, channel)
    # at creation time. Nullable because the template could later be
    # deleted without invalidating this historical record.
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )

    rendered_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rendered_body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=NotificationStatus.CREATED.value, index=True
    )

    # {recipient_id: reason} for recipients with no address on this channel.
    skipped_recipients: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)

    notification_request: Mapped[NotificationRequest] = relationship(
        "NotificationRequest", back_populates="notification_channels", lazy="noload"
    )
    delivery_attempts: Mapped[list[DeliveryAttempt]] = relationship(
        "DeliveryAttempt", back_populates="notification_channel", lazy="noload"
    )
