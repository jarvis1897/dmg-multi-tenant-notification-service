from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.notifications.models import Notification
    from app.recipients.models import Recipient
    from app.templates.models import Template
    from app.tenants.models import User


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # Stored as bcrypt hash; the raw key is shown once at creation time
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_notifications_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10_000)

    # Per-channel token-bucket rate limits (tokens replenished per minute)
    rate_limit_email: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    rate_limit_sms: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    rate_limit_push: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    rate_limit_in_app: Mapped[int] = mapped_column(Integer, nullable=False, default=500)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant", lazy="noload")
    templates: Mapped[list["Template"]] = relationship("Template", back_populates="tenant", lazy="noload")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="tenant", lazy="noload")
    recipients: Mapped[list["Recipient"]] = relationship("Recipient", back_populates="tenant", lazy="noload")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    # NULL tenant_id = platform admin (not scoped to any tenant)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # UserRole enum value
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tenant: Mapped["Tenant | None"] = relationship(
        "Tenant",
        back_populates="users",
        foreign_keys=[tenant_id],
        primaryjoin="User.tenant_id == Tenant.id",
        lazy="noload",
    )
