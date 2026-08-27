from fastapi import APIRouter, Response
from sqlalchemy import text

from app.db.database import SessionLocal
from app.schemas.api import HealthResponse
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

router = APIRouter(tags=["health"])


async def _database_reachable() -> bool:
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Human-facing detail view; always 200 so a partial outage is still readable."""
    gateway = "DOWN"
    zalo = "UNAVAILABLE"
    listener_status = None
    events_healthy = False
    events_caught_up = True
    event_backlog = 0
    event_backlog_age_ms: int | None = None
    database = "UP" if await _database_reachable() else "DOWN"
    try:
        gateway_health = await zalo_gateway.health()
        gateway = str(gateway_health.get("gateway", "UP"))
        zalo = str(gateway_health.get("zalo", "UNAVAILABLE"))
        listener_status = str(gateway_health.get("listener") or "") or None
        events_healthy = bool(gateway_health.get("events_healthy", False))
        events_caught_up = bool(gateway_health.get("events_caught_up", True))
        event_backlog = int(gateway_health.get("event_backlog") or 0)
        raw_age = gateway_health.get("event_backlog_age_ms")
        event_backlog_age_ms = int(raw_age) if raw_age is not None else None
    except GatewayError:
        pass
    return HealthResponse(
        api="UP",
        database=database,
        zalo_gateway=gateway,
        zalo=zalo,
        listener_status=listener_status,
        events_healthy=events_healthy,
        events_caught_up=events_caught_up,
        event_backlog=event_backlog,
        event_backlog_age_ms=event_backlog_age_ms,
    )


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    """Liveness: deliberately checks nothing external.

    Restarting the API because the database blipped would turn a recoverable
    outage into a restart loop.
    """
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
async def ready(response: Response) -> dict[str, str]:
    """Readiness: fail out of the load balancer while the database is unreachable."""
    if not await _database_reachable():
        response.status_code = 503
        return {"status": "unready", "database": "DOWN"}
    return {"status": "ready", "database": "UP"}
