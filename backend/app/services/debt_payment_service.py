import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.core.alerts import Severity
from app.models import (
    Customer,
    DebtPaymentConfirmation,
    DebtPaymentSettings,
    ZaloGroup,
)
from app.models.entities import DeliveryStatus, DeliveryType
from app.schemas.api import (
    DebtPaymentSettingsResponse,
    DebtPaymentSettingsUpdate,
    IncomingGroupMessage,
)
from app.services.alerting import customer_link, report_async
from app.services.debt_reminder_service import sync_debt_reminder_state
from app.services.delivery_service import add_delivery_log
from app.services.mention_rules import normalize_phrase
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.debt_payment")
GLOBAL_SETTINGS_ID = 1
DEFAULT_PHRASES = ["đã thanh toán", "đã tt", "da thanh toan"]
REPLY_TASK = "zbridge.debt_payments.send_reply"
#: Seconds before each retry of the group notice; the first attempt is immediate.
REPLY_RETRY_DELAYS = (60, 300, 900, 1800)
REPLY_ATTEMPTS = len(REPLY_RETRY_DELAYS) + 1
PENDING_STALE_AFTER = timedelta(hours=2)


def _response(settings: DebtPaymentSettings) -> DebtPaymentSettingsResponse:
    return DebtPaymentSettingsResponse(
        tracked_members=settings.tracked_members,
        notification_targets=settings.notification_targets,
        phrases=settings.phrases,
        updated_at=settings.updated_at,
    )


async def get_settings(db: AsyncSession) -> DebtPaymentSettingsResponse:
    settings = await db.get(DebtPaymentSettings, GLOBAL_SETTINGS_ID)
    if settings is None:
        settings = DebtPaymentSettings(
            id=GLOBAL_SETTINGS_ID,
            tracked_members=[],
            notification_targets=[],
            phrases=DEFAULT_PHRASES,
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return _response(settings)


async def save_settings(
    db: AsyncSession, data: DebtPaymentSettingsUpdate
) -> DebtPaymentSettingsResponse:
    settings = await db.get(DebtPaymentSettings, GLOBAL_SETTINGS_ID)
    if settings is None:
        settings = DebtPaymentSettings(
            id=GLOBAL_SETTINGS_ID,
            tracked_members=[],
            notification_targets=[],
            phrases=[],
        )
        db.add(settings)

    seen: set[str] = set()
    phrases: list[str] = []
    for raw in data.phrases:
        normalized = normalize_phrase(raw)
        if normalized and normalized not in seen:
            phrases.append(raw.strip())
            seen.add(normalized)

    settings.tracked_members = [member.model_dump() for member in data.tracked_members]
    settings.notification_targets = [
        member.model_dump() for member in data.notification_targets
    ]
    settings.phrases = phrases
    await db.commit()
    await db.refresh(settings)
    logger.info(
        "DEBT_PAYMENT_SETTINGS_SAVED members=%d notification_targets=%d phrases=%d",
        len(settings.tracked_members),
        len(settings.notification_targets),
        len(settings.phrases),
    )
    return _response(settings)


def _matched_phrase(content: str, phrases: list[str]) -> str | None:
    normalized_content = normalize_phrase(content)
    if not normalized_content:
        return None
    padded_content = f" {normalized_content} "
    for phrase in phrases:
        normalized_phrase = normalize_phrase(phrase)
        if normalized_phrase and f" {normalized_phrase} " in padded_content:
            return phrase
    return None


async def apply_payment_confirmation(
    db: AsyncSession, event: IncomingGroupMessage
) -> bool:
    """Record a trusted "đã thanh toán" message and start notifying the group.

    The customer switches to paid in :func:`process_confirmation` only after the
    notice went out, so a failed notice leaves the debt open for staff to see.
    """
    settings = await db.get(DebtPaymentSettings, GLOBAL_SETTINGS_ID)
    if settings is None or not event.sender_id:
        return False

    tracked = {
        str(member.get("user_id")): member
        for member in settings.tracked_members
        if member.get("user_id")
    }
    member = tracked.get(event.sender_id)
    phrase = _matched_phrase(event.content, settings.phrases) if member else None
    if member is None or phrase is None:
        return False

    now = datetime.now(UTC)
    sent_at = event.sent_at or now
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    else:
        sent_at = sent_at.astimezone(UTC)

    customer_id = await db.scalar(
        select(Customer.id)
        .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
        .where(ZaloGroup.zalo_group_id == event.group_id)
    )
    if customer_id is None:
        return False

    customer = await db.scalar(
        select(Customer)
        .options(selectinload(Customer.group))
        .where(Customer.id == customer_id)
        .with_for_update(of=Customer)
    )
    if customer is None:
        return False
    # One in-flight confirmation per customer: a second "đã thanh toán" while the
    # first is still notifying must not post the notice twice. A pending row older
    # than the whole retry schedule lost its task and must not block forever.
    duplicate = await db.scalar(
        select(DebtPaymentConfirmation.id).where(
            DebtPaymentConfirmation.customer_id == customer.id,
            or_(
                DebtPaymentConfirmation.source_message_id == event.message_id,
                (
                    DebtPaymentConfirmation.applied_at.is_(None)
                    & DebtPaymentConfirmation.failed_at.is_(None)
                    & (DebtPaymentConfirmation.created_at >= now - PENDING_STALE_AFTER)
                ),
            ),
        )
    )
    last_paid_at = customer.last_debt_paid_at
    if last_paid_at is not None:
        last_paid_at = (
            last_paid_at.replace(tzinfo=UTC)
            if last_paid_at.tzinfo is None
            else last_paid_at.astimezone(UTC)
        )
    if (
        duplicate is not None
        or not customer.has_debt
        or (last_paid_at is not None and sent_at <= last_paid_at)
    ):
        return False

    display_name = (
        event.sender_display_name
        or str(member.get("display_name") or "")
        or event.sender_id
    )
    confirmation = DebtPaymentConfirmation(
        customer_id=customer.id,
        source_message_id=event.message_id,
        sender_id=event.sender_id,
        sender_display_name=display_name,
        content=event.content,
        matched_phrase=phrase,
        message_sent_at=sent_at,
    )
    db.add(confirmation)
    await db.commit()
    logger.info(
        "DEBT_PAYMENT_CONFIRMATION_MATCHED customer_id=%s group_id=%s sender_id=%s message_id=%s",
        customer.id,
        event.group_id,
        event.sender_id,
        event.message_id,
    )
    await _start_delivery(db, confirmation)
    return True


def _reply_parts(targets: list[dict[str, object]]) -> list[dict[str, str]]:
    parts = [{"type": "text", "text": "Hệ thống đã xác nhận thanh toán, vui lòng "}]
    for index, target in enumerate(targets):
        if index:
            parts.append({"type": "text", "text": ", "})
        parts.append(
            {
                "type": "mention",
                "user_id": str(target["user_id"]),
                "display_name": str(target["display_name"]),
            }
        )
    parts.append({"type": "text", "text": " vào chỉnh sửa công nợ."})
    return parts


async def process_confirmation(
    db: AsyncSession,
    confirmation_id: uuid.UUID,
    *,
    final: bool = False,
    attempt: int = 0,
) -> bool:
    """Notify the group, then mark the customer paid; False means retry later.

    The paid switch waits for both messages so staff are always told when a debt
    closes. Safe to re-run: a message already accepted by Zalo is skipped by its
    stored ID, and the stable idempotency keys make the gateway answer from its
    receipt when only the response to an earlier attempt was lost.
    """
    settings = await db.get(DebtPaymentSettings, GLOBAL_SETTINGS_ID)
    confirmation = await db.scalar(
        select(DebtPaymentConfirmation)
        .options(
            selectinload(DebtPaymentConfirmation.customer).selectinload(Customer.group)
        )
        .where(DebtPaymentConfirmation.id == confirmation_id)
    )
    if (
        confirmation is None
        or confirmation.applied_at is not None
        or confirmation.failed_at is not None
    ):
        return True
    customer = confirmation.customer
    group_id = customer.group.zalo_group_id
    key = f"debt-payment-confirmation:{customer.id}:{confirmation.source_message_id}"
    targets = settings.notification_targets if settings else []
    parts = _reply_parts(targets)
    # The link goes out on its own so Zalo renders its preview card cleanly.
    steps = []
    if targets:
        steps.append(
            (
                "reply_message_id",
                lambda: zalo_gateway.send_rich_text(group_id, parts, idempotency_key=key),
            )
        )
    if targets and customer.debt_file_url:
        link = customer.debt_file_url
        steps.append(
            (
                "link_message_id",
                lambda: zalo_gateway.send_link(
                    group_id, link, idempotency_key=f"{key}:link"
                ),
            )
        )
    for field, send in steps:
        if getattr(confirmation, field):
            continue
        try:
            result = await send()
        except GatewayError as exc:
            await add_delivery_log(
                db,
                customer.id,
                DeliveryType.DEBT_PAYMENT_CONFIRMATION,
                DeliveryStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            await db.commit()
            logger.warning(
                "DEBT_PAYMENT_CONFIRMATION_REPLY_FAILED confirmation_id=%s code=%s final=%s",
                confirmation.id,
                exc.code,
                final,
            )
            if final:
                confirmation.failed_at = datetime.now(UTC)
                await db.commit()
            await _report_failure(
                confirmation, exc.code, exc.message, final=final, attempt=attempt
            )
            return False
        message_id = str(result.get("message_id") or "") or None
        setattr(confirmation, field, message_id or "confirmed")
        await add_delivery_log(
            db,
            customer.id,
            DeliveryType.DEBT_PAYMENT_CONFIRMATION,
            DeliveryStatus.SENT,
            zalo_message_id=message_id,
        )
        await db.commit()

    locked = await db.scalar(
        select(Customer)
        .options(selectinload(Customer.group))
        .where(Customer.id == customer.id)
        .with_for_update(of=Customer)
        .execution_options(populate_existing=True)
    )
    await db.refresh(confirmation)
    if confirmation.applied_at is not None or locked is None:
        return True
    last_paid_at = locked.last_debt_paid_at
    if last_paid_at is not None and last_paid_at.tzinfo is None:
        last_paid_at = last_paid_at.replace(tzinfo=UTC)
    sent_at = confirmation.message_sent_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    # Staff may have switched the customer by hand while the notice was retrying.
    if locked.has_debt and (last_paid_at is None or sent_at > last_paid_at):
        locked.has_debt = False
        locked.last_debt_paid_at = sent_at
        await sync_debt_reminder_state(
            db,
            locked,
            inactive_reason="Khách hàng đã được tự động đánh dấu thanh toán từ tin nhắn Zalo.",
        )
    confirmation.applied_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "DEBT_PAYMENT_AUTO_CONFIRMED customer_id=%s confirmation_id=%s",
        locked.id,
        confirmation.id,
    )
    return True


async def _start_delivery(
    db: AsyncSession, confirmation: DebtPaymentConfirmation
) -> None:
    """Hand the notice to Celery so the event request never waits on Zalo.

    Sending inline used to hold the gateway's event POST (10s timeout) behind the
    shared 1-message-per-second send queue; a timeout made the gateway resend the
    event and let the next one overtake it.
    """
    try:
        await asyncio.to_thread(
            celery_app.send_task, REPLY_TASK, args=[str(confirmation.id)], retry=False
        )
        return
    except Exception:
        logger.exception(
            "DEBT_PAYMENT_CONFIRMATION_ENQUEUE_FAILED confirmation_id=%s",
            confirmation.id,
        )
    # The queue is down, so nothing would retry: one attempt here, and a failure
    # closes the confirmation (debt stays open) and alerts.
    await process_confirmation(db, confirmation.id, final=True)


async def expire_stuck_confirmations(db: AsyncSession) -> int:
    """Close pending confirmations the retry task lost, so none rots silently.

    The whole retry schedule takes under an hour; a row still pending well past
    that had its task dropped (worker killed, broker lost it). Its debt is still
    open, so staff must hear about it.
    """
    stuck = list(
        (
            await db.scalars(
                select(DebtPaymentConfirmation)
                .options(
                    selectinload(DebtPaymentConfirmation.customer).selectinload(
                        Customer.group
                    )
                )
                .where(
                    DebtPaymentConfirmation.applied_at.is_(None),
                    DebtPaymentConfirmation.failed_at.is_(None),
                    DebtPaymentConfirmation.created_at
                    < datetime.now(UTC) - PENDING_STALE_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for confirmation in stuck:
        confirmation.failed_at = datetime.now(UTC)
    await db.commit()
    for confirmation in stuck:
        logger.error(
            "DEBT_PAYMENT_CONFIRMATION_STUCK confirmation_id=%s", confirmation.id
        )
        await _report_failure(
            confirmation,
            "DEBT_PAYMENT_CONFIRMATION_STUCK",
            "tác vụ gửi tin đã bị mất (quá 2 giờ vẫn chưa xong)",
            final=True,
        )
    return len(stuck)


async def _report_failure(
    confirmation: DebtPaymentConfirmation,
    code: str,
    message: str,
    *,
    final: bool,
    attempt: int = 0,
) -> None:
    customer = confirmation.customer
    alert_code = (
        "DEBT_PAYMENT_CONFIRMATION_FAILED" if final else "DEBT_PAYMENT_CONFIRMATION_RETRY"
    )
    await report_async(
        alert_code,
        (
            "Không gửi được tin báo thanh toán vào nhóm, khách CHƯA được chuyển sang "
            f"đã thanh toán, cần xử lý tay: {message}"
            if final
            else f"Gửi tin báo thanh toán lỗi (lần {attempt + 1}/{REPLY_ATTEMPTS}), sẽ thử"
            f" lại; khách chưa được chuyển sang đã thanh toán: {message}"
        ),
        severity=Severity.ERROR if final else Severity.WARNING,
        service="celery-worker",
        context={
            "Khách hàng": customer.group.name,
            "Xem tại": customer_link(customer.id),
            "Tin nhắn": confirmation.content,
            "Mã lỗi gốc": code,
        },
        # Per attempt: every failure reaches Telegram, and another customer failing
        # in the same window is still named. Bounded by REPLY_ATTEMPTS per payment.
        dedup_key=f"{alert_code}:{confirmation.id}:{attempt}",
    )
