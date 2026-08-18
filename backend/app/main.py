import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import activity, auth, bot, customers, dashboard, health, internal_events
from app.core.config import settings
from app.core.errors import AppError, app_error_handler
from app.core.security import hash_password
from app.db.database import SessionLocal
from app.models import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("zbridge")


async def seed_admin() -> None:
    async with SessionLocal() as db:
        existing = await db.scalar(
            select(User).where(User.email == settings.initial_admin_email.lower())
        )
        if existing:
            return
        db.add(
            User(
                email=settings.initial_admin_email.lower(),
                password_hash=hash_password(settings.initial_admin_password),
            )
        )
        await db.commit()
        logger.info("INITIAL_ADMIN_CREATED email=%s", settings.initial_admin_email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await seed_admin()
    except Exception:
        logger.exception("INITIAL_ADMIN_SEED_FAILED (run migrations before starting the API)")
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
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
