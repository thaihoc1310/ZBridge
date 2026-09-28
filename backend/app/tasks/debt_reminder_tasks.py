import logging
import uuid

from app.celery_app import celery_app
from app.db.database import SessionLocal
from app.services.debt_payment_service import (
    CLASSIFY_RETRY_DELAYS,
    CLASSIFY_TASK,
    REPLY_RETRY_DELAYS,
    REPLY_TASK,
    classify_confirmation,
    close_abandoned_model_calls,
    expire_stuck_confirmations,
    process_confirmation,
    report_task_error,
)
from app.services.debt_reminder_scheduler import (
    claim_due_debt_reminders,
    process_debt_reminder,
)
from app.tasks.async_utils import run_async

logger = logging.getLogger("zbridge.debt_payment")


@celery_app.task(name="zbridge.debt_reminders.dispatch_due", ignore_result=True)
def dispatch_due_debt_reminders() -> None:
    run_async(_expire_stuck_confirmations())
    for run_id in run_async(claim_due_debt_reminders()):
        process_debt_reminder_task.delay(str(run_id))


@celery_app.task(name="zbridge.debt_reminders.process", ignore_result=True)
def process_debt_reminder_task(run_id: str) -> None:
    run_async(process_debt_reminder(uuid.UUID(run_id)))


async def _deliver_reply(confirmation_id: uuid.UUID, final: bool, attempt: int) -> bool:
    async with SessionLocal() as db:
        return await process_confirmation(
            db, confirmation_id, final=final, attempt=attempt
        )


async def _classify(confirmation_id: uuid.UUID, final: bool, attempt: int) -> bool:
    async with SessionLocal() as db:
        return await classify_confirmation(
            db, confirmation_id, final=final, attempt=attempt
        )


@celery_app.task(name=CLASSIFY_TASK, bind=True, ignore_result=True)
def classify_payment_confirmation(self, confirmation_id: str) -> None:
    """Runs on the `ai` queue, the only worker holding the model API key."""
    attempt = self.request.retries
    final = attempt >= len(CLASSIFY_RETRY_DELAYS)
    try:
        done = run_async(_classify(uuid.UUID(confirmation_id), final, attempt))
    except Exception as exc:
        if final:
            raise
        logger.exception(
            "DEBT_PAYMENT_CONFIRMATION_CLASSIFY_ERROR confirmation_id=%s attempt=%d",
            confirmation_id,
            attempt,
        )
        run_async(_report_task_error(uuid.UUID(confirmation_id), "CLASSIFY", exc, attempt))
        done = False
    if not done and not final:
        raise self.retry(
            countdown=CLASSIFY_RETRY_DELAYS[attempt], max_retries=len(CLASSIFY_RETRY_DELAYS)
        )


async def _expire_stuck_confirmations() -> None:
    # Piggybacks on the reminder tick; a failure here must not stop reminders.
    try:
        async with SessionLocal() as db:
            await expire_stuck_confirmations(db)
            await close_abandoned_model_calls(db)
    except Exception:
        logger.exception("DEBT_PAYMENT_CONFIRMATION_SWEEP_FAILED")


async def _report_task_error(
    confirmation_id: uuid.UUID, stage: str, exc: BaseException, attempt: int
) -> None:
    # Best effort: the alert must not turn a retryable error into a crash.
    try:
        async with SessionLocal() as db:
            await report_task_error(db, confirmation_id, stage, exc, attempt)
    except Exception:
        logger.exception(
            "DEBT_PAYMENT_CONFIRMATION_ALERT_FAILED confirmation_id=%s", confirmation_id
        )


@celery_app.task(name=REPLY_TASK, bind=True, ignore_result=True)
def send_payment_confirmation_reply(self, confirmation_id: str) -> None:
    attempt = self.request.retries
    final = attempt >= len(REPLY_RETRY_DELAYS)
    try:
        delivered = run_async(_deliver_reply(uuid.UUID(confirmation_id), final, attempt))
    except Exception as exc:
        # A DB blip must not end the schedule; on the last attempt it surfaces as a
        # task crash alert, and the stuck-confirmation sweep closes the row.
        if final:
            raise
        logger.exception(
            "DEBT_PAYMENT_CONFIRMATION_TASK_ERROR confirmation_id=%s attempt=%d",
            confirmation_id,
            attempt,
        )
        run_async(_report_task_error(uuid.UUID(confirmation_id), "REPLY", exc, attempt))
        delivered = False
    if not delivered and not final:
        raise self.retry(
            countdown=REPLY_RETRY_DELAYS[attempt], max_retries=len(REPLY_RETRY_DELAYS)
        )
