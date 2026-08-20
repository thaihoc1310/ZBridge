from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.errors import AppError
from app.core.permissions import BOT_CONNECT, BOT_DISCONNECT, BOT_READ
from app.db.database import get_db
from app.models import User
from app.schemas.api import BotStatusResponse, QRResponse
from app.services.bot_service import refresh_bot_status
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/status", response_model=BotStatusResponse)
async def status(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(BOT_READ)),
) -> BotStatusResponse:
    return await refresh_bot_status(db)


async def gateway_action(action: str) -> dict:
    try:
        return await getattr(zalo_gateway, action)()
    except GatewayError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc


@router.post("/connect", response_model=QRResponse)
async def connect(_actor: User = Depends(require_permission(BOT_CONNECT))) -> dict:
    return await gateway_action("connect")


@router.get("/qr", response_model=QRResponse)
async def qr(_actor: User = Depends(require_permission(BOT_CONNECT))) -> dict:
    return await gateway_action("get_qr")


@router.post("/reconnect")
async def reconnect(_actor: User = Depends(require_permission(BOT_CONNECT))) -> dict:
    return await gateway_action("reconnect")


@router.post("/disconnect")
async def disconnect(_actor: User = Depends(require_permission(BOT_DISCONNECT))) -> dict:
    return await gateway_action("disconnect")
