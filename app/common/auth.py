from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import settings
from app.common.database import get_db
from app.common.enums import UserRole
from app.common.exceptions import ForbiddenError, UnauthorizedError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, role: str, tenant_id: str | None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "role": role, "tenant_id": tenant_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    # Import here to avoid circular import (auth ↔ tenants/models)
    from app.tenants.models import User

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise UnauthorizedError()
    except JWTError:
        raise UnauthorizedError()

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError()
    return user


async def require_platform_admin(current_user=Depends(get_current_user)):
    if current_user.role != UserRole.PLATFORM_ADMIN:
        raise ForbiddenError("Platform admin access required")
    return current_user


async def require_tenant_admin(current_user=Depends(get_current_user)):
    if current_user.role not in (UserRole.PLATFORM_ADMIN, UserRole.TENANT_ADMIN):
        raise ForbiddenError("Tenant admin access required")
    return current_user
