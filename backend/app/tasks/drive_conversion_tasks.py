import uuid

from app.celery_app import celery_app
from app.services.drive_conversion_service import process_conversion_job, scan_conversion_job
from app.tasks.async_utils import run_async


@celery_app.task(name="zbridge.drive.scan", ignore_result=True, acks_late=True)
def scan_drive_folder_task(job_id: str) -> None:
    run_async(scan_conversion_job(uuid.UUID(job_id)))


@celery_app.task(
    name="zbridge.drive.convert",
    ignore_result=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_drive_conversion_task(job_id: str) -> None:
    run_async(process_conversion_job(uuid.UUID(job_id)))
