import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.alerts import Severity
from app.db.database import SessionLocal
from app.models import Customer, DebtReminderAutomation, DebtReminderRun, ZaloGroup
from app.models.entities import (
    BotStatus,
    DebtReminderStatus,
    DeliveryStatus,
    DeliveryType,
)
from app.services.alerting import customer_link, report_async
from app.services.debt_reminder_service import (
    defer_debt_reminder,
    next_debt_reminder_run,
)
from app.services.delivery_service import add_delivery_log
from app.services.google_sheets_service import SheetExportError, google_sheets
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.debt_reminder_scheduler")
MAX_ATTEMPTS = 5


async def claim_due_debt_reminders() -> list[uuid.UUID]:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        await db.execute(
            update(DebtReminderRun)
            .where(
                DebtReminderRun.status == DebtReminderStatus.PROCESSING,
                DebtReminderRun.claimed_at < now - timedelta(minutes=20),
            )
            .values(
                status=DebtReminderStatus.PENDING,
                claimed_at=None,
                retry_at=now,
            )
        )
        automations = list(
            (
                await db.scalars(
                    select(DebtReminderAutomation)
                    .join(Customer)
                    .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
                    .options(selectinload(DebtReminderAutomation.customer))
                    .where(
                        Customer.has_debt.is_(True),
                        Customer.debt_file_url.is_not(None),
                        Customer.debt_file_url != "",
                        ZaloGroup.is_available.is_(True),
                        DebtReminderAutomation.next_run_at.is_not(None),
                        DebtReminderAutomation.next_run_at <= now,
                    )
                    .order_by(DebtReminderAutomation.next_run_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for automation in automations:
            scheduled_for = automation.next_run_at
            if scheduled_for is None:
                continue
            deferred_for = defer_debt_reminder(scheduled_for)
            scheduled_for_utc = (
                scheduled_for.replace(tzinfo=UTC)
                if scheduled_for.tzinfo is None
                else scheduled_for.astimezone(UTC)
            )
            if deferred_for != scheduled_for_utc:
                automation.next_run_at = deferred_for
                continue
            db.add(
                DebtReminderRun(
                    automation_id=automation.id,
                    scheduled_for=scheduled_for,
                    retry_at=scheduled_for,
                    status=DebtReminderStatus.PENDING,
                )
            )
            automation.next_run_at = next_debt_reminder_run(
                automation.day_of_month,
                automation.send_time,
                automation.repeat_interval_days,
                scheduled_for,
                repeat_enabled=automation.repeat_enabled,
                has_debt=automation.customer.has_debt,
                now=now,
            )
        await db.flush()

        jobs = list(
            (
                await db.scalars(
                    select(DebtReminderRun)
                    .where(
                        DebtReminderRun.status == DebtReminderStatus.PENDING,
                        DebtReminderRun.retry_at <= now,
                    )
                    .order_by(DebtReminderRun.retry_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in jobs:
            job.status = DebtReminderStatus.PROCESSING
            job.claimed_at = now
            job.attempt_count += 1
        await db.commit()
        return [job.id for job in jobs]


def _current_delivery_type(run: DebtReminderRun) -> DeliveryType:
    if not run.image_message_id:
        return DeliveryType.DEBT_REMINDER_IMAGE
    if not run.link_message_id:
        return DeliveryType.DEBT_REMINDER_LINK
    return DeliveryType.DEBT_REMINDER_MESSAGE


async def _fail_run(
    run: DebtReminderRun,
    customer_id: uuid.UUID,
    code: str,
    message: str,
) -> None:
    async with SessionLocal() as db:
        current = await db.get(DebtReminderRun, run.id)
        if (
            current is None
            or current.status != DebtReminderStatus.PROCESSING
            or _as_utc(current.claimed_at) != _as_utc(run.claimed_at)
        ):
            return
        await add_delivery_log(
            db,
            customer_id,
            _current_delivery_type(current),
            DeliveryStatus.FAILED,
            error_code=code,
            error_message=message,
        )
        current.error_code = code
        current.error_message = message
        current.claimed_at = None
        if current.attempt_count >= MAX_ATTEMPTS:
            current.status = DebtReminderStatus.FAILED
            current.processed_at = datetime.now(UTC)
        else:
            delay_minutes = min(60, 5 * (2 ** max(0, current.attempt_count - 1)))
            current.status = DebtReminderStatus.PENDING
            current.retry_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
        exhausted = current.status == DebtReminderStatus.FAILED
        attempts = current.attempt_count
        customer_name = await db.scalar(
            select(ZaloGroup.name)
            .join(Customer, Customer.zalo_group_id == ZaloGroup.id)
            .where(Customer.id == customer_id)
        )
        await db.commit()
        logger.warning(
            "DEBT_REMINDER_FAILED run_id=%s attempt=%d code=%s",
            current.id,
            attempts,
            code,
        )
    await report_async(
        "DEBT_REMINDER_FAILED" if exhausted else "DEBT_REMINDER_RETRY",
        (
            f"Không nhắc được công nợ sau {MAX_ATTEMPTS} lần thử, khách sẽ không nhận"
            f" được nhắc: {message}"
            if exhausted
            else f"Nhắc công nợ lỗi, sẽ thử lại: {message}"
        ),
        severity=Severity.ERROR if exhausted else Severity.WARNING,
        service="celery-worker",
        context={
            "Khách hàng": customer_name or str(customer_id),
            "Xem tại": customer_link(customer_id),
            "Mã lỗi gốc": code,
            "Lần thử": str(attempts),
        },
    )


async def _finish_without_sending(
    run_id: uuid.UUID,
    claimed_at: datetime | None,
    status: DebtReminderStatus,
    reason: str,
) -> None:
    async with SessionLocal() as db:
        run = await db.scalar(
            select(DebtReminderRun)
            .where(DebtReminderRun.id == run_id)
            .with_for_update()
        )
        if (
            run is None
            or run.status != DebtReminderStatus.PROCESSING
            or _as_utc(run.claimed_at) != _as_utc(claimed_at)
        ):
            return
        run.status = status
        run.error_message = reason
        run.claimed_at = None
        run.processed_at = datetime.now(UTC)
        await db.commit()


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _send_step_if_current(
    run_id: uuid.UUID,
    claimed_at: datetime | None,
    customer_id: uuid.UUID,
    delivery_type: DeliveryType,
    field_name: str,
    send: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[bool, str | None]:
    """Lock business state across one external send.

    Customer/config mutations take the same locks in the same order. Therefore
    either a paid change commits first and this step stays silent, or
    this send finishes before the mutation returns to the operator.
    """
    async with SessionLocal() as db:
        snapshot = await db.get(DebtReminderRun, run_id)
        if snapshot is None:
            return False, None
        automation_snapshot = await db.get(DebtReminderAutomation, snapshot.automation_id)
        if automation_snapshot is None:
            return False, None
        customer = await db.scalar(
            select(Customer)
            .where(Customer.id == automation_snapshot.customer_id)
            .with_for_update()
        )
        automation = await db.scalar(
            select(DebtReminderAutomation)
            .where(DebtReminderAutomation.id == snapshot.automation_id)
            .with_for_update()
        )
        if automation is None:
            return False, None
        run = await db.scalar(
            select(DebtReminderRun)
            .where(DebtReminderRun.id == run_id)
            .with_for_update()
        )
        if (
            run is None
            or run.status != DebtReminderStatus.PROCESSING
            or _as_utc(run.claimed_at) != _as_utc(claimed_at)
            or customer is None
            or not customer.has_debt
        ):
            return False, None
        existing = getattr(run, field_name)
        if existing:
            return True, str(existing)
        result = await send(f"debt:{run.id}:{field_name}")
        message_id = str(result.get("message_id") or "") or None
        setattr(run, field_name, message_id or "confirmed")
        run.error_code = None
        run.error_message = None
        await add_delivery_log(
            db,
            customer_id,
            delivery_type,
            DeliveryStatus.SENT,
            zalo_message_id=message_id,
        )
        await db.commit()
        return True, message_id


async def process_debt_reminder(run_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        run = await db.scalar(
            select(DebtReminderRun)
            .options(
                selectinload(DebtReminderRun.automation)
                .selectinload(DebtReminderAutomation.customer)
                .selectinload(Customer.group)
            )
            .where(DebtReminderRun.id == run_id)
        )
        if run is None or run.status != DebtReminderStatus.PROCESSING:
            return
        automation = run.automation
        customer = automation.customer
        customer_id = customer.id
        group_id = customer.group.zalo_group_id
        parts = automation.message_parts
        debt_file_url = customer.debt_file_url
        if not customer.has_debt:
            await _finish_without_sending(
                run.id,
                run.claimed_at,
                DebtReminderStatus.SKIPPED,
                "Khách hàng đã thanh toán tại thời điểm kiểm tra.",
            )
            return
        if not customer.group.is_available:
            await _fail_run(
                run, customer_id, "GROUP_UNAVAILABLE", "Nhóm Zalo hiện không khả dụng."
            )
            return
        if not debt_file_url:
            await _fail_run(
                run,
                customer_id,
                "CUSTOMER_FOLDER_REQUIRED",
                "Khách hàng chưa có file công nợ.",
            )
            return

        try:
            bot = await zalo_gateway.get_status()
            if bot.get("status") != BotStatus.CONNECTED.value:
                code = (
                    "AUTH_REQUIRED"
                    if bot.get("status") == BotStatus.AUTH_REQUIRED.value
                    else "BOT_DISCONNECTED"
                )
                raise GatewayError(code, "Bot Zalo chưa kết nối.", 409)

            mention_ids = {
                str(part.get("user_id"))
                for part in parts
                if part.get("type") == "mention"
            }
            if mention_ids:
                members = await zalo_gateway.get_group_members(group_id)
                member_ids = {str(member.get("user_id")) for member in members}
                missing = mention_ids - member_ids
                if missing:
                    raise GatewayError(
                        "MENTION_MEMBER_NOT_FOUND",
                        "Một thành viên được mention không còn trong nhóm Zalo.",
                        422,
                    )

            artifact = None
            if not run.image_message_id or not run.sheet_url:
                artifact = await google_sheets.export_first_sheet(debt_file_url)
                run.sheet_file_id = artifact.file_id
                run.sheet_name = artifact.file_name
                run.sheet_url = artifact.web_view_link
                await db.commit()

            if not run.image_message_id:
                if artifact is None:
                    artifact = await google_sheets.export_first_sheet(debt_file_url)
                sent, message_id = await _send_step_if_current(
                    run.id,
                    run.claimed_at,
                    customer_id,
                    DeliveryType.DEBT_REMINDER_IMAGE,
                    "image_message_id",
                    lambda key: zalo_gateway.send_image(
                        group_id,
                        artifact.png_data,
                        width=artifact.width,
                        height=artifact.height,
                        idempotency_key=key,
                    ),
                )
                if not sent:
                    return
                run.image_message_id = message_id or "confirmed"

            if not run.link_message_id:
                link = run.sheet_url or (artifact.web_view_link if artifact else None)
                if not link:
                    raise SheetExportError(
                        "GOOGLE_SHEET_LINK_MISSING", "Không lấy được link Google Sheet."
                    )
                sent, message_id = await _send_step_if_current(
                    run.id,
                    run.claimed_at,
                    customer_id,
                    DeliveryType.DEBT_REMINDER_LINK,
                    "link_message_id",
                    lambda key: zalo_gateway.send_link(
                        group_id, link, idempotency_key=key
                    ),
                )
                if not sent:
                    return
                run.link_message_id = message_id or "confirmed"

            if not run.text_message_id:
                sent, _message_id = await _send_step_if_current(
                    run.id,
                    run.claimed_at,
                    customer_id,
                    DeliveryType.DEBT_REMINDER_MESSAGE,
                    "text_message_id",
                    lambda key: zalo_gateway.send_rich_text(
                        group_id, parts, idempotency_key=key
                    ),
                )
                if not sent:
                    return

            async with SessionLocal() as finish_db:
                current = await finish_db.scalar(
                    select(DebtReminderRun)
                    .where(DebtReminderRun.id == run.id)
                    .with_for_update()
                )
                if (
                    current is not None
                    and current.status == DebtReminderStatus.PROCESSING
                    and _as_utc(current.claimed_at) == _as_utc(run.claimed_at)
                ):
                    current.status = DebtReminderStatus.SENT
                    current.claimed_at = None
                    current.processed_at = datetime.now(UTC)
                    current.error_code = None
                    current.error_message = None
                    await finish_db.commit()
            logger.info("DEBT_REMINDER_SENT run_id=%s customer_id=%s", run.id, customer_id)
        except (GatewayError, SheetExportError) as exc:
            await _fail_run(run, customer_id, exc.code, exc.message)
        except Exception:
            logger.exception("DEBT_REMINDER_UNEXPECTED_ERROR run_id=%s", run.id)
            await _fail_run(
                run,
                customer_id,
                "DEBT_REMINDER_INTERNAL_ERROR",
                "Tác vụ nhắc công nợ gặp lỗi không xác định.",
            )
