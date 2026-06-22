from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import require_platform_admin
from app.common.database import get_db
from app.tenants.schemas import TenantCreate, TenantCreateOut, TenantOut, TenantUpdate, UserCreate, UserOut
from app.tenants.service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _svc(db: AsyncSession = Depends(get_db)) -> TenantService:
    return TenantService(db)


@router.post("", response_model=TenantCreateOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    tenant, raw_key = await svc.create(body)
    return TenantCreateOut(**TenantOut.model_validate(tenant).model_dump(), api_key=raw_key)


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.list_all()


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: str,
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.get_by_id(tenant_id)


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.update(tenant_id, body)


# --- Tenant user management (platform admin only) ---

@router.post("/{tenant_id}/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_tenant_user(
    tenant_id: str,
    body: UserCreate,
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.create_tenant_user(tenant_id, body)


@router.get("/{tenant_id}/users", response_model=list[UserOut])
async def list_tenant_users(
    tenant_id: str,
    svc: TenantService = Depends(_svc),
    _=Depends(require_platform_admin),
):
    return await svc.list_tenant_users(tenant_id)
