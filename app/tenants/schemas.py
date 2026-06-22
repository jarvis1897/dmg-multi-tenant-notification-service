from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    max_notifications_per_day: int = Field(default=10_000, ge=1)
    rate_limit_email: int = Field(default=100, ge=0)
    rate_limit_sms: int = Field(default=50, ge=0)
    rate_limit_push: int = Field(default=200, ge=0)
    rate_limit_in_app: int = Field(default=500, ge=0)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    max_notifications_per_day: int | None = Field(default=None, ge=1)
    rate_limit_email: int | None = Field(default=None, ge=0)
    rate_limit_sms: int | None = Field(default=None, ge=0)
    rate_limit_push: int | None = Field(default=None, ge=0)
    rate_limit_in_app: int | None = Field(default=None, ge=0)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    is_active: bool
    max_notifications_per_day: int
    rate_limit_email: int
    rate_limit_sms: int
    rate_limit_push: int
    rate_limit_in_app: int
    created_at: datetime
    updated_at: datetime


class TenantCreateOut(TenantOut):
    # Raw API key — shown exactly once at creation; not stored in plaintext
    api_key: str
