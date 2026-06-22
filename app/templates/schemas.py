from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Channel


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    channel: Channel
    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(..., min_length=1)
    variables: list[str] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    # name/channel are the natural key together — not mutable after creation.
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, min_length=1)
    variables: list[str] | None = None
    is_active: bool | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    description: str | None
    channel: str
    subject: str | None
    body: str
    variables: list[str]
    is_active: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime
