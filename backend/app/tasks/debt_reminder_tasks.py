import uuid

from app.celery_app import celery_app
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
