from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models import BotDeliveryLog, Customer, ZaloAccount, ZaloGroup
from app.models.entities import BotStatus, DeliveryStatus
from app.schemas.api import DashboardResponse

router = APIRouter(
    prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=DashboardResponse)
async def dashboard(db: AsyncSession = Depends(get_db)) -> DashboardResponse:
    account = await db.scalar(select(ZaloAccount).order_by(ZaloAccount.created_at).limit(1))
    local_now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
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
            .where(BotDeliveryLog.created_at >= today)
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
    return DashboardResponse(
        bot_status=account.status if account else BotStatus.AUTH_REQUIRED,
        customer_count=customer_count,
        customers_with_debt=customers_with_debt,
        messages_today=messages_today,
        failed_today=failed_today,
        last_sync_at=last_sync,
        last_successful_message_at=last_sent,
    )
