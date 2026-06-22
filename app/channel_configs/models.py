from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.tenants.models import Tenant


class ChannelConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tenant-managed, per-channel settings (enabled/disabled + arbitrary
    channel-specific config like sender identity). Distinct from the
    platform-controlled rate limits on Tenant — this is tenant-admin
    self-service, those are platform-admin "global limits".
    """

    __tablename__ = "channel_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_channel_config_tenant_channel"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # e.g. {"from_email": "...", "from_name": "..."} for email,
    # {"sender_id": "..."} for sms, etc.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="channel_configs", lazy="noload")
