from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "zbridge",
    broker=settings.redis_url,
    include=[
        "app.tasks.alert_tasks",
        "app.tasks.debt_reminder_tasks",
        "app.tasks.maintenance_tasks",
        "app.tasks.mention_tasks",
    ],
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    # Publishing must fail fast. Kombu otherwise retries the broker connection
    # for ~6s inside the caller, so a Redis outage would add that to every
    # request that tries to raise an alert. Worker consumers are unaffected:
    # they reconnect using broker_connection_max_retries instead.
    broker_connection_timeout=2.0,
    broker_transport_options={"max_retries": 0},
    task_default_queue="celery",
    # Alerts run on their own worker: a blocking Telegram call must never take a
    # slot away from the debt reminders and mention follow-ups it is reporting on.
    task_routes={
        "zbridge.alerts.*": {"queue": "alerts"},
        "zbridge.mentions.classify": {"queue": "ai"},
    },
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    beat_schedule={
        "dispatch-mention-classifications": {
            "task": "zbridge.mentions.dispatch_classifications",
            "schedule": settings.mention_classifier_interval_seconds,
        },
        "dispatch-due-mention-followups": {
            "task": "zbridge.mentions.dispatch_due",
            "schedule": settings.mention_scheduler_interval_seconds,
        },
        "dispatch-due-debt-reminders": {
            "task": "zbridge.debt_reminders.dispatch_due",
            "schedule": settings.debt_reminder_scheduler_interval_seconds,
        },
        "alert-heartbeat": {
            "task": "zbridge.alerts.heartbeat",
            "schedule": settings.alert_heartbeat_interval_seconds,
        },
        "purge-expired-delivery-logs": {
            "task": "zbridge.maintenance.purge_expired_delivery_logs",
            "schedule": crontab(minute=0, hour=2, day_of_week="monday"),
        },
        "purge-expired-mention-context": {
            "task": "zbridge.maintenance.purge_expired_mention_context",
            "schedule": crontab(minute=20, hour="*"),
        },
    },
)
