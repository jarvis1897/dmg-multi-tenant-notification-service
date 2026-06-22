from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import hash_password
from app.common.enums import UserRole
from app.common.exceptions import ConflictError, NotFoundError
from app.tenants.models import Tenant
from app.users.models import User
from app.users.schemas import UserCreate


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_tenant_admin(self, tenant_id: str, data: UserCreate) -> User:
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        if result.scalar_one_or_none() is None:
            raise NotFoundError(f"Tenant '{tenant_id}' not found")

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
        result = await self.db.execute(
            select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.desc())
        )
        return list(result.scalars().all())
