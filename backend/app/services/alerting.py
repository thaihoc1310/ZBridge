"""Queue operator alerts without ever disturbing the caller.

Alerts go through the existing Celery worker rather than being sent inline: a
slow or rate-limited Telegram must never add latency to a request, and Celery
already gives the delivery its own retries.
"""

import asyncio
import functools
import logging
from typing import Any

from app.celery_app import celery_app
from app.core.alerts import Severity
from app.core.config import settings

logger = logging.getLogger("zbridge.alerting")

ALERT_TASK = "zbridge.alerts.send"


def customer_link(customer_id: object) -> str:
    """Deep link so an alert can be acted on without hunting for the customer."""
    base = (settings.alert_link_base_url or settings.app_url).split(",")[0]
    return f"{base.strip().rstrip('/')}/customers/{customer_id}"


def report(
    code: str,
    message: str,
    *,
    severity: Severity | str = Severity.ERROR,
    service: str = "backend",
    context: dict[str, Any] | None = None,
    dedup_key: str | None = None,
    notify_from: int = 1,
    window_seconds: int | None = None,
) -> None:
    """Enqueue an alert. Swallows every failure by design."""
    try:
        celery_app.send_task(
            ALERT_TASK,
            kwargs={
                "code": code,
                "message": message,
                "severity": str(severity),
                "service": service,
                "context": {key: str(value) for key, value in (context or {}).items()},
                "dedup_key": dedup_key or f"{service}:{code}",
                "notify_from": notify_from,
                "window_seconds": window_seconds,
            },
            retry=False,
        )
    except Exception:
        logger.exception("ALERT_ENQUEUE_FAILED code=%s", code)


async def report_async(*args: Any, **kwargs: Any) -> None:
    """Same as :func:`report` but keeps the event loop free of broker I/O."""
    await asyncio.to_thread(functools.partial(report, *args, **kwargs))
