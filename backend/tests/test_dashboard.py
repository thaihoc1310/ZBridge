import asyncio
import time as time_module
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dashboard as dashboard_api
from app.api.dashboard import dashboard
from app.db.database import Base
from app.models import (
    BotDeliveryLog,
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionClassifierSettings,
    MentionFollowup,
    ModelCallLog,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    DebtReminderStatus,
    DeliveryStatus,
    DeliveryType,
    MentionFollowupStatus,
    MentionFollowupTrigger,
    ModelCallStatus,
)
from app.services.zalo_gateway_client import GatewayError

VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
SENT = DeliveryStatus.SENT
FAILED = DeliveryStatus.FAILED


def _log(
    customer: Customer,
    status: DeliveryStatus,
    created_at: datetime,
    delivery_type: DeliveryType = DeliveryType.MANUAL_MESSAGE,
) -> BotDeliveryLog:
    return BotDeliveryLog(
        customer_id=customer.id,
        type=delivery_type,
        status=status,
        created_at=created_at,
    )


def _model_call(
    customer: Customer,
    *,
    outcome: str,
    latency_ms: int,
    created_at: datetime,
    status: ModelCallStatus = ModelCallStatus.SUCCEEDED,
) -> ModelCallLog:
    return ModelCallLog(
        customer_id=customer.id,
        customer_name="Khach",
        trigger=MentionFollowupTrigger.MENTION,
        provider="fptcloud",
        model="DeepSeek-V4-Flash",
        request_payload={},
        status=status,
        outcome=outcome,
        input_tokens=10,
        output_tokens=4,
        latency_ms=latency_ms,
        created_at=created_at,
    )


async def test_dashboard_returns_debt_split_and_sent_messages_by_local_hour(
    monkeypatch,
) -> None:
    _silence_gateway(monkeypatch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    local_now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    first_sent = local_now.replace(minute=5, second=0, microsecond=0).astimezone(UTC)
    second_sent = local_now.replace(minute=35, second=0, microsecond=0).astimezone(UTC)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customers: list[Customer] = []
        for index, has_debt in enumerate((True, False)):
            group = ZaloGroup(
                zalo_account_id=account.id,
                zalo_group_id=f"dashboard-group-{index}",
                name=f"Khách {index}",
                member_count=3,
                is_available=True,
                last_synced_at=local_now.astimezone(UTC),
            )
            db.add(group)
            await db.flush()
            customer = Customer(zalo_group_id=group.id, has_debt=has_debt)
            db.add(customer)
            customers.append(customer)
        await db.flush()
        db.add_all(
            [
                BotDeliveryLog(
                    customer_id=customers[0].id,
                    type=DeliveryType.MENTION_AUTOMATION,
                    status=DeliveryStatus.SENT,
                    created_at=first_sent,
                ),
                BotDeliveryLog(
                    customer_id=customers[1].id,
                    type=DeliveryType.DEBT_REMINDER_MESSAGE,
                    status=DeliveryStatus.SENT,
                    created_at=second_sent,
                ),
                BotDeliveryLog(
                    customer_id=customers[0].id,
                    type=DeliveryType.MANUAL_MESSAGE,
                    status=DeliveryStatus.FAILED,
                    created_at=second_sent,
                ),
                BotDeliveryLog(
                    customer_id=customers[0].id,
                    type=DeliveryType.MANUAL_MESSAGE,
                    status=DeliveryStatus.SENT,
                    created_at=first_sent - timedelta(days=1),
                ),
            ]
        )
        await db.commit()

        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.customer_count == 2
    assert result.customers_with_debt == 1
    assert result.customers_without_debt == 1
    assert result.messages_today == 2
    assert result.failed_today == 1
    assert len(result.messages_by_hour) == 24
    assert result.messages_by_hour[local_now.hour].count == 2
    assert sum(point.count for point in result.messages_by_hour) == 2
    await engine.dispose()


# --- Shared fixture for the richer dashboard figures -----------------------


async def _dashboard_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _local_midnight(offset_days: int = 0) -> datetime:
    """Start of a Vietnam-local day, as UTC, offset from today."""
    local_today = datetime.now(VIETNAM).date() + timedelta(days=offset_days)
    return datetime.combine(local_today, time(0, 0), tzinfo=VIETNAM).astimezone(UTC)


def _local_at(offset_days: int, hour: int, minute: int = 0) -> datetime:
    local_day = datetime.now(VIETNAM).date() + timedelta(days=offset_days)
    return datetime.combine(local_day, time(hour, minute), tzinfo=VIETNAM).astimezone(UTC)


async def _seed_customer(
    db,
    account: ZaloAccount,
    *,
    name: str,
    has_debt: bool = False,
    debt_file_url: str | None = "https://docs.google.com/spreadsheets/d/x/edit",
    is_available: bool = True,
) -> Customer:
    group = ZaloGroup(
        zalo_account_id=account.id,
        zalo_group_id=f"group-{name}",
        name=name,
        member_count=3,
        is_available=is_available,
        last_synced_at=datetime.now(UTC),
    )
    db.add(group)
    await db.flush()
    customer = Customer(
        zalo_group_id=group.id, has_debt=has_debt, debt_file_url=debt_file_url
    )
    db.add(customer)
    await db.flush()
    return customer


def _silence_gateway(monkeypatch, value: bool | None = True) -> None:
    async def probe() -> bool | None:
        return value

    monkeypatch.setattr(dashboard_api, "gateway_events_healthy", probe)


async def test_seven_day_trend_covers_retention_and_excludes_older_logs(
    monkeypatch,
) -> None:
    """The trend window matches delivery-log retention exactly.

    A day-8 row must not appear: retention deletes it, and plotting it would
    render a decline that is only the purge running.
    """
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="Trend")
        db.add_all(
            [
                _log(customer, DeliveryStatus.SENT, _local_at(0, 9)),
                _log(customer, DeliveryStatus.SENT, _local_at(0, 10)),
                _log(customer, DeliveryStatus.FAILED, _local_at(0, 11)),
                _log(customer, DeliveryStatus.SENT, _local_at(-1, 8)),
                _log(customer, DeliveryStatus.SENT, _local_at(-1, 9)),
                _log(customer, DeliveryStatus.SENT, _local_at(-6, 8)),
                # Outside the window on purpose.
                _log(customer, DeliveryStatus.SENT, _local_at(-8, 8)),
            ]
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert len(result.daily_messages) == 7
    assert result.daily_messages[-1].sent == 2
    assert result.daily_messages[-1].failed == 1
    assert result.daily_messages[-2].sent == 2
    assert result.daily_messages[0].sent == 1, "ngay thu 7 phai nam trong cua so"
    assert sum(day.sent for day in result.daily_messages) == 5, "log 8 ngay truoc bi lot"
    assert result.messages_yesterday == 2
    # Oldest first, one entry per calendar day, no gaps.
    dates = [day.date for day in result.daily_messages]
    assert dates == sorted(dates)
    assert len(set(dates)) == 7
    await engine.dispose()


async def test_todays_messages_are_broken_down_by_feature(monkeypatch) -> None:
    """"3 failed" is only actionable once you know which feature failed."""
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="Types")
        db.add_all(
            [
                _log(customer, SENT, _local_at(0, 9), DeliveryType.DEBT_REMINDER_IMAGE),
                _log(customer, SENT, _local_at(0, 9), DeliveryType.DEBT_REMINDER_LINK),
                _log(customer, SENT, _local_at(0, 9), DeliveryType.DEBT_REMINDER_MESSAGE),
                _log(customer, SENT, _local_at(0, 10), DeliveryType.MENTION_AUTOMATION),
                _log(customer, SENT, _local_at(0, 11), DeliveryType.MANUAL_MESSAGE),
                # Failures are counted separately, never in the breakdown.
                _log(customer, FAILED, _local_at(0, 11), DeliveryType.MANUAL_MESSAGE),
            ]
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.messages_by_type_today == {"debt": 3, "mention": 1, "manual": 1}
    assert result.messages_today == 5
    assert result.failed_today == 1
    await engine.dispose()


async def test_failed_today_is_bounded_at_both_ends(monkeypatch) -> None:
    """failed_today used to have no upper bound while messages_today did."""
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="Bounds")
        db.add_all(
            [
                _log(customer, DeliveryStatus.FAILED, _local_at(0, 12)),
                _log(customer, DeliveryStatus.FAILED, _local_at(1, 12)),
                _log(customer, DeliveryStatus.FAILED, _local_at(-1, 12)),
            ]
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.failed_today == 1, "chi dem that bai trong hom nay"
    await engine.dispose()


async def test_upcoming_reminders_list_todays_work_in_order(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        overdue = await _seed_customer(db, account, name="Qua han", has_debt=True)
        later = await _seed_customer(db, account, name="Sap toi", has_debt=True)
        tomorrow = await _seed_customer(db, account, name="Ngay mai", has_debt=True)
        paused = await _seed_customer(db, account, name="Tam dung", has_debt=True)
        db.add_all(
            [
                DebtReminderAutomation(
                    customer_id=later.id, next_run_at=_local_at(0, 23, 50)
                ),
                DebtReminderAutomation(
                    customer_id=overdue.id, next_run_at=_local_at(0, 0, 5)
                ),
                DebtReminderAutomation(
                    customer_id=tomorrow.id, next_run_at=_local_at(1, 9)
                ),
                DebtReminderAutomation(customer_id=paused.id, next_run_at=None),
            ]
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.reminders_due_today_count == 2
    assert [item.customer_name for item in result.reminders_due_today] == [
        "Qua han",
        "Sap toi",
    ]
    assert result.reminders_due_today[0].customer_id == overdue.id
    await engine.dispose()


async def test_upcoming_reminders_are_capped_but_counted_in_full(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        for index in range(8):
            customer = await _seed_customer(db, account, name=f"KH{index}", has_debt=True)
            db.add(
                DebtReminderAutomation(
                    customer_id=customer.id, next_run_at=_local_at(0, 8, index)
                )
            )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.reminders_due_today_count == 8
    assert len(result.reminders_due_today) == dashboard_api.UPCOMING_REMINDER_LIMIT
    await engine.dispose()


async def test_active_mention_followups_are_counted(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="Tag")
        automation = MentionAutomation(zalo_group_id=customer.zalo_group_id, enabled=True)
        db.add(automation)
        await db.flush()
        for index, status in enumerate(
            (
                MentionFollowupStatus.PENDING,
                MentionFollowupStatus.CLASSIFYING,
                MentionFollowupStatus.PROCESSING,
                MentionFollowupStatus.SENT,
                MentionFollowupStatus.CANCELLED,
            )
        ):
            db.add(
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id=f"m{index}",
                    target_user_ids=["u1"],
                    target_display_names=["Nguoi"],
                    due_at=datetime.now(UTC),
                    status=status,
                )
            )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.active_mention_followups == 3
    await engine.dispose()


async def test_debt_run_funnel_covers_this_month_and_drops_cancelled(
    monkeypatch,
) -> None:
    """CANCELLED is config churn, not an outcome, so it stays out of the funnel."""
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="Funnel", has_debt=True)
        automation = DebtReminderAutomation(customer_id=customer.id)
        db.add(automation)
        await db.flush()
        local_month_start = datetime.now(VIETNAM).date().replace(day=1)
        this_month = datetime.combine(
            local_month_start, time(9), tzinfo=VIETNAM
        ).astimezone(UTC)
        # First of the current local month, so it lands inside the window even on
        # the 1st, and 40 days back is reliably in a previous month.
        previous_month = _local_midnight(-40)
        for index, (status, when) in enumerate(
            (
                (DebtReminderStatus.SENT, this_month),
                (DebtReminderStatus.SENT, this_month + timedelta(minutes=1)),
                (DebtReminderStatus.SKIPPED, this_month + timedelta(minutes=2)),
                (DebtReminderStatus.FAILED, this_month + timedelta(minutes=3)),
                (DebtReminderStatus.CANCELLED, this_month + timedelta(minutes=4)),
                (DebtReminderStatus.SENT, previous_month),
            )
        ):
            db.add(
                DebtReminderRun(
                    automation_id=automation.id,
                    scheduled_for=when,
                    retry_at=when,
                    status=status,
                )
            )
            _ = index
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.debt_runs_month == {"sent": 2, "skipped": 1, "failed": 1}
    await engine.dispose()


async def test_ai_stats_summarise_todays_classifier_spend(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        customer = await _seed_customer(db, account, name="AI")
        db.add_all(
            [
                _model_call(
                    customer, outcome="SKIPPED", latency_ms=100, created_at=_local_at(0, 9)
                ),
                _model_call(
                    customer, outcome="SKIPPED", latency_ms=300, created_at=_local_at(0, 10)
                ),
                _model_call(
                    customer, outcome="SCHEDULED", latency_ms=200, created_at=_local_at(0, 11)
                ),
                # Failed calls count towards spend but not towards latency.
                _model_call(
                    customer,
                    outcome="RETRY_CLASSIFICATION",
                    latency_ms=9000,
                    created_at=_local_at(0, 12),
                    status=ModelCallStatus.FAILED,
                ),
                # Yesterday: out of scope entirely.
                _model_call(
                    customer, outcome="SKIPPED", latency_ms=50, created_at=_local_at(-1, 9)
                ),
                # A bad producer clock must not leak tomorrow into today's card.
                _model_call(
                    customer,
                    outcome="SKIPPED",
                    latency_ms=9999,
                    created_at=_local_at(1, 9),
                ),
            ]
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.ai_calls_today == 4
    assert result.ai_blocked_today == 2
    assert result.ai_avg_latency_ms == 200, "chi tinh latency cua call thanh cong"
    assert result.ai_tokens_today == {"input": 40, "output": 16}
    await engine.dispose()


async def test_ai_stats_are_empty_rather_than_zero_latency(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.ai_calls_today == 0
    assert result.ai_avg_latency_ms is None, "khong co call thi khong phai 0ms"
    assert result.ai_tokens_today == {"input": 0, "output": 0}
    await engine.dispose()


async def test_quiet_failures_are_surfaced(monkeypatch) -> None:
    """Owing with no Sheet is the trap: the schedule pauses without saying so."""
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        await _seed_customer(db, account, name="Co file", has_debt=True)
        await _seed_customer(db, account, name="Thieu file", has_debt=True, debt_file_url=None)
        await _seed_customer(db, account, name="File rong", has_debt=True, debt_file_url="")
        await _seed_customer(db, account, name="Het no", has_debt=False, debt_file_url=None)
        await _seed_customer(db, account, name="Mat nhom", is_available=False)
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.debt_missing_file == 2
    assert result.groups_unavailable == 1
    assert result.ai_classifier_enabled is True, "chua co row thi coi nhu dang bat"
    await engine.dispose()


async def test_a_disabled_classifier_is_reported(monkeypatch) -> None:
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch)
    async with sessions() as db:
        db.add(
            MentionClassifierSettings(
                id=1,
                ai_classifier_enabled=False,
                bare_mention_requires_response=True,
                skip_phrases=[],
            )
        )
        await db.commit()
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.ai_classifier_enabled is False
    await engine.dispose()


async def test_an_unreachable_gateway_leaves_the_dashboard_readable(monkeypatch) -> None:
    """None, not False: "cannot ask" is a different message from "channel down"."""
    engine, sessions = await _dashboard_database()
    _silence_gateway(monkeypatch, None)
    async with sessions() as db:
        result = await dashboard(db=db, _actor=None)  # type: ignore[arg-type]

    assert result.events_healthy is None
    # Everything else still rendered, so one dead dependency does not blank the page.
    assert result.customer_count == 0
    assert len(result.daily_messages) == 7
    await engine.dispose()


async def test_the_probe_swallows_a_gateway_error(monkeypatch) -> None:
    async def refuse() -> dict[str, object]:
        raise GatewayError("ZALO_GATEWAY_UNAVAILABLE", "khong ket noi duoc", 503)

    monkeypatch.setattr(dashboard_api.zalo_gateway, "get_status", refuse)
    assert await dashboard_api.gateway_events_healthy() is None


async def test_the_probe_reports_a_reachable_but_unhealthy_channel(monkeypatch) -> None:
    async def unhealthy() -> dict[str, object]:
        return {"status": "CONNECTED", "events_healthy": False}

    monkeypatch.setattr(dashboard_api.zalo_gateway, "get_status", unhealthy)
    assert await dashboard_api.gateway_events_healthy() is False


async def test_the_gateway_probe_gives_up_quickly(monkeypatch) -> None:
    """A hung gateway must not hold the dashboard of every logged-in operator."""

    async def hang() -> dict[str, object]:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(dashboard_api, "GATEWAY_PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(dashboard_api.zalo_gateway, "get_status", hang)
    started = time_module.monotonic()
    assert await dashboard_api.gateway_events_healthy() is None
    assert time_module.monotonic() - started < 5, "probe phai bo cuoc som"
