from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.database import Base
from app.common.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.tenants.models import Tenant


class Template(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tenant-defined notification template.

    Body text uses {{variable_name}} placeholders.  The `variables` column
    stores the list of expected variable names so the API can validate
    substitution completeness before dispatch.
    """

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "channel", name="uq_template_tenant_name_channel"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # Channel enum value

    # Email-only; ignored for other channels
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Template body; may contain {{variable}} placeholders
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # JSON array of expected variable names, e.g. ["first_name", "otp_code"]
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="templates", lazy="noload")
