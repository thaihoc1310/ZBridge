import uuid

from app.celery_app import celery_app
from app.db.database import SessionLocal
from app.services.debt_payment_service import (
    REPLY_RETRY_DELAYS,
    REPLY_TASK,
    process_confirmation,
)
from app.services.debt_reminder_scheduler import (
    claim_due_debt_reminders,
    process_debt_reminder,
)
from app.tasks.async_utils import run_async


@celery_app.task(name="zbridge.debt_reminders.dispatch_due", ignore_result=True)
def dispatch_due_debt_reminders() -> None:
    for run_id in run_async(claim_due_debt_reminders()):
        process_debt_reminder_task.delay(str(run_id))


@celery_app.task(name="zbridge.debt_reminders.process", ignore_result=True)
def process_debt_reminder_task(run_id: str) -> None:
    run_async(process_debt_reminder(uuid.UUID(run_id)))


async def _deliver_reply(confirmation_id: uuid.UUID, final: bool) -> bool:
    async with SessionLocal() as db:
        return await process_confirmation(db, confirmation_id, final=final)


@celery_app.task(name=REPLY_TASK, bind=True, ignore_result=True)
def send_payment_confirmation_reply(self, confirmation_id: str) -> None:
    next_retry = self.request.retries + 1
    final = next_retry >= len(REPLY_RETRY_DELAYS)
    if not run_async(_deliver_reply(uuid.UUID(confirmation_id), final)) and not final:
        raise self.retry(
            countdown=REPLY_RETRY_DELAYS[next_retry], max_retries=len(REPLY_RETRY_DELAYS)
        )
