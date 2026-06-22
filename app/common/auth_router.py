from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth import create_access_token, hash_password, verify_password
from app.common.database import get_db
from app.common.enums import UserRole
from app.common.exceptions import UnauthorizedError

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    from app.tenants.models import User

    result = await db.execute(
        select(User).where(User.email == form.username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise UnauthorizedError("Incorrect email or password")

    return TokenOut(access_token=create_access_token(user.id, user.role, user.tenant_id))


@router.post("/register/platform-admin", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def bootstrap_platform_admin(
    body: RegisterIn,
    db: AsyncSession = Depends(get_db),
):
    """
    One-time bootstrap endpoint: creates the first platform admin.
    Returns 403 once any platform admin exists.
    """
    from app.tenants.models import User

    existing = await db.execute(
        select(User).where(User.role == UserRole.PLATFORM_ADMIN)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin already exists. Use /auth/login.",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        role=UserRole.PLATFORM_ADMIN,
        tenant_id=None,
    )
    db.add(user)
    await db.flush()
    return TokenOut(access_token=create_access_token(user.id, user.role, user.tenant_id))
