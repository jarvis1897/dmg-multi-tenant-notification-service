from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Channel


class ChannelAddressIn(BaseModel):
    channel: Channel
    address: str = Field(..., min_length=1, max_length=500)


class ChannelAddressUpsert(BaseModel):
    address: str = Field(..., min_length=1, max_length=500)


class ChannelAddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel: str
    address: str
    created_at: datetime
    updated_at: datetime


class RecipientCreate(BaseModel):
    external_key: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    addresses: list[ChannelAddressIn] = Field(default_factory=list)


class RecipientUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    external_key: str
    display_name: str | None
    created_at: datetime
    updated_at: datetime
    channel_addresses: list[ChannelAddressOut] = Field(default_factory=list)
