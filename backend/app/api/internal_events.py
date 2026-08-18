import secrets

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.db.database import get_db
from app.schemas.api import IncomingEventResponse, IncomingGroupMessage
from app.services.mention_automation_service import schedule_from_incoming_event

router = APIRouter(prefix="/internal/zalo", tags=["internal"])


@router.post("/events", response_model=IncomingEventResponse, include_in_schema=False)
async def receive_zalo_event(
    event: IncomingGroupMessage,
    event_secret: str | None = Header(default=None, alias="X-Zalo-Event-Secret"),
    db: AsyncSession = Depends(get_db),
) -> IncomingEventResponse:
    if event_secret is None or not secrets.compare_digest(event_secret, settings.zalo_event_secret):
        raise AppError("UNAUTHORIZED", "Invalid event secret.", 401)
    return await schedule_from_incoming_event(db, event)
