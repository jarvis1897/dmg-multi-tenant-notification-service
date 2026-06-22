from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import get_current_tenant_id, get_current_user
from app.common.database import get_db
from app.templates.schemas import TemplateCreate, TemplateOut, TemplateUpdate
from app.templates.service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


def _svc(db: AsyncSession = Depends(get_db)) -> TemplateService:
    return TemplateService(db)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    svc: TemplateService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
    current_user=Depends(get_current_user),
):
    return await svc.create(tenant_id, body, created_by=current_user.id)


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    svc: TemplateService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.list_all(tenant_id)


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: str,
    svc: TemplateService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.get_by_id(tenant_id, template_id)


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    svc: TemplateService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    return await svc.update(tenant_id, template_id, body)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    svc: TemplateService = Depends(_svc),
    tenant_id: str = Depends(get_current_tenant_id),
):
    await svc.delete(tenant_id, template_id)
