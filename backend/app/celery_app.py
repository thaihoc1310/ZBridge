from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "zbridge",
    broker=settings.redis_url,
    include=[
        "app.tasks.debt_reminder_tasks",
        "app.tasks.maintenance_tasks",
        "app.tasks.mention_tasks",
    ],
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-mention-followups": {
            "task": "zbridge.mentions.dispatch_due",
            "schedule": settings.mention_scheduler_interval_seconds,
        },
        "dispatch-due-debt-reminders": {
            "task": "zbridge.debt_reminders.dispatch_due",
            "schedule": settings.debt_reminder_scheduler_interval_seconds,
        },
        "purge-expired-delivery-logs": {
            "task": "zbridge.maintenance.purge_expired_delivery_logs",
            "schedule": crontab(minute=0, hour=2, day_of_week="monday"),
        },
    },
)
