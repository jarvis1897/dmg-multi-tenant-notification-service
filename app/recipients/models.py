from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.tenants.models import Tenant


class Recipient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A person/identity a tenant knows about, independent of any single
    channel. Reachable on zero or more channels via RecipientChannelAddress.
    """

    __tablename__ = "recipients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_key", name="uq_recipient_tenant_external_key"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The tenant's own identifier for this person (e.g. their user ID)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="recipients", lazy="noload")
    channel_addresses: Mapped[list[RecipientChannelAddress]] = relationship(
        "RecipientChannelAddress", back_populates="recipient", lazy="noload"
    )


class RecipientChannelAddress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One reachable address for a Recipient on a single channel
    (email address, phone number, push device token, or in-app user id).
    """

    __tablename__ = "recipient_channel_addresses"
    __table_args__ = (
        UniqueConstraint("recipient_id", "channel", name="uq_recipient_channel"),
    )

    recipient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized for direct tenant-scoped queries without a join,
    # consistent with delivery_attempts.tenant_id.
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # Channel enum value
    address: Mapped[str] = mapped_column(String(500), nullable=False)

    recipient: Mapped[Recipient] = relationship(
        "Recipient", back_populates="channel_addresses", lazy="noload"
    )
