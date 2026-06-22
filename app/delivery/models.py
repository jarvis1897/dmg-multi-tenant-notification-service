from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.enums import DeliveryStatus
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin, _now_utc

if TYPE_CHECKING:
    from app.notifications.models import NotificationChannel


class DeliveryAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One unit of work: delivering a single NotificationChannel's rendered
    content to a single recipient.  Claimed atomically via
    UPDATE…WHERE status='PENDING' to avoid duplicate dispatch on retry races.
    """

    __tablename__ = "delivery_attempts"

    notification_channel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized tenant_id/channel so every query can be scoped/filtered
    # without a join back through notification_channels.
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)

    recipient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Resolved RecipientChannelAddress.address snapshot taken at fan-out
    # time — stays correct even if the recipient's address changes later.
    address: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DeliveryStatus.CREATED.value, index=True
    )

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Set to a future time when the attempt should next be retried
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Opaque ID returned by the provider on successful send
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notification_channel: Mapped[NotificationChannel] = relationship(
        "NotificationChannel", back_populates="delivery_attempts", lazy="noload"
    )


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """
    Append-only record of every state transition and significant action.
    Never updated after insert — no updated_at column.
    """

    __tablename__ = "audit_logs"

    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # NULL actor_id = system-initiated (background worker, scheduler)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    action: Mapped[str] = mapped_column(String(255), nullable=False)
    old_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Renamed to avoid shadowing SQLAlchemy internals; column name stays 'metadata'
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )
