from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alerts import Severity
from app.models import ZaloAccount, ZaloGroup
from app.models.entities import BotStatus
from app.schemas.api import BotStatusResponse
from app.services.alerting import report_async
from app.services.zalo_gateway_client import GatewayError, zalo_gateway


async def get_or_create_account(db: AsyncSession) -> ZaloAccount:
    account = await db.scalar(select(ZaloAccount).order_by(ZaloAccount.created_at).limit(1))
    if account:
        return account
    account = ZaloAccount(status=BotStatus.AUTH_REQUIRED)
    db.add(account)
    await db.flush()
    return account


async def refresh_bot_status(db: AsyncSession) -> BotStatusResponse:
    account = await get_or_create_account(db)
    now = datetime.now(UTC)
    listener_status: str | None = None
    events_healthy = False
    try:
        gateway_status = await zalo_gateway.get_status()
        raw_status = gateway_status.get("status", "ERROR")
        listener_status = gateway_status.get("listener_status")
        events_healthy = bool(gateway_status.get("events_healthy", False))
        account.status = BotStatus(raw_status)
        account.zalo_user_id = gateway_status.get("zalo_user_id") or account.zalo_user_id
        account.display_name = gateway_status.get("account_name") or account.display_name
        account.avatar_url = gateway_status.get("avatar_url") or account.avatar_url
        account.last_health_check_at = now
        account.last_error = gateway_status.get("last_error")
        if account.status == BotStatus.CONNECTED and account.last_connected_at is None:
            account.last_connected_at = now
    except (GatewayError, ValueError) as exc:
        account.status = BotStatus.ERROR
        account.last_health_check_at = now
        account.last_error = getattr(exc, "message", str(exc))
        await report_async(
            "ZALO_GATEWAY_UNREACHABLE",
            f"Không lấy được trạng thái bot Zalo: {account.last_error}",
            severity=Severity.ERROR,
        )
    await db.commit()
    group_count = await db.scalar(
        select(func.count()).select_from(ZaloGroup).where(ZaloGroup.is_available.is_(True))
    )
    return BotStatusResponse(
        status=account.status,
        account_name=account.display_name,
        zalo_user_id=account.zalo_user_id,
        avatar_url=account.avatar_url,
        group_count=group_count or 0,
        session_active=account.status in {BotStatus.CONNECTED, BotStatus.CONNECTING},
        last_connected_at=account.last_connected_at,
        last_health_check_at=account.last_health_check_at,
        last_error=account.last_error,
        listener_status=listener_status,
        events_healthy=events_healthy,
    )
