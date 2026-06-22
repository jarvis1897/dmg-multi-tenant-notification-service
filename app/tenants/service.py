import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import hash_password
from app.common.enums import UserRole
from app.common.exceptions import ConflictError, NotFoundError
from app.tenants.models import Tenant, User
from app.tenants.schemas import TenantCreate, TenantUpdate, UserCreate


class TenantService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: TenantCreate) -> tuple[Tenant, str]:
        conflict = await self.db.execute(
            select(Tenant).where(
                (Tenant.slug == data.slug) | (Tenant.name == data.name)
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise ConflictError("Tenant with this name or slug already exists")

        raw_key = secrets.token_urlsafe(32)
        tenant = Tenant(
            name=data.name,
            slug=data.slug,
            api_key_hash=hash_password(raw_key),
            max_notifications_per_day=data.max_notifications_per_day,
            rate_limit_email=data.rate_limit_email,
            rate_limit_sms=data.rate_limit_sms,
            rate_limit_push=data.rate_limit_push,
            rate_limit_in_app=data.rate_limit_in_app,
        )
        self.db.add(tenant)
        await self.db.flush()
        return tenant, raw_key

    async def get_by_id(self, tenant_id: str) -> Tenant:
        result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise NotFoundError(f"Tenant '{tenant_id}' not found")
        return tenant

    async def list_all(self) -> list[Tenant]:
        result = await self.db.execute(
            select(Tenant).order_by(Tenant.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, tenant_id: str, data: TenantUpdate) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(tenant, field, value)
        await self.db.flush()
        return tenant

    # --- Tenant user management ---

    async def create_tenant_user(self, tenant_id: str, data: UserCreate) -> User:
        await self.get_by_id(tenant_id)  # 404 if tenant doesn't exist

        existing = await self.db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A user with this email already exists")

        user = User(
            tenant_id=tenant_id,
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRole.TENANT_ADMIN,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def list_tenant_users(self, tenant_id: str) -> list[User]:
        await self.get_by_id(tenant_id)
        result = await self.db.execute(
            select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.desc())
        )
        return list(result.scalars().all())
