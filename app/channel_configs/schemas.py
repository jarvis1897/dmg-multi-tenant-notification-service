from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChannelConfigUpsert(BaseModel):
    is_enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    channel: str
    is_enabled: bool
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
