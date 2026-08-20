import httpx
import pytest

from app.core import alerts as alert_rules
from app.core.errors import AppError, app_error_handler
from app.services import alerting
from app.tasks import alert_tasks


def test_dedup_pattern_keeps_a_flood_readable() -> None:
    """A long outage must stay a handful of messages, not hundreds."""
    fired = [n for n in range(1, 1_501) if alert_rules.should_notify(n)]
    assert fired == [1, 10, 100, 500, 1000, 1500]


def test_notify_from_ignores_a_single_typo() -> None:
    assert not alert_rules.should_notify(4, notify_from=5)
    assert alert_rules.should_notify(5, notify_from=5)
    assert alert_rules.should_notify(14, notify_from=5)


def test_severity_threshold() -> None:
    assert alert_rules.meets_threshold("CRITICAL", "WARNING")
    assert alert_rules.meets_threshold("WARNING", "WARNING")
    assert not alert_rules.meets_threshold("WARNING", "ERROR")
    # An unknown level must not silently disappear.
    assert alert_rules.meets_threshold("nonsense", "ERROR")


def test_message_escapes_html_so_telegram_cannot_break() -> None:
    text = alert_tasks._format(
        code="DEBT_REMINDER_FAILED",
        message="Lỗi <script>alert(1)</script> & thất bại",
        severity="ERROR",
        service="celery-worker",
        context={"customer": "ABC <Accounting>"},
        occurrence=10,
        window_seconds=900,
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "ABC &lt;Accounting&gt;" in text
    assert "DEBT_REMINDER_FAILED" in text
    assert "Lần thứ 10 trong 15 phút qua." in text
    assert text.startswith("🔴 <b>ZBridge · ERROR</b>")


def test_report_never_raises_even_if_the_broker_is_down(monkeypatch) -> None:
    def explode(*_args, **_kwargs):
        raise ConnectionError("redis is gone")

    monkeypatch.setattr(alerting.celery_app, "send_task", explode)
    alerting.report("ANY_CODE", "vẫn phải im lặng")  # must not raise


def _configure(monkeypatch, **overrides) -> list[dict]:
    monkeypatch.setattr(alert_tasks.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(alert_tasks.settings, "telegram_chat_id", "-1")
    monkeypatch.setattr(alert_tasks.settings, "alert_min_severity", "WARNING")
    for key, value in overrides.items():
        monkeypatch.setattr(alert_tasks.settings, key, value)
    sent: list[dict] = []

    def fake_post(url, **kwargs):
        sent.append({"url": url, "json": kwargs.get("json")})
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(alert_tasks.httpx, "post", fake_post)
    return sent


def test_first_occurrence_is_sent(monkeypatch) -> None:
    sent = _configure(monkeypatch)
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 1)

    alert_tasks.send_alert(code="X", message="hỏng rồi", severity="ERROR")

    assert len(sent) == 1
    assert "test-token" in sent[0]["url"]
    assert sent[0]["json"]["chat_id"] == "-1"
    assert sent[0]["json"]["parse_mode"] == "HTML"


def test_suppressed_occurrence_is_not_sent(monkeypatch) -> None:
    sent = _configure(monkeypatch)
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 7)

    alert_tasks.send_alert(code="X", message="hỏng rồi", severity="ERROR")

    assert sent == []


def test_severity_below_threshold_is_dropped(monkeypatch) -> None:
    sent = _configure(monkeypatch, alert_min_severity="ERROR")
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 1)

    alert_tasks.send_alert(code="X", message="chỉ là cảnh báo", severity="WARNING")

    assert sent == []


def test_nothing_is_sent_when_telegram_is_not_configured(monkeypatch) -> None:
    sent = _configure(monkeypatch, telegram_bot_token="")
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 1)

    alert_tasks.send_alert(code="X", message="không có token", severity="CRITICAL")

    assert sent == []


def test_bad_token_is_not_retried_forever(monkeypatch) -> None:
    """A 4xx from Telegram is a config error; retrying can never fix it."""
    _configure(monkeypatch)
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 1)

    def unauthorized(url, **_kwargs):
        return httpx.Response(
            401, json={"description": "Unauthorized"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(alert_tasks.httpx, "post", unauthorized)
    alert_tasks.send_alert(code="X", message="token sai", severity="ERROR")  # no raise


def test_telegram_outage_is_retried(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(alert_tasks, "_occurrence", lambda *_: 1)

    def unavailable(url, **_kwargs):
        return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr(alert_tasks.httpx, "post", unavailable)
    with pytest.raises(httpx.HTTPStatusError):
        alert_tasks.send_alert(code="X", message="telegram sập", severity="ERROR")


class _FakeRequest:
    method = "GET"

    class url:
        path = "/api/customers"


async def test_client_errors_do_not_alert_but_server_errors_do(monkeypatch) -> None:
    reported: list[str] = []

    async def capture(code, _message, **_kwargs):
        reported.append(code)

    monkeypatch.setattr("app.core.errors.report_async", capture)

    await app_error_handler(_FakeRequest(), AppError("CUSTOMER_NOT_FOUND", "không có", 404))
    await app_error_handler(_FakeRequest(), AppError("INVALID_CREDENTIALS", "sai", 401))
    assert reported == []

    await app_error_handler(
        _FakeRequest(), AppError("ZALO_GATEWAY_UNAVAILABLE", "gateway chết", 503)
    )
    assert reported == ["ZALO_GATEWAY_UNAVAILABLE"]


def test_customer_link_points_at_the_customer_page(monkeypatch) -> None:
    monkeypatch.setattr(alerting.settings, "app_url", "https://zbridge.example.com/")
    assert (
        alerting.customer_link("abc-123")
        == "https://zbridge.example.com/customers/abc-123"
    )
    # app_url may hold a CORS list; the first origin is the real app.
    monkeypatch.setattr(
        alerting.settings, "app_url", "https://a.example.com, https://b.example.com"
    )
    assert alerting.customer_link("x") == "https://a.example.com/customers/x"


def test_mention_alert_context_names_the_customer(monkeypatch) -> None:
    import uuid

    from app.services import mention_scheduler

    monkeypatch.setattr(alerting.settings, "app_url", "https://zbridge.example.com")
    customer_id = uuid.uuid4()
    job = mention_scheduler._FollowupJob(
        followup_id=uuid.uuid4(),
        claimed_at=None,
        zalo_group_id="group-9",
        customer_id=customer_id,
        customer_name="ABC — Accounting",
        delay_minutes=60,
        active_windows=[{"start": "00:00", "end": "23:59"}],
        targets=[],
    )

    context = mention_scheduler._alert_context(job)

    assert context["Khách hàng"] == "ABC — Accounting"
    assert context["Xem tại"] == f"https://zbridge.example.com/customers/{customer_id}"


def test_url_context_becomes_a_real_telegram_link() -> None:
    text = alert_tasks._format(
        code="DEBT_REMINDER_FAILED",
        message="hỏng",
        severity="ERROR",
        service="celery-worker",
        context={"Xem tại": "https://zbridge.example.com/customers/abc?a=1&b=2"},
        occurrence=1,
        window_seconds=900,
    )
    assert (
        '<a href="https://zbridge.example.com/customers/abc?a=1&amp;b=2">'
        "Mở trang khách hàng</a>" in text
    )


def test_alert_link_base_url_overrides_app_url(monkeypatch) -> None:
    """APP_URL is usually localhost, which Telegram will not turn into a link."""
    monkeypatch.setattr(alerting.settings, "app_url", "http://localhost:5173")
    monkeypatch.setattr(alerting.settings, "alert_link_base_url", "")
    assert alerting.customer_link("x") == "http://localhost:5173/customers/x"

    monkeypatch.setattr(alerting.settings, "alert_link_base_url", "http://192.168.1.50:5173/")
    assert alerting.customer_link("x") == "http://192.168.1.50:5173/customers/x"
