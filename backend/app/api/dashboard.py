from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import DASHBOARD_READ
from app.db.database import get_db
from app.models import BotDeliveryLog, Customer, User, ZaloAccount, ZaloGroup
from app.models.entities import BotStatus, DeliveryStatus
from app.schemas.api import DashboardHourlyMessages, DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DASHBOARD_READ)),
) -> DashboardResponse:
    account = await db.scalar(select(ZaloAccount).order_by(ZaloAccount.created_at).limit(1))
    local_now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    tomorrow = today + timedelta(days=1)
    customer_count = int(await db.scalar(select(func.count()).select_from(Customer)) or 0)
    customers_with_debt = int(
        await db.scalar(
            select(func.count()).select_from(Customer).where(Customer.has_debt.is_(True))
        )
        or 0
    )
    messages_today = int(
        await db.scalar(
            select(func.count())
            .select_from(BotDeliveryLog)
            .where(
                BotDeliveryLog.created_at >= today,
                BotDeliveryLog.created_at < tomorrow,
                BotDeliveryLog.status == DeliveryStatus.SENT,
            )
        )
        or 0
    )
    failed_today = int(
        await db.scalar(
            select(func.count())
            .select_from(BotDeliveryLog)
            .where(
                BotDeliveryLog.created_at >= today,
                BotDeliveryLog.status == DeliveryStatus.FAILED,
            )
        )
        or 0
    )
    last_sync = await db.scalar(select(func.max(ZaloGroup.last_synced_at)))
    last_sent = await db.scalar(
        select(func.max(BotDeliveryLog.created_at)).where(
            BotDeliveryLog.status == DeliveryStatus.SENT
        )
    )
    sent_timestamps = (
        await db.scalars(
            select(BotDeliveryLog.created_at).where(
                BotDeliveryLog.created_at >= today,
                BotDeliveryLog.created_at < tomorrow,
                BotDeliveryLog.status == DeliveryStatus.SENT,
            )
        )
    ).all()
    messages_by_hour = [0] * 24
    local_timezone = ZoneInfo("Asia/Ho_Chi_Minh")
    for sent_at in sent_timestamps:
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        messages_by_hour[sent_at.astimezone(local_timezone).hour] += 1

    return DashboardResponse(
        bot_status=account.status if account else BotStatus.AUTH_REQUIRED,
        customer_count=customer_count,
        customers_with_debt=customers_with_debt,
        customers_without_debt=max(0, customer_count - customers_with_debt),
        messages_today=messages_today,
        messages_by_hour=[
            DashboardHourlyMessages(hour=hour, count=count)
            for hour, count in enumerate(messages_by_hour)
        ],
        failed_today=failed_today,
        last_sync_at=last_sync,
        last_successful_message_at=last_sent,
    )
