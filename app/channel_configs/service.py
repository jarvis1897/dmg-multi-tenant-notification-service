from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_configs.models import ChannelConfig
from app.channel_configs.schemas import ChannelConfigUpsert
from app.common.enums import Channel
from app.common.exceptions import NotFoundError


class ChannelConfigService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self, tenant_id: str) -> list[ChannelConfig]:
        result = await self.db.execute(
            select(ChannelConfig).where(ChannelConfig.tenant_id == tenant_id).order_by(ChannelConfig.channel)
        )
        return list(result.scalars().all())

    async def get(self, tenant_id: str, channel: Channel) -> ChannelConfig:
        result = await self.db.execute(
            select(ChannelConfig).where(
                ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel == channel.value
            )
        )
        config = result.scalar_one_or_none()
        if config is None:
            raise NotFoundError(f"No config found for channel '{channel.value}'")
        return config

    async def upsert(self, tenant_id: str, channel: Channel, data: ChannelConfigUpsert) -> ChannelConfig:
        result = await self.db.execute(
            select(ChannelConfig).where(
                ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel == channel.value
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.is_enabled = data.is_enabled
            existing.config = data.config
            await self.db.flush()
            return existing

        config = ChannelConfig(
            tenant_id=tenant_id,
            channel=channel.value,
            is_enabled=data.is_enabled,
            config=data.config,
        )
        self.db.add(config)
        await self.db.flush()
        return config

    async def delete(self, tenant_id: str, channel: Channel) -> None:
        config = await self.get(tenant_id, channel)
        await self.db.delete(config)
        await self.db.flush()
