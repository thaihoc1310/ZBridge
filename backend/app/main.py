import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import (
    activity,
    auth,
    bot,
    customers,
    dashboard,
    health,
    internal_events,
    roles,
    users,
)
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.permissions import ADMIN_ROLE_CODE
from app.core.security import hash_password
from app.db.database import SessionLocal
from app.models import Role, User
from app.services.rbac_service import sync_rbac

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("zbridge")


async def bootstrap() -> None:
    """Mirror the permission catalog, then make sure an admin can log in."""
    async with SessionLocal() as db:
        await sync_rbac(db)
        admin_role = await db.scalar(select(Role).where(Role.code == ADMIN_ROLE_CODE))
        if admin_role is None:
            raise RuntimeError("Vai trò ADMIN không tồn tại sau khi đồng bộ phân quyền.")
        email = settings.initial_admin_email.lower()
        if await db.scalar(select(User.id).where(User.email == email)):
            return
        db.add(
            User(
                email=email,
                full_name="Quản trị hệ thống",
                password_hash=hash_password(settings.initial_admin_password),
                role_id=admin_role.id,
            )
        )
        await db.commit()
        logger.info("INITIAL_ADMIN_CREATED email=%s", email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await bootstrap()
    except Exception:
        logger.exception("BOOTSTRAP_FAILED (run migrations before starting the API)")
    yield


# The interactive docs describe every endpoint, so they stay off in production
# where the app is reachable from the internet.
_docs_enabled = settings.environment != "production"
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(internal_events.router)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(bot.router, prefix=settings.api_prefix)
app.include_router(customers.router, prefix=settings.api_prefix)
app.include_router(activity.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(roles.router, prefix=settings.api_prefix)
