from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import require_platform_admin
from app.common.database import get_db
from app.users.schemas import UserCreate, UserOut
from app.users.service import UserService

router = APIRouter(prefix="/tenants/{tenant_id}/users", tags=["users"])


def _svc(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_tenant_user(
    tenant_id: str,
    body: UserCreate,
    svc: UserService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.create_tenant_admin(tenant_id, body)


@router.get("", response_model=list[UserOut])
async def list_tenant_users(
    tenant_id: str,
    svc: UserService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.list_tenant_users(tenant_id)
