import html
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import redis
from celery.signals import task_failure

from app.celery_app import celery_app
from app.core.alerts import ICONS, coerce, meets_threshold, should_notify
from app.core.config import settings

logger = logging.getLogger("zbridge.alerts")

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
ALERT_TASK_NAME = "zbridge.alerts.send"
TELEGRAM_MAX_LENGTH = 4096
#: Every URL we emit today is a customer page; give a new link type its own label.
LINK_TEXT = "Mở trang khách hàng"


def _occurrence(dedup_key: str, window_seconds: int) -> int:
    """How many times this problem was reported inside the current window.

    Fails open (returns 1) so a Redis problem produces a duplicate alert rather
    than silence.
    """
    try:
        client = redis.Redis.from_url(
            settings.redis_url, socket_timeout=5, socket_connect_timeout=5
        )
        key = f"zbridge:alert:{dedup_key}"
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, window_seconds)
        return count
    except Exception:
        logger.warning("ALERT_DEDUP_UNAVAILABLE dedup_key=%s", dedup_key)
        return 1


def _format(
    code: str,
    message: str,
    severity: str,
    service: str,
    context: dict[str, Any],
    occurrence: int,
    window_seconds: int,
) -> str:
    level = coerce(severity)
    stamp = datetime.now(UTC).astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S")
    lines = [
        f"{ICONS[level]} <b>ZBridge · {level.value}</b>",
        f"<b>Mã lỗi:</b> <code>{html.escape(code)}</code>",
        html.escape(message),
        "",
        f"<b>Nguồn:</b> {html.escape(service)}",
    ]
    for key, value in context.items():
        label = html.escape(str(key))
        text = str(value)
        if text.startswith(("http://", "https://")):
            # Telegram only turns this into a real link when the host has a TLD or
            # is an IP address; a localhost URL is stripped back to plain text.
            href = html.escape(text, quote=True)
            lines.append(f'<b>{label}:</b> <a href="{href}">{html.escape(LINK_TEXT)}</a>')
        else:
            lines.append(f"<b>{label}:</b> {html.escape(text)}")
    lines.append(f"<b>Lúc:</b> {stamp} (giờ VN)")
    if occurrence > 1:
        lines.append(
            f"<i>Lần thứ {occurrence} trong {window_seconds // 60} phút qua.</i>"
        )
    return "\n".join(lines)[:TELEGRAM_MAX_LENGTH]


@celery_app.task(
    name=ALERT_TASK_NAME,
    ignore_result=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_alert(
    *,
    code: str,
    message: str,
    severity: str = "ERROR",
    service: str = "backend",
    context: dict[str, Any] | None = None,
    dedup_key: str | None = None,
    notify_from: int = 1,
    window_seconds: int | None = None,
) -> None:
    if not meets_threshold(severity, settings.alert_min_severity):
        return
    if not settings.telegram_enabled:
        logger.warning("ALERT_DROPPED telegram_not_configured code=%s", code)
        return

    window = window_seconds or settings.alert_dedup_window_seconds
    occurrence = _occurrence(dedup_key or f"{service}:{code}", window)
    if not should_notify(occurrence, notify_from=notify_from):
        return

    response = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={
            "chat_id": settings.telegram_chat_id,
            "text": _format(
                code, message, severity, service, context or {}, occurrence, window
            ),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=settings.telegram_timeout_seconds,
    )
    if response.is_error:
        # A 4xx means the token or chat id is wrong; retrying cannot fix that.
        if 400 <= response.status_code < 500 and response.status_code != 429:
            logger.error(
                "ALERT_REJECTED status=%d body=%s", response.status_code, response.text[:300]
            )
            return
        response.raise_for_status()
    logger.info(
        "ALERT_SENT code=%s severity=%s occurrence=%d", code, severity, occurrence
    )


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, **_kwargs) -> None:
    """Catch-all for tasks that died with an unhandled exception."""
    name = getattr(sender, "name", "unknown")
    if name == ALERT_TASK_NAME:
        return  # never let alert delivery failures alert about themselves
    send_alert.delay(
        code="CELERY_TASK_CRASHED",
        message=f"Tác vụ nền {name} lỗi không xử lý được: {exception}",
        severity="CRITICAL",
        service="celery-worker",
        context={"task": name, "task_id": str(task_id)},
        dedup_key=f"celery:{name}",
    )


@celery_app.task(name="zbridge.alerts.heartbeat", ignore_result=True)
def heartbeat() -> None:
    """Watch the API from outside it.

    A crashed backend logs nothing, so nothing would ever be reported. Beat and
    this worker do not depend on the backend, which lets them notice its absence.
    """
    try:
        response = httpx.get(settings.health_check_url, timeout=10.0)
        response.raise_for_status()
        health = response.json()
    except Exception as exc:
        send_alert(
            code="BACKEND_UNREACHABLE",
            message=f"Backend không phản hồi health check: {exc}",
            severity="CRITICAL",
            service="heartbeat",
        )
        return

    if health.get("database") != "UP":
        send_alert(
            code="DATABASE_DOWN",
            message="Backend không kết nối được cơ sở dữ liệu.",
            severity="CRITICAL",
            service="heartbeat",
        )
    if health.get("zalo_gateway") == "DOWN":
        send_alert(
            code="GATEWAY_DOWN",
            message="Backend không liên lạc được Zalo Gateway.",
            severity="ERROR",
            service="heartbeat",
        )
    elif health.get("zalo") != "CONNECTED":
        send_alert(
            code="ZALO_BOT_NOT_CONNECTED",
            message=f"Tài khoản bot Zalo đang ở trạng thái {health.get('zalo') or 'UNKNOWN'}.",
            severity="CRITICAL",
            service="heartbeat",
        )
    elif not health.get("events_healthy"):
        send_alert(
            code="ZALO_EVENTS_UNHEALTHY",
            message=(
                "Kênh nhận phản hồi Zalo không khỏe; tag tự động đang tạm dừng. "
                f"Listener={health.get('listener_status') or 'UNKNOWN'}, "
                f"backlog={health.get('event_backlog') or 0}."
            ),
            severity="ERROR",
            service="heartbeat",
        )
