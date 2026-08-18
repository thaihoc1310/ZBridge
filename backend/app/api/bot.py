from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.db.database import get_db
from app.schemas.api import BotStatusResponse, QRResponse
from app.services.bot_service import refresh_bot_status
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

router = APIRouter(prefix="/bot", tags=["bot"], dependencies=[Depends(get_current_user)])


@router.get("/status", response_model=BotStatusResponse)
async def status(db: AsyncSession = Depends(get_db)) -> BotStatusResponse:
    return await refresh_bot_status(db)


async def gateway_action(action: str) -> dict:
    try:
        return await getattr(zalo_gateway, action)()
    except GatewayError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc


@router.post("/connect", response_model=QRResponse)
async def connect() -> dict:
    return await gateway_action("connect")


@router.get("/qr", response_model=QRResponse)
async def qr() -> dict:
    return await gateway_action("get_qr")


@router.post("/reconnect")
async def reconnect() -> dict:
    return await gateway_action("reconnect")


@router.post("/disconnect")
async def disconnect() -> dict:
    return await gateway_action("disconnect")
