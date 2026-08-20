import secrets

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.db.database import get_db
from app.schemas.api import GatewayAlert, IncomingEventResponse, IncomingGroupMessage
from app.services.alerting import report_async
from app.services.mention_automation_service import schedule_from_incoming_event

router = APIRouter(prefix="/internal/zalo", tags=["internal"])


def _secret_matches(provided: str | None, expected: str) -> bool:
    # compare_digest raises TypeError on non-ASCII str input, so compare bytes.
    if not provided:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


@router.post("/events", response_model=IncomingEventResponse, include_in_schema=False)
async def receive_zalo_event(
    event: IncomingGroupMessage,
    event_secret: str | None = Header(default=None, alias="X-Zalo-Event-Secret"),
    db: AsyncSession = Depends(get_db),
) -> IncomingEventResponse:
    if not _secret_matches(event_secret, settings.zalo_event_secret):
        raise AppError("UNAUTHORIZED", "Invalid event secret.", 401)
    return await schedule_from_incoming_event(db, event)


@router.post("/alerts", status_code=202, include_in_schema=False)
async def receive_gateway_alert(
    alert: GatewayAlert,
    event_secret: str | None = Header(default=None, alias="X-Zalo-Event-Secret"),
) -> dict[str, str]:
    """Relay gateway problems into the same alert pipeline the backend uses."""
    if not _secret_matches(event_secret, settings.zalo_event_secret):
        raise AppError("UNAUTHORIZED", "Invalid event secret.", 401)
    await report_async(
        alert.code,
        alert.message,
        severity=alert.severity,
        service="zalo-gateway",
        context=alert.context,
    )
    return {"status": "queued"}
