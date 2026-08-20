import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import SessionLocal
from app.models import BotDeliveryLog, DebtReminderRun, MentionFollowup
from app.models.entities import DebtReminderStatus, MentionFollowupStatus

logger = logging.getLogger(__name__)

DELIVERY_LOG_RETENTION_DAYS = 30


async def delete_expired_delivery_logs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=DELIVERY_LOG_RETENTION_DAYS)
    result = await db.execute(
        delete(BotDeliveryLog).where(BotDeliveryLog.created_at < cutoff)
    )
    await db.execute(
        delete(DebtReminderRun).where(
            DebtReminderRun.processed_at < cutoff,
            DebtReminderRun.status.in_(
                [
                    DebtReminderStatus.SENT,
                    DebtReminderStatus.FAILED,
                    DebtReminderStatus.SKIPPED,
                    DebtReminderStatus.CANCELLED,
                ]
            ),
        )
    )
    # Follow-ups in a terminal state only: PENDING/PROCESSING rows are live loops
    # still waiting for the customer to reply.
    await db.execute(
        delete(MentionFollowup).where(
            MentionFollowup.processed_at < cutoff,
            MentionFollowup.status.in_(
                [
                    MentionFollowupStatus.SENT,
                    MentionFollowupStatus.FAILED,
                    MentionFollowupStatus.CANCELLED,
                ]
            ),
        )
    )
    await db.commit()
    return result.rowcount or 0


async def purge_expired_delivery_logs() -> int:
    async with SessionLocal() as db:
        deleted_count = await delete_expired_delivery_logs(db)

    logger.info(
        "Delivery log retention completed: retention_days=%d deleted=%d",
        DELIVERY_LOG_RETENTION_DAYS,
        deleted_count,
    )
    return deleted_count
