import logging
import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import BotDeliveryLog, Customer, ZaloGroup
from app.models.entities import BotStatus, DeliveryStatus, DeliveryType
from app.schemas.api import DeliveryLogListResponse, DeliveryLogResponse, MessageCreate
from app.services.customer_service import get_customer
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.delivery")


def delivery_response(log: BotDeliveryLog, customer_name: str) -> DeliveryLogResponse:
    return DeliveryLogResponse(
        id=log.id,
        customer_id=log.customer_id,
        customer_name=customer_name,
        type=log.type,
        status=log.status,
        zalo_message_id=log.zalo_message_id,
        error_code=log.error_code,
        error_message=log.error_message,
        created_at=log.created_at,
    )


async def add_delivery_log(
    db: AsyncSession,
    customer_id: uuid.UUID,
    delivery_type: DeliveryType,
    status: DeliveryStatus,
    *,
    zalo_message_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> BotDeliveryLog:
    log = BotDeliveryLog(
        customer_id=customer_id,
        type=delivery_type,
        status=status,
        zalo_message_id=zalo_message_id,
        error_code=error_code,
        error_message=error_message,
    )
    db.add(log)
    await db.flush()
    return log


async def _failed_manual_delivery(
    db: AsyncSession, customer: Customer, code: str, message: str
) -> DeliveryLogResponse:
    log = await add_delivery_log(
        db,
        customer.id,
        DeliveryType.MANUAL_MESSAGE,
        DeliveryStatus.FAILED,
        error_code=code,
        error_message=message,
    )
    await db.commit()
    await db.refresh(log)
    logger.warning("MANUAL_MESSAGE_FAILED customer_id=%s code=%s", customer.id, code)
    return delivery_response(log, customer.group.name)


async def send_customer_message(
    db: AsyncSession, customer_id: uuid.UUID, data: MessageCreate
) -> DeliveryLogResponse:
    customer = await get_customer(db, customer_id)
    content = data.content.strip()
    if not customer.group.is_available:
        return await _failed_manual_delivery(
            db, customer, "GROUP_UNAVAILABLE", "Nhóm Zalo của khách hàng hiện không khả dụng."
        )
    try:
        bot = await zalo_gateway.get_status()
    except GatewayError as exc:
        return await _failed_manual_delivery(db, customer, exc.code, exc.message)

    status = bot.get("status")
    if status == BotStatus.AUTH_REQUIRED.value:
        return await _failed_manual_delivery(
            db, customer, "AUTH_REQUIRED", "Bot cần được đăng nhập lại bằng mã QR."
        )
    if status != BotStatus.CONNECTED.value:
        return await _failed_manual_delivery(
            db, customer, "BOT_DISCONNECTED", "Bot đang mất kết nối. Hãy kết nối lại bot."
        )

    try:
        result = await zalo_gateway.send_text(customer.group.zalo_group_id, content)
        message_id = str(result.get("message_id") or "") or None
        log = await add_delivery_log(
            db,
            customer.id,
            DeliveryType.MANUAL_MESSAGE,
            DeliveryStatus.SENT,
            zalo_message_id=message_id,
        )
    except GatewayError as exc:
        return await _failed_manual_delivery(db, customer, exc.code, exc.message)

    await db.commit()
    await db.refresh(log)
    logger.info("MANUAL_MESSAGE_SENT customer_id=%s log_id=%s", customer.id, log.id)
    return delivery_response(log, customer.group.name)


async def list_delivery_logs(
    db: AsyncSession,
    search: str | None,
    status: DeliveryStatus | None,
    today: bool,
    page: int,
    limit: int,
) -> DeliveryLogListResponse:
    filters = []
    if search:
        needle = f"%{search.strip()}%"
        filters.append(
            or_(
                BotDeliveryLog.customer.has(Customer.group.has(ZaloGroup.name.ilike(needle))),
                BotDeliveryLog.error_code.ilike(needle),
                BotDeliveryLog.error_message.ilike(needle),
            )
        )
    if status:
        filters.append(BotDeliveryLog.status == status)
    if today:
        from zoneinfo import ZoneInfo

        local_now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        filters.append(BotDeliveryLog.created_at >= local_start.astimezone(UTC))

    count_stmt = select(func.count()).select_from(BotDeliveryLog).where(*filters)
    total = int(await db.scalar(count_stmt) or 0)
    logs = list(
        (
            await db.scalars(
                select(BotDeliveryLog)
                .options(
                    selectinload(BotDeliveryLog.customer).selectinload(Customer.group)
                )
                .where(*filters)
                .order_by(BotDeliveryLog.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    return DeliveryLogListResponse(
        items=[delivery_response(log, log.customer.group.name) for log in logs],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)),
    )
