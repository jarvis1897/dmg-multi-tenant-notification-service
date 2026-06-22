from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Channel


class NotificationRequestCreate(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=255)
    channels: list[Channel] = Field(..., min_length=1)
    recipient_ids: list[str] = Field(..., min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)


class NotificationChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel: str
    template_id: str | None
    rendered_subject: str | None
    rendered_body: str
    status: str
    skipped_recipients: dict[str, str]
    delivery_attempt_count: int = 0
    created_at: datetime
    updated_at: datetime


class NotificationRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    template_name: str
    channels: list[str]
    recipient_ids: list[str]
    variables: dict[str, Any]
    scheduled_at: datetime | None
    status: str
    idempotency_key: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    notification_channels: list[NotificationChannelOut] = Field(default_factory=list)
