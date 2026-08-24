import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.alerts import Severity
from app.db.database import SessionLocal
from app.models import Customer, MentionAutomation, MentionFollowup
from app.models.entities import (
    BotStatus,
    DeliveryStatus,
    DeliveryType,
    MentionFollowupStatus,
)
from app.services.alerting import customer_link, report_async
from app.services.delivery_service import add_delivery_log
from app.services.mention_time_windows import next_allowed_at
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.mention_scheduler")

MAX_ATTEMPTS = 3
STALE_CLAIM_AFTER = timedelta(minutes=10)
RETRY_DELAY = timedelta(minutes=5)
EVENTS_DOWN_DELAY = timedelta(minutes=5)


@dataclass(frozen=True)
class _FollowupJob:
    """Everything a send needs, captured so no DB row stays locked during it."""

    followup_id: uuid.UUID
    claimed_at: datetime | None
    zalo_group_id: str
    customer_id: uuid.UUID | None
    customer_name: str
    delay_minutes: int
    active_windows: list[dict[str, str]]
    targets: list[dict[str, str]]
    idempotency_key: str = ""


async def claim_due_followups() -> list[uuid.UUID]:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        await db.execute(
            update(MentionFollowup)
            .where(
                MentionFollowup.status == MentionFollowupStatus.PROCESSING,
                MentionFollowup.claimed_at < now - STALE_CLAIM_AFTER,
            )
            .values(status=MentionFollowupStatus.PENDING, claimed_at=None)
        )
        jobs = list(
            (
                await db.scalars(
                    select(MentionFollowup)
                    .where(
                        MentionFollowup.status == MentionFollowupStatus.PENDING,
                        MentionFollowup.due_at <= now,
                    )
                    .order_by(MentionFollowup.due_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in jobs:
            job.status = MentionFollowupStatus.PROCESSING
            job.claimed_at = now
            job.attempt_count += 1
        await db.commit()
        return [job.id for job in jobs]


async def _prepare_job(followup_id: uuid.UUID) -> _FollowupJob | None:
    """Validate the claim, settle everything decidable locally, and snapshot the send.

    The gateway call deliberately happens after this transaction closes. Incoming
    Zalo events acknowledge these very rows, and a lock held across a multi-second
    HTTP call blocks that acknowledgement until the gateway stops retrying — which
    silently turns an answered reminder into an endless one.
    """
    async with SessionLocal() as db:
        followup = await db.scalar(
            select(MentionFollowup)
            .options(
                selectinload(MentionFollowup.automation).selectinload(MentionAutomation.group)
            )
            .where(MentionFollowup.id == followup_id)
        )
        if followup is None or followup.status != MentionFollowupStatus.PROCESSING:
            return None
        automation = followup.automation
        group = automation.group
        now = datetime.now(UTC)

        if not automation.enabled or not group.is_available:
            followup.status = MentionFollowupStatus.CANCELLED
            followup.claimed_at = None
            followup.processed_at = now
            await db.commit()
            return None

        if len(followup.target_user_ids) != len(followup.target_display_names):
            followup.status = MentionFollowupStatus.FAILED
            followup.claimed_at = None
            followup.processed_at = now
            followup.error_message = "Danh sách người cần tag bị lỗi dữ liệu."
            await db.commit()
            logger.error("MENTION_FOLLOWUP_CORRUPT followup_id=%s", followup_id)
            return None

        allowed_at = next_allowed_at(now, automation.active_windows)
        if allowed_at > now:
            followup.status = MentionFollowupStatus.PENDING
            followup.due_at = allowed_at
            followup.claimed_at = None
            followup.attempt_count = 0
            await db.commit()
            return None

        # One customer owns exactly one group; delivery logs hang off the customer.
        customer_id = await db.scalar(
            select(Customer.id).where(Customer.zalo_group_id == group.id)
        )
        return _FollowupJob(
            followup_id=followup.id,
            claimed_at=followup.claimed_at,
            zalo_group_id=group.zalo_group_id,
            customer_id=customer_id,
            customer_name=group.name,
            delay_minutes=automation.delay_minutes,
            active_windows=list(automation.active_windows),
            idempotency_key=f"mention:{followup.id}:{followup.due_at.isoformat()}",
            targets=[
                {"user_id": user_id, "display_name": display_name}
                for user_id, display_name in zip(
                    followup.target_user_ids,
                    followup.target_display_names,
                    strict=True,
                )
            ],
        )


async def _reload_claim(db: AsyncSession, job: _FollowupJob) -> MentionFollowup | None:
    """Re-read the row and confirm nobody took the claim over while we were sending."""
    followup = await db.get(MentionFollowup, job.followup_id)
    if followup is None:
        return None
    if (
        followup.status != MentionFollowupStatus.PROCESSING
        or followup.claimed_at != job.claimed_at
    ):
        logger.warning("MENTION_FOLLOWUP_CLAIM_LOST followup_id=%s", job.followup_id)
        return None
    return followup


async def _log_delivery(
    db: AsyncSession,
    customer_id: uuid.UUID | None,
    status: DeliveryStatus,
    *,
    zalo_message_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    if customer_id is None:
        logger.warning("MENTION_DELIVERY_LOG_SKIPPED reason=customer_not_found")
        return
    await add_delivery_log(
        db,
        customer_id,
        DeliveryType.MENTION_AUTOMATION,
        status,
        zalo_message_id=zalo_message_id,
        error_code=error_code,
        error_message=error_message,
    )


def _alert_context(job: _FollowupJob) -> dict[str, str]:
    context = {"Khách hàng": job.customer_name, "Nhóm Zalo": job.zalo_group_id}
    if job.customer_id is not None:
        context["Xem tại"] = customer_link(job.customer_id)
    return context


async def _gateway_ready() -> tuple[bool, str]:
    """Mention follow-ups are only safe to send while replies/reactions are observable."""
    try:
        state = await zalo_gateway.get_status()
    except GatewayError as exc:
        return False, exc.message
    if state.get("status") != BotStatus.CONNECTED.value:
        return False, "Bot Zalo chưa kết nối nên chưa thể tag lại."
    if not state.get("events_healthy", True):
        return False, (
            "Gateway đang mất kênh sự kiện Zalo nên không nhận biết được khách đã phản hồi."
        )
    return True, ""


async def _postpone(job: _FollowupJob, reason: str, delay: timedelta) -> None:
    async with SessionLocal() as db:
        followup = await _reload_claim(db, job)
        if followup is None:
            return
        followup.status = MentionFollowupStatus.PENDING
        followup.due_at = next_allowed_at(datetime.now(UTC) + delay, job.active_windows)
        followup.claimed_at = None
        followup.attempt_count = 0
        followup.error_message = reason
        await db.commit()
    await report_async(
        "MENTION_FOLLOWUP_POSTPONED",
        f"Tag tên tự động đang tạm dừng: {reason}",
        severity=Severity.WARNING,
        service="celery-worker",
        context=_alert_context(job),
    )


async def _record_success(job: _FollowupJob, message_id: str | None) -> None:
    async with SessionLocal() as db:
        followup = await _reload_claim(db, job)
        if followup is None:
            return
        await _log_delivery(
            db, job.customer_id, DeliveryStatus.SENT, zalo_message_id=message_id
        )
        next_due_at = next_allowed_at(
            datetime.now(UTC) + timedelta(minutes=job.delay_minutes),
            job.active_windows,
        )
        followup.status = MentionFollowupStatus.PENDING
        followup.due_at = next_due_at
        followup.claimed_at = None
        followup.attempt_count = 0
        followup.send_count += 1
        followup.sent_message_id = message_id
        followup.processed_at = None
        followup.error_message = None
        await db.commit()
        logger.info(
            "MENTION_FOLLOWUP_SENT followup_id=%s next_due_at=%s",
            followup.id,
            next_due_at.isoformat(),
        )


async def _record_failure(job: _FollowupJob, code: str, message: str) -> None:
    async with SessionLocal() as db:
        followup = await _reload_claim(db, job)
        if followup is None:
            return
        await _log_delivery(
            db,
            job.customer_id,
            DeliveryStatus.FAILED,
            error_code=code,
            error_message=message,
        )
        followup.error_message = message
        followup.claimed_at = None
        if followup.attempt_count < MAX_ATTEMPTS:
            followup.status = MentionFollowupStatus.PENDING
            followup.due_at = next_allowed_at(
                datetime.now(UTC) + RETRY_DELAY, job.active_windows
            )
        else:
            followup.status = MentionFollowupStatus.FAILED
            followup.processed_at = datetime.now(UTC)
        exhausted = followup.status == MentionFollowupStatus.FAILED
        await db.commit()
        logger.warning(
            "MENTION_FOLLOWUP_FAILED followup_id=%s attempt=%d code=%s",
            followup.id,
            followup.attempt_count,
            code,
        )
    await report_async(
        "MENTION_FOLLOWUP_FAILED" if exhausted else "MENTION_FOLLOWUP_RETRY",
        (
            f"Tag tên tự động thất bại hẳn sau {MAX_ATTEMPTS} lần thử: {message}"
            if exhausted
            else f"Tag tên tự động lỗi, sẽ thử lại: {message}"
        ),
        severity=Severity.ERROR if exhausted else Severity.WARNING,
        service="celery-worker",
        context={**_alert_context(job), "Mã lỗi gốc": code},
    )


async def process_followup(followup_id: uuid.UUID) -> None:
    job = await _prepare_job(followup_id)
    if job is None:
        return

    ready, reason = await _gateway_ready()
    if not ready:
        logger.warning(
            "MENTION_FOLLOWUP_POSTPONED followup_id=%s reason=%s", job.followup_id, reason
        )
        await _postpone(job, reason, EVENTS_DOWN_DELAY)
        return

    try:
        result = await zalo_gateway.send_mention(
            job.zalo_group_id,
            job.targets,
            idempotency_key=job.idempotency_key,
        )
    except GatewayError as exc:
        await _record_failure(job, exc.code, exc.message)
        return
    await _record_success(job, str(result.get("message_id") or "") or None)
