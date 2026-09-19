import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.services.debt_reminder_service import sync_debt_reminder_state
from app.services.delivery_service import add_delivery_log
from app.services.mention_rules import normalize_phrase
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.debt_payment")
GLOBAL_SETTINGS_ID = 1
DEFAULT_PHRASES = ["đã thanh toán", "đã tt", "da thanh toan"]


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
    """Apply the same paid transition as the customer switch, then audit it."""
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
    duplicate = await db.scalar(
        select(DebtPaymentConfirmation.id).where(
            DebtPaymentConfirmation.customer_id == customer.id,
            DebtPaymentConfirmation.source_message_id == event.message_id,
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
    customer.has_debt = False
    customer.last_debt_paid_at = sent_at
    db.add(
        DebtPaymentConfirmation(
            customer_id=customer.id,
            source_message_id=event.message_id,
            sender_id=event.sender_id,
            sender_display_name=display_name,
            content=event.content,
            matched_phrase=phrase,
            message_sent_at=sent_at,
        )
    )
    await sync_debt_reminder_state(
        db,
        customer,
        now=now,
        inactive_reason="Khách hàng đã được tự động đánh dấu thanh toán từ tin nhắn Zalo.",
    )
    # The acknowledgement must never get ahead of the source-of-truth state.
    await db.commit()
    if settings.notification_targets:
        parts: list[dict[str, str]] = [
            {"type": "text", "text": "Hệ thống đã xác nhận thanh toán, vui lòng "}
        ]
        for index, target in enumerate(settings.notification_targets):
            if index:
                parts.append({"type": "text", "text": ", "})
            parts.append(
                {
                    "type": "mention",
                    "user_id": str(target["user_id"]),
                    "display_name": str(target["display_name"]),
                }
            )
        suffix = " vào chỉnh sửa công nợ"
        suffix += f": {customer.debt_file_url}" if customer.debt_file_url else "."
        parts.append({"type": "text", "text": suffix})
        try:
            result = await zalo_gateway.send_rich_text(
                event.group_id,
                parts,
                idempotency_key=(
                    f"debt-payment-confirmation:{customer.id}:{event.message_id}"
                ),
            )
            await add_delivery_log(
                db,
                customer.id,
                DeliveryType.DEBT_PAYMENT_CONFIRMATION,
                DeliveryStatus.SENT,
                zalo_message_id=str(result.get("message_id") or "") or None,
            )
        except GatewayError as exc:
            await add_delivery_log(
                db,
                customer.id,
                DeliveryType.DEBT_PAYMENT_CONFIRMATION,
                DeliveryStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            logger.warning(
                "DEBT_PAYMENT_CONFIRMATION_REPLY_FAILED customer_id=%s code=%s",
                customer.id,
                exc.code,
            )
        await db.commit()
    logger.info(
        "DEBT_PAYMENT_AUTO_CONFIRMED customer_id=%s group_id=%s sender_id=%s message_id=%s",
        customer.id,
        event.group_id,
        event.sender_id,
        event.message_id,
    )
    return True
