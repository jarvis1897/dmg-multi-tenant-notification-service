from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import get_current_tenant_id, get_current_user
from app.common.database import get_db
from app.notifications.schemas import NotificationRequestCreate, NotificationRequestOut
from app.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _svc(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.post("", response_model=NotificationRequestOut, status_code=status.HTTP_201_CREATED)
async def create_notification(
    body: NotificationRequestCreate,
    svc: NotificationService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
    current_user=Depends(get_current_user),
):
    notification_request = await svc.create(tenant_id, body, created_by=current_user.id)
    counts = await svc.get_delivery_attempt_counts(notification_request)

    out = NotificationRequestOut.model_validate(notification_request)
    for ch in out.notification_channels:
        ch.delivery_attempt_count = counts.get(ch.id, 0)
    return out
