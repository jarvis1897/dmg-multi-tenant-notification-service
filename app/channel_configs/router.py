from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_configs.schemas import ChannelConfigOut, ChannelConfigUpsert
from app.channel_configs.service import ChannelConfigService
from app.common.auth import get_current_tenant_id
from app.common.database import get_db
from app.common.enums import Channel

router = APIRouter(prefix="/channel-configs", tags=["channel-configs"])


def _svc(db: AsyncSession = Depends(get_db)) -> ChannelConfigService:
    return ChannelConfigService(db)


@router.get("", response_model=list[ChannelConfigOut])
async def list_channel_configs(
    svc: ChannelConfigService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.list_all(tenant_id)


@router.get("/{channel}", response_model=ChannelConfigOut)
async def get_channel_config(
    channel: Channel,
    svc: ChannelConfigService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.get(tenant_id, channel)


@router.put("/{channel}", response_model=ChannelConfigOut)
async def upsert_channel_config(
    channel: Channel,
    body: ChannelConfigUpsert,
    svc: ChannelConfigService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.upsert(tenant_id, channel, body)


@router.delete("/{channel}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel_config(
    channel: Channel,
    svc: ChannelConfigService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    await svc.delete(tenant_id, channel)
