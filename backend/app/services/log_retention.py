import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import SessionLocal
from app.models import (
    BotDeliveryLog,
    DebtReminderRun,
    DriveConversionJob,
    MentionContextMessage,
    MentionFollowup,
    ModelCallLog,
)
from app.models.entities import (
    DebtReminderStatus,
    DriveConversionJobStatus,
    MentionFollowupStatus,
)

logger = logging.getLogger(__name__)

ACTIVITY_LOG_RETENTION_DAYS = 7
DEBT_REMINDER_RUN_RETENTION_DAYS = 45
DRIVE_CONVERSION_JOB_RETENTION_DAYS = 45


async def delete_expired_delivery_logs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=ACTIVITY_LOG_RETENTION_DAYS)
    debt_cutoff = reference - timedelta(days=DEBT_REMINDER_RUN_RETENTION_DAYS)
    drive_cutoff = reference - timedelta(days=DRIVE_CONVERSION_JOB_RETENTION_DAYS)
    result = await db.execute(
        delete(BotDeliveryLog).where(BotDeliveryLog.created_at < cutoff)
    )
    await db.execute(
        delete(DebtReminderRun).where(
            DebtReminderRun.processed_at < debt_cutoff,
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
                    MentionFollowupStatus.SKIPPED,
                    MentionFollowupStatus.CANCELLED,
                ]
            ),
        )
    )
    # Folder registrations are configuration and stay. Finished scan/conversion
    # jobs are transient history; deleting a job cascades to its discovered item
    # rows and prevents file metadata from accumulating forever.
    await db.execute(
        delete(DriveConversionJob).where(
            DriveConversionJob.finished_at < drive_cutoff,
            DriveConversionJob.status.in_(
                [
                    DriveConversionJobStatus.COMPLETED,
                    DriveConversionJobStatus.FAILED,
                ]
            ),
        )
    )
    await db.commit()
    return result.rowcount or 0


async def delete_expired_model_call_logs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=ACTIVITY_LOG_RETENTION_DAYS)
    result = await db.execute(
        delete(ModelCallLog).where(ModelCallLog.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def delete_expired_mention_context(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(
        hours=settings.mention_context_retention_hours
    )
    active_source = exists(
        select(MentionFollowup.id).where(
            MentionFollowup.automation_id == MentionContextMessage.automation_id,
            MentionFollowup.source_message_id == MentionContextMessage.message_id,
            MentionFollowup.status.in_(
                {
                    MentionFollowupStatus.CLASSIFYING,
                    MentionFollowupStatus.PENDING,
                    MentionFollowupStatus.PROCESSING,
                }
            ),
        )
    )
    result = await db.execute(
        delete(MentionContextMessage).where(
            MentionContextMessage.sent_at < cutoff,
            ~active_source,
        )
    )
    await db.commit()
    return result.rowcount or 0


async def purge_expired_delivery_logs() -> int:
    async with SessionLocal() as db:
        deleted_count = await delete_expired_delivery_logs(db)
        deleted_model_calls = await delete_expired_model_call_logs(db)

    logger.info(
        "Activity log retention completed: retention_days=%d "
        "debt_retention_days=%d drive_retention_days=%d "
        "delivery_deleted=%d model_calls_deleted=%d",
        ACTIVITY_LOG_RETENTION_DAYS,
        DEBT_REMINDER_RUN_RETENTION_DAYS,
        DRIVE_CONVERSION_JOB_RETENTION_DAYS,
        deleted_count,
        deleted_model_calls,
    )
    return deleted_count


async def purge_expired_mention_context() -> int:
    async with SessionLocal() as db:
        deleted_count = await delete_expired_mention_context(db)
    logger.info(
        "Mention context retention completed: retention_hours=%d deleted=%d",
        settings.mention_context_retention_hours,
        deleted_count,
    )
    return deleted_count
