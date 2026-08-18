from app.celery_app import celery_app
from app.services.log_retention import purge_expired_delivery_logs
from app.tasks.async_utils import run_async


@celery_app.task(
    name="zbridge.maintenance.purge_expired_delivery_logs",
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def purge_delivery_logs() -> None:
    run_async(purge_expired_delivery_logs())
