from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.tenants.models import Tenant


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(role = 'platform_admin' AND tenant_id IS NULL) "
            "OR (role = 'tenant_admin' AND tenant_id IS NOT NULL)",
            name="ck_user_role_tenant_scope",
        ),
    )

    # NULL tenant_id = platform admin (not scoped to any tenant); enforced
    # together with `role` by ck_user_role_tenant_scope.
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

    tenant: Mapped[Tenant | None] = relationship(
        "Tenant",
        back_populates="users",
        foreign_keys=[tenant_id],
        primaryjoin="User.tenant_id == Tenant.id",
        lazy="noload",
    )
