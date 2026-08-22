import calendar
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import DebtReminderAutomation, DebtReminderRun
from app.models.entities import DebtReminderStatus
from app.schemas.api import DebtReminderResponse, DebtReminderUpdate
from app.services.customer_service import get_customer

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_MESSAGE_PARTS = [
    {"type": "text", "text": "Vui lòng thanh toán công nợ giúp mình nhé."}
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    if not has_debt:
        return monthly_anchor
    step = timedelta(days=repeat_interval_days)
    repeated_run = scheduled_for + step
    if repeated_run <= reference:
        missed = (reference - repeated_run) // step + 1
        repeated_run += missed * step
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
        )
        .order_by(DebtReminderRun.scheduled_for.desc())
        .limit(1)
    )


async def _response(
    db: AsyncSession,
    customer_id: uuid.UUID,
    automation: DebtReminderAutomation | None,
) -> DebtReminderResponse:
    if automation is None:
        return DebtReminderResponse(
            customer_id=customer_id,
            enabled=False,
            day_of_month=25,
            repeat_interval_days=3,
            send_time="09:00",
            message_parts=DEFAULT_MESSAGE_PARTS,
        )
    last_run = await _latest_run(db, automation.id)
    return DebtReminderResponse(
        id=automation.id,
        customer_id=customer_id,
        enabled=automation.enabled,
        day_of_month=automation.day_of_month,
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
    await get_customer(db, customer_id)
    automation = await db.scalar(
        select(DebtReminderAutomation).where(
            DebtReminderAutomation.customer_id == customer_id
        )
    )
    return await _response(db, customer_id, automation)


async def save_debt_reminder(
    db: AsyncSession,
    customer_id: uuid.UUID,
    data: DebtReminderUpdate,
    *,
    now: datetime | None = None,
) -> DebtReminderResponse:
    customer = await get_customer(db, customer_id)
    if data.enabled and not customer.debt_file_url:
        raise AppError(
            "CUSTOMER_FOLDER_REQUIRED",
            "Hãy thêm file công nợ (Google Sheet) trước khi bật nhắc công nợ.",
            422,
        )
    automation = await db.scalar(
        select(DebtReminderAutomation).where(
            DebtReminderAutomation.customer_id == customer_id
        )
    )
    parsed_time = time.fromisoformat(data.send_time)
    parts = [part.model_dump() for part in data.message_parts]
    if automation is None:
        automation = DebtReminderAutomation(
            customer_id=customer_id,
            enabled=data.enabled,
            day_of_month=data.day_of_month,
            repeat_interval_days=data.repeat_interval_days,
            send_time=parsed_time,
            message_parts=parts,
        )
        db.add(automation)
        await db.flush()
    else:
        automation.enabled = data.enabled
        automation.day_of_month = data.day_of_month
        automation.repeat_interval_days = data.repeat_interval_days
        automation.send_time = parsed_time
        automation.message_parts = parts
        await db.execute(
            update(DebtReminderRun)
            .where(
                DebtReminderRun.automation_id == automation.id,
                DebtReminderRun.status == DebtReminderStatus.PENDING,
            )
            .values(
                status=DebtReminderStatus.CANCELLED,
                processed_at=now or datetime.now(UTC),
            )
        )
    effective_now = _as_utc(now or datetime.now(UTC))
    if data.enabled:
        next_run_at = next_monthly_run(
            data.day_of_month, parsed_time, now=effective_now
        )
        if customer.has_debt:
            last_sent = await _latest_sent_run(db, automation.id)
            if last_sent is not None:
                repeated_run = _as_utc(last_sent.scheduled_for) + timedelta(
                    days=data.repeat_interval_days
                )
                # An already-overdue repeat must fire now. Dropping it would push a
                # still-indebted customer all the way to next month's anchor.
                next_run_at = min(next_run_at, max(repeated_run, effective_now))
        automation.next_run_at = next_run_at
    else:
        automation.next_run_at = None
    await db.commit()
    await db.refresh(automation)
    return await _response(db, customer_id, automation)
