from fastapi import APIRouter
from sqlalchemy import text

from app.db.database import SessionLocal
from app.schemas.api import HealthResponse
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    database = "DOWN"
    gateway = "DOWN"
    zalo = "UNAVAILABLE"
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        database = "UP"
    except Exception:
        pass
    try:
        gateway_health = await zalo_gateway.health()
        gateway = str(gateway_health.get("gateway", "UP"))
        zalo = str(gateway_health.get("zalo", "UNAVAILABLE"))
    except GatewayError:
        pass
    return HealthResponse(api="UP", database=database, zalo_gateway=gateway, zalo=zalo)
