import calendar
import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from lunar_vn import solar_to_lunar
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import Customer, DebtReminderAutomation, DebtReminderRun
from app.models.entities import DebtReminderStatus
from app.schemas.api import (
    DebtReminderResponse,
    DebtReminderTriggerResponse,
    DebtReminderUpdate,
)

logger = logging.getLogger("zbridge.debt_reminder_service")
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SOLAR_DEBT_REMINDER_BLACKOUTS = {(1, 1), (4, 30), (5, 1), (9, 2)}
DEFAULT_MESSAGE_PARTS = [
    {"type": "text", "text": "Vui lòng thanh toán công nợ giúp mình nhé."}
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_debt_reminder_blackout(value: date) -> bool:
    """Return whether a Vietnam-local date is excluded from debt reminders.

    Fixed solar holidays are excluded. In the lunar calendar, the first six
    days of every month, ngày rằm and Giỗ Tổ Hùng Vương (10/03) are excluded.
    The longer Tết break runs continuously from 28 tháng Chạp through the end
    of tháng Giêng; combined with the monthly rule, reminders resume on mùng 7
    tháng Hai.
    """
    if (value.month, value.day) in SOLAR_DEBT_REMINDER_BLACKOUTS:
        return True
    lunar = solar_to_lunar(value)
    in_tet_break = (lunar.month == 12 and lunar.day >= 28) or lunar.month == 1
    return (
        in_tet_break
        or 1 <= lunar.day <= 6
        or lunar.day == 15
        or (lunar.month, lunar.day) == (3, 10)
    )


def defer_debt_reminder(value: datetime) -> datetime:
    """Move a reminder to the first allowed following local day."""
    local_value = _as_utc(value).astimezone(LOCAL_TIMEZONE)
    while is_debt_reminder_blackout(local_value.date()):
        local_value = datetime.combine(
            local_value.date() + timedelta(days=1),
            local_value.timetz().replace(tzinfo=None),
            tzinfo=LOCAL_TIMEZONE,
        )
    return local_value.astimezone(UTC)


def next_monthly_run(
    day_of_month: int,
    send_time: time,
    *,
    now: datetime | None = None,
) -> datetime:
    local_now = _as_utc(now or datetime.now(UTC)).astimezone(LOCAL_TIMEZONE)
    year, month = local_now.year, local_now.month
    for _ in range(2):
        last_day = calendar.monthrange(year, month)[1]
        candidate = datetime.combine(
            date(year, month, min(day_of_month, last_day)),
            send_time,
            tzinfo=LOCAL_TIMEZONE,
        )
        candidate = defer_debt_reminder(candidate).astimezone(LOCAL_TIMEZONE)
        if candidate > local_now:
            return candidate.astimezone(UTC)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    raise RuntimeError("Could not calculate the next debt reminder run")


def next_debt_reminder_run(
    day_of_month: int,
    send_time: time,
    repeat_interval_days: int,
    scheduled_for: datetime,
    *,
    repeat_enabled: bool = True,
    has_debt: bool,
    now: datetime | None = None,
) -> datetime:
    """Next moment this customer should be reminded, never a moment already past.

    Missed occurrences are skipped rather than replayed: after an outage longer
    than the repeat interval, advancing purely from ``scheduled_for`` would leave
    ``next_run_at`` in the past, so every beat tick would create another run and
    the customer would receive a burst of reminders a minute apart.
    """
    scheduled_for = _as_utc(scheduled_for)
    reference = _as_utc(now or datetime.now(UTC))
    monthly_anchor = next_monthly_run(
        day_of_month, send_time, now=max(scheduled_for, reference)
    )
    if not has_debt or not repeat_enabled:
        return monthly_anchor
    step = timedelta(days=repeat_interval_days)
    repeated_run = defer_debt_reminder(scheduled_for + step)
    # A lunar deferral becomes the anchor for the next interval. Iterate instead
    # of arithmetically skipping missed slots so a 7 -> 8 shift yields 8 -> 11.
    while repeated_run <= reference:
        repeated_run = defer_debt_reminder(repeated_run + step)
    return min(repeated_run, monthly_anchor)


async def _latest_run(
    db: AsyncSession, automation_id: uuid.UUID
) -> DebtReminderRun | None:
    return await db.scalar(
        select(DebtReminderRun)
        .where(DebtReminderRun.automation_id == automation_id)
        .order_by(DebtReminderRun.created_at.desc())
        .limit(1)
    )


async def _latest_sent_run(
    db: AsyncSession, automation_id: uuid.UUID
) -> DebtReminderRun | None:
    return await db.scalar(
        select(DebtReminderRun)
        .where(
            DebtReminderRun.automation_id == automation_id,
            DebtReminderRun.status == DebtReminderStatus.SENT,
            DebtReminderRun.is_manual.is_(False),
        )
        .order_by(DebtReminderRun.scheduled_for.desc())
        .limit(1)
    )


async def _response(
    db: AsyncSession,
    customer_id: uuid.UUID,
    automation: DebtReminderAutomation,
) -> DebtReminderResponse:
    last_run = await _latest_run(db, automation.id)
    return DebtReminderResponse(
        id=automation.id,
        customer_id=customer_id,
        day_of_month=automation.day_of_month,
        repeat_enabled=automation.repeat_enabled,
        repeat_interval_days=automation.repeat_interval_days,
        send_time=automation.send_time.strftime("%H:%M"),
        message_parts=automation.message_parts,
        next_run_at=automation.next_run_at,
        last_run_status=last_run.status if last_run else None,
        last_run_at=(last_run.processed_at or last_run.created_at) if last_run else None,
        last_error=last_run.error_message if last_run else None,
        updated_at=automation.updated_at,
    )


async def get_debt_reminder(
    db: AsyncSession, customer_id: uuid.UUID
) -> DebtReminderResponse:
    if await db.scalar(select(Customer.id).where(Customer.id == customer_id)) is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng.", 404)
    automation = await db.scalar(
        select(DebtReminderAutomation).where(
            DebtReminderAutomation.customer_id == customer_id
        )
    )
    if automation is None:
        raise AppError(
            "DEBT_REMINDER_CONFIG_MISSING",
            "Khách hàng thiếu cấu hình nhắc công nợ.",
            500,
        )
    return await _response(db, customer_id, automation)


async def trigger_debt_reminder_now(
    db: AsyncSession,
    customer_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    actor_email: str,
    request_id: uuid.UUID,
    now: datetime | None = None,
) -> DebtReminderTriggerResponse:
    """Queue one immediate reminder without moving the automatic schedule."""
    effective_now = _as_utc(now or datetime.now(UTC))
    customer = await db.scalar(
        select(Customer)
        .options(selectinload(Customer.group))
        .where(Customer.id == customer_id)
        .with_for_update()
    )
    if customer is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng.", 404)
    automation = await db.scalar(
        select(DebtReminderAutomation)
        .where(DebtReminderAutomation.customer_id == customer_id)
        .with_for_update()
    )
    if automation is None:
        raise AppError(
            "DEBT_REMINDER_CONFIG_MISSING",
            "Khách hàng thiếu cấu hình nhắc công nợ.",
            500,
        )
    prior_run = await db.scalar(
        select(DebtReminderRun).where(
            DebtReminderRun.automation_id == automation.id,
            DebtReminderRun.triggered_by_user_id == actor_id,
            DebtReminderRun.manual_request_id == request_id,
        )
    )
    if prior_run is not None:
        return DebtReminderTriggerResponse(run_id=prior_run.id, status=prior_run.status)
    if not customer.has_debt:
        raise AppError(
            "CUSTOMER_HAS_NO_DEBT",
            "Khách hàng đã thanh toán nên không thể gửi nhắc công nợ.",
            409,
        )
    if not customer.debt_file_url:
        raise AppError(
            "CUSTOMER_FOLDER_REQUIRED",
            "Hãy thêm file công nợ (Google Sheet) trước khi gửi nhắc.",
            422,
        )
    if not customer.group.is_available:
        raise AppError(
            "GROUP_UNAVAILABLE",
            "Bot hiện không còn trong nhóm Zalo của khách hàng.",
            409,
        )
    active_run = await db.scalar(
        select(DebtReminderRun)
        .where(
            DebtReminderRun.automation_id == automation.id,
            DebtReminderRun.status.in_(
                [DebtReminderStatus.PENDING, DebtReminderStatus.PROCESSING]
            ),
        )
        .limit(1)
        .with_for_update()
    )
    if active_run is not None:
        raise AppError(
            "DEBT_REMINDER_ALREADY_RUNNING",
            "Đang có một lượt nhắc công nợ chờ gửi hoặc thử lại.",
            409,
        )

    run = DebtReminderRun(
        automation_id=automation.id,
        scheduled_for=effective_now,
        retry_at=effective_now,
        is_manual=True,
        triggered_by_user_id=actor_id,
        triggered_by_email=actor_email,
        manual_request_id=request_id,
        status=DebtReminderStatus.PROCESSING,
        attempt_count=1,
        claimed_at=effective_now,
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior_run = await db.scalar(
            select(DebtReminderRun).where(
                DebtReminderRun.automation_id == automation.id,
                DebtReminderRun.triggered_by_user_id == actor_id,
                DebtReminderRun.manual_request_id == request_id,
            )
        )
        if prior_run is not None:
            return DebtReminderTriggerResponse(
                run_id=prior_run.id, status=prior_run.status
            )
        raise AppError(
            "DEBT_REMINDER_ALREADY_RUNNING",
            "Đang có một lượt nhắc công nợ chờ gửi hoặc thử lại.",
            409,
        ) from None
    await db.refresh(run)

    from app.tasks.debt_reminder_tasks import process_debt_reminder_task

    try:
        process_debt_reminder_task.delay(str(run.id))
    except Exception as exc:
        logger.exception("DEBT_REMINDER_MANUAL_ENQUEUE_FAILED run_id=%s", run.id)
        run.status = DebtReminderStatus.FAILED
        run.claimed_at = None
        run.processed_at = datetime.now(UTC)
        run.error_code = "DEBT_REMINDER_QUEUE_UNAVAILABLE"
        run.error_message = "Không đưa được lượt nhắc công nợ vào hàng đợi."
        await db.commit()
        raise AppError(
            "DEBT_REMINDER_QUEUE_UNAVAILABLE",
            "Hàng đợi nhắc công nợ đang không phản hồi. Hãy thử lại sau.",
            503,
        ) from exc

    return DebtReminderTriggerResponse(run_id=run.id, status=run.status)


async def sync_debt_reminder_state(
    db: AsyncSession,
    customer: Customer,
    *,
    now: datetime | None = None,
    inactive_reason: str = "Nhắc công nợ đang tạm dừng.",
) -> DebtReminderAutomation:
    """Keep the persisted schedule in step with debt state and Sheet readiness.

    A customer is runnable only while they owe money and have a verified Sheet.
    Marking them paid or removing the Sheet pauses the schedule without
    discarding its settings.
    """
    automation = await db.scalar(
        select(DebtReminderAutomation)
        .where(DebtReminderAutomation.customer_id == customer.id)
        .with_for_update()
    )
    if automation is None:
        raise AppError(
            "DEBT_REMINDER_CONFIG_MISSING",
            "Khách hàng thiếu cấu hình nhắc công nợ.",
            500,
        )

    runnable = (
        customer.has_debt
        and bool(customer.debt_file_url)
        and customer.group.is_available
    )
    if runnable:
        if automation.next_run_at is None:
            automation.next_run_at = next_monthly_run(
                automation.day_of_month,
                automation.send_time,
                now=_as_utc(now or datetime.now(UTC)),
            )
        return automation

    automation.next_run_at = None
    await db.execute(
        update(DebtReminderRun)
        .where(
            DebtReminderRun.automation_id == automation.id,
            DebtReminderRun.status.in_(
                [DebtReminderStatus.PENDING, DebtReminderStatus.PROCESSING]
            ),
        )
        .values(
            status=DebtReminderStatus.CANCELLED,
            claimed_at=None,
            processed_at=_as_utc(now or datetime.now(UTC)),
            error_message=inactive_reason,
        )
    )
    return automation


async def save_debt_reminder(
    db: AsyncSession,
    customer_id: uuid.UUID,
    data: DebtReminderUpdate,
    *,
    now: datetime | None = None,
) -> DebtReminderResponse:
    customer = await db.scalar(
        select(Customer)
        .options(selectinload(Customer.group))
        .where(Customer.id == customer_id)
        .with_for_update()
    )
    if customer is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng.", 404)
    if not customer.debt_file_url:
        raise AppError(
            "CUSTOMER_FOLDER_REQUIRED",
            "Hãy thêm file công nợ (Google Sheet) trước khi lưu nhắc công nợ.",
            422,
        )
    automation = await db.scalar(
        select(DebtReminderAutomation)
        .where(DebtReminderAutomation.customer_id == customer_id)
        .with_for_update()
    )
    parsed_time = time.fromisoformat(data.send_time)
    parts = [part.model_dump() for part in data.message_parts]
    if automation is None:
        raise AppError(
            "DEBT_REMINDER_CONFIG_MISSING",
            "Khách hàng thiếu cấu hình nhắc công nợ.",
            500,
        )
    automation.day_of_month = data.day_of_month
    automation.repeat_enabled = data.repeat_enabled
    automation.repeat_interval_days = data.repeat_interval_days
    automation.send_time = parsed_time
    automation.message_parts = parts
    await db.execute(
        update(DebtReminderRun)
        .where(
            DebtReminderRun.automation_id == automation.id,
            DebtReminderRun.status.in_(
                [DebtReminderStatus.PENDING, DebtReminderStatus.PROCESSING]
            ),
        )
        .values(
            status=DebtReminderStatus.CANCELLED,
            claimed_at=None,
            processed_at=now or datetime.now(UTC),
            error_message="Cấu hình nhắc công nợ đã thay đổi.",
        )
    )
    effective_now = _as_utc(now or datetime.now(UTC))
    if customer.has_debt and customer.group.is_available:
        next_run_at = next_monthly_run(
            data.day_of_month, parsed_time, now=effective_now
        )
        last_sent = await _latest_sent_run(db, automation.id)
        if last_sent is not None and data.repeat_enabled:
            repeated_run = defer_debt_reminder(
                _as_utc(last_sent.scheduled_for)
                + timedelta(days=data.repeat_interval_days)
            )
            # Preserve the config-edit behaviour: an overdue repeat is due now,
            # except that lunar blackout dates still move it to the first
            # permitted following day at the configured send time.
            local_now = effective_now.astimezone(LOCAL_TIMEZONE)
            overdue_floor = effective_now
            if is_debt_reminder_blackout(local_now.date()):
                overdue_floor = defer_debt_reminder(
                    datetime.combine(
                        local_now.date(),
                        parsed_time,
                        tzinfo=LOCAL_TIMEZONE,
                    )
                )
            next_run_at = min(
                next_run_at,
                max(repeated_run, overdue_floor),
            )
        automation.next_run_at = next_run_at
    else:
        automation.next_run_at = None
    await db.commit()
    await db.refresh(automation)
    return await _response(db, customer_id, automation)
