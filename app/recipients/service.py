from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.enums import Channel
from app.common.exceptions import ConflictError, NotFoundError
from app.recipients.models import Recipient, RecipientChannelAddress
from app.recipients.schemas import RecipientCreate, RecipientUpdate


class RecipientService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, tenant_id: str, data: RecipientCreate) -> Recipient:
        conflict = await self.db.execute(
            select(Recipient).where(
                Recipient.tenant_id == tenant_id, Recipient.external_key == data.external_key
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise ConflictError("A recipient with this external_key already exists")

        recipient = Recipient(
            tenant_id=tenant_id,
            external_key=data.external_key,
            display_name=data.display_name,
        )
        self.db.add(recipient)
        await self.db.flush()

        for addr in data.addresses:
            self.db.add(
                RecipientChannelAddress(
                    recipient_id=recipient.id,
                    tenant_id=tenant_id,
                    channel=addr.channel.value,
                    address=addr.address,
                )
            )
        await self.db.flush()
        # channel_addresses uses lazy="noload" (consistent with the rest of
        # the codebase) — session.refresh() won't populate a noload
        # relationship, so re-fetch with the same selectinload as get_by_id.
        return await self.get_by_id(tenant_id, recipient.id)

    async def get_by_id(self, tenant_id: str, recipient_id: str) -> Recipient:
        result = await self.db.execute(
            select(Recipient)
            .where(Recipient.id == recipient_id, Recipient.tenant_id == tenant_id)
            .options(selectinload(Recipient.channel_addresses))
        )
        recipient = result.scalar_one_or_none()
        if recipient is None:
            raise NotFoundError(f"Recipient '{recipient_id}' not found")
        return recipient

    async def list_all(self, tenant_id: str) -> list[Recipient]:
        result = await self.db.execute(
            select(Recipient)
            .where(Recipient.tenant_id == tenant_id)
            .options(selectinload(Recipient.channel_addresses))
            .order_by(Recipient.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, tenant_id: str, recipient_id: str, data: RecipientUpdate) -> Recipient:
        # get_by_id already eager-loads channel_addresses via selectinload;
        # update() only touches scalar fields so no re-fetch is needed.
        recipient = await self.get_by_id(tenant_id, recipient_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(recipient, field, value)
        await self.db.flush()
        return recipient

    async def delete(self, tenant_id: str, recipient_id: str) -> None:
        recipient = await self.get_by_id(tenant_id, recipient_id)
        await self.db.delete(recipient)
        await self.db.flush()

    async def upsert_address(
        self, tenant_id: str, recipient_id: str, channel: Channel, address: str
    ) -> RecipientChannelAddress:
        await self.get_by_id(tenant_id, recipient_id)  # 404 + tenant scoping

        result = await self.db.execute(
            select(RecipientChannelAddress).where(
                RecipientChannelAddress.recipient_id == recipient_id,
                RecipientChannelAddress.channel == channel.value,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.address = address
            await self.db.flush()
            return existing

        new_addr = RecipientChannelAddress(
            recipient_id=recipient_id,
            tenant_id=tenant_id,
            channel=channel.value,
            address=address,
        )
        self.db.add(new_addr)
        await self.db.flush()
        return new_addr

    async def delete_address(self, tenant_id: str, recipient_id: str, channel: Channel) -> None:
        await self.get_by_id(tenant_id, recipient_id)  # 404 + tenant scoping

        result = await self.db.execute(
            select(RecipientChannelAddress).where(
                RecipientChannelAddress.recipient_id == recipient_id,
                RecipientChannelAddress.channel == channel.value,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise NotFoundError(f"No {channel.value} address registered for this recipient")
        await self.db.delete(existing)
        await self.db.flush()
