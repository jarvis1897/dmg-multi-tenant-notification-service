from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import get_current_tenant_id
from app.common.database import get_db
from app.common.enums import Channel
from app.recipients.schemas import (
    ChannelAddressOut,
    ChannelAddressUpsert,
    RecipientCreate,
    RecipientOut,
    RecipientUpdate,
)
from app.recipients.service import RecipientService

router = APIRouter(prefix="/recipients", tags=["recipients"])


def _svc(db: AsyncSession = Depends(get_db)) -> RecipientService:
    return RecipientService(db)


@router.post("", response_model=RecipientOut, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    body: RecipientCreate,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.create(tenant_id, body)


@router.get("", response_model=list[RecipientOut])
async def list_recipients(
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.list_all(tenant_id)


@router.get("/{recipient_id}", response_model=RecipientOut)
async def get_recipient(
    recipient_id: str,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.get_by_id(tenant_id, recipient_id)


@router.patch("/{recipient_id}", response_model=RecipientOut)
async def update_recipient(
    recipient_id: str,
    body: RecipientUpdate,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.update(tenant_id, recipient_id, body)


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(
    recipient_id: str,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    await svc.delete(tenant_id, recipient_id)


@router.put("/{recipient_id}/addresses/{channel}", response_model=ChannelAddressOut)
async def upsert_address(
    recipient_id: str,
    channel: Channel,
    body: ChannelAddressUpsert,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.upsert_address(tenant_id, recipient_id, channel, body.address)


@router.delete("/{recipient_id}/addresses/{channel}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    recipient_id: str,
    channel: Channel,
    svc: RecipientService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    await svc.delete_address(tenant_id, recipient_id, channel)
