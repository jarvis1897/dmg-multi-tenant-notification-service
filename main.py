import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.channel_configs.router import router as channel_configs_router
from app.common.auth_router import router as auth_router
from app.common.database import AsyncSessionLocal
from app.delivery import engine as dispatch_engine
from app.notifications.router import router as notifications_router
from app.recipients.router import router as recipients_router
from app.templates.router import router as templates_router
from app.tenants.router import router as tenants_router
from app.users.router import router as users_router


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run in a thread: alembic internally calls asyncio.run(), which requires
    # no running loop in the calling thread.
    await asyncio.to_thread(_run_migrations)
    await dispatch_engine.start()
    yield
    await dispatch_engine.stop()


app = FastAPI(
    title="Multi-tenant Notification Service",
    description="Async notification dispatch across email, SMS, push, and in-app channels.",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(templates_router)
app.include_router(recipients_router)
app.include_router(channel_configs_router)
app.include_router(notifications_router)


@app.get("/health", tags=["meta"])
async def health():
    """Liveness check with a DB round-trip."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))
    return {"status": "ok"}
