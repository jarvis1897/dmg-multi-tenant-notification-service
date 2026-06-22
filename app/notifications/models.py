from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.enums import NotificationStatus
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.delivery.models import DeliveryAttempt
    from app.tenants.models import Tenant


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Logical send request.  One Notification → N DeliveryAttempts
    (one per channel/recipient pair).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Idempotency: same tenant cannot submit the same key twice
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_notification_idempotency"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # Channel enum value

    # Rendered (or raw) content — stored so retries use the same body
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # JSON array of recipient addresses / tokens
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Original template variables used to render body; kept for audit
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # NULL = send immediately; future datetime = schedule
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=NotificationStatus.CREATED.value, index=True
    )

    # Client-supplied dedup key; must be unique within tenant
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="notifications", lazy="noload")
    delivery_attempts: Mapped[list["DeliveryAttempt"]] = relationship(
        "DeliveryAttempt", back_populates="notification", lazy="noload"
    )
