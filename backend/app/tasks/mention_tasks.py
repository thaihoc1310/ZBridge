import uuid
from datetime import datetime

from app.celery_app import celery_app
from app.services.mention_classifier import (
    claim_pending_classifications,
    process_classification,
)
from app.services.mention_scheduler import claim_due_followups, process_followup
from app.tasks.async_utils import run_async


@celery_app.task(name="zbridge.mentions.dispatch_due", ignore_result=True)
def dispatch_due_followups() -> None:
    for followup_id in run_async(claim_due_followups()):
        process_mention_followup.delay(str(followup_id))


@celery_app.task(name="zbridge.mentions.dispatch_classifications", ignore_result=True)
def dispatch_classifications() -> None:
    for followup_id, claimed_at in run_async(claim_pending_classifications()):
        process_mention_classification.delay(str(followup_id), claimed_at.isoformat())


@celery_app.task(name="zbridge.mentions.classify", ignore_result=True)
def process_mention_classification(followup_id: str, claimed_at: str) -> None:
    # The service itself always fails open to PENDING when OpenAI is unavailable.
    run_async(
        process_classification(uuid.UUID(followup_id), datetime.fromisoformat(claimed_at))
    )


@celery_app.task(
    name="zbridge.mentions.process_followup",
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_mention_followup(followup_id: str) -> None:
    run_async(process_followup(uuid.UUID(followup_id)))
