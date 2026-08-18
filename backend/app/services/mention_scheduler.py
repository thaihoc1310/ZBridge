import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.models import MentionAutomation, MentionFollowup
from app.models.entities import DeliveryStatus, DeliveryType, MentionFollowupStatus
from app.services.delivery_service import add_delivery_log
from app.services.mention_time_windows import next_allowed_at
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.mention_scheduler")


async def claim_due_followups() -> list[uuid.UUID]:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        await db.execute(
            update(MentionFollowup)
            .where(
                MentionFollowup.status == MentionFollowupStatus.PROCESSING,
                MentionFollowup.claimed_at < now - timedelta(minutes=10),
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


async def process_followup(followup_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        followup = await db.scalar(
            select(MentionFollowup)
            .options(selectinload(MentionFollowup.automation).selectinload(MentionAutomation.group))
            .where(MentionFollowup.id == followup_id)
            .with_for_update()
        )
        if followup is None or followup.status != MentionFollowupStatus.PROCESSING:
            return
        automation = followup.automation
        if not automation.enabled or not automation.group.is_available:
            followup.status = MentionFollowupStatus.CANCELLED
            followup.processed_at = datetime.now(UTC)
            await db.commit()
            return
        now = datetime.now(UTC)
        allowed_at = next_allowed_at(now, automation.active_windows)
        if allowed_at > now:
            followup.status = MentionFollowupStatus.PENDING
            followup.due_at = allowed_at
            followup.claimed_at = None
            followup.attempt_count = 0
            await db.commit()
            return
        targets = [
            {"user_id": user_id, "display_name": display_name}
            for user_id, display_name in zip(
                followup.target_user_ids, followup.target_display_names, strict=True
            )
        ]
        try:
            result = await zalo_gateway.send_mention(automation.group.zalo_group_id, targets)
            sent_message_id = str(result.get("message_id") or "") or None
            await add_delivery_log(
                db,
                automation.group.id,
                DeliveryType.MENTION_AUTOMATION,
                DeliveryStatus.SENT,
                zalo_message_id=sent_message_id,
            )
            next_due_at = next_allowed_at(
                datetime.now(UTC) + timedelta(minutes=automation.delay_minutes),
                automation.active_windows,
            )
            followup.status = MentionFollowupStatus.PENDING
            followup.due_at = next_due_at
            followup.claimed_at = None
            followup.attempt_count = 0
            followup.sent_message_id = sent_message_id
            followup.processed_at = None
            followup.error_message = None
            logger.info(
                "MENTION_FOLLOWUP_SENT followup_id=%s next_due_at=%s",
                followup.id,
                next_due_at.isoformat(),
            )
        except GatewayError as exc:
            await add_delivery_log(
                db,
                automation.group.id,
                DeliveryType.MENTION_AUTOMATION,
                DeliveryStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            followup.error_message = exc.message
            if followup.attempt_count < 3:
                followup.status = MentionFollowupStatus.PENDING
                followup.due_at = next_allowed_at(
                    datetime.now(UTC) + timedelta(minutes=5),
                    automation.active_windows,
                )
                followup.claimed_at = None
            else:
                followup.status = MentionFollowupStatus.FAILED
                followup.processed_at = datetime.now(UTC)
            logger.warning(
                "MENTION_FOLLOWUP_FAILED followup_id=%s attempt=%d code=%s",
                followup.id,
                followup.attempt_count,
                exc.code,
            )
        await db.commit()
