import asyncio
import contextlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import DASHBOARD_READ
from app.db.database import get_db
from app.models import (
    BotDeliveryLog,
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionClassifierSettings,
    MentionFollowup,
    ModelCallLog,
    User,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    BotStatus,
    DebtReminderStatus,
    DeliveryStatus,
    DeliveryType,
    MentionFollowupStatus,
    ModelCallStatus,
)
from app.schemas.api import (
    DashboardDailyMessages,
    DashboardHourlyMessages,
    DashboardResponse,
    DashboardUpcomingReminder,
)
from app.services.mention_settings_service import GLOBAL_SETTINGS_ID
from app.services.zalo_gateway_client import zalo_gateway

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
#: Matches ACTIVITY_LOG_RETENTION_DAYS: asking for more would plot a slope that
#: only shows retention deleting rows.
TREND_DAYS = 7
#: Enough for an operator to recognise the day's work without a scrollbar.
UPCOMING_REMINDER_LIMIT = 5
#: The gateway is a nice-to-have here. Its own timeout is 30s, and one hung
#: gateway must not hang the dashboard of every logged-in operator.
GATEWAY_PROBE_TIMEOUT_SECONDS = 2.0

_DELIVERY_FEATURE = {
    DeliveryType.DEBT_REMINDER_IMAGE: "debt",
    DeliveryType.DEBT_REMINDER_LINK: "debt",
    DeliveryType.DEBT_REMINDER_MESSAGE: "debt",
    DeliveryType.MENTION_AUTOMATION: "mention",
    DeliveryType.MANUAL_MESSAGE: "manual",
}

_ACTIVE_FOLLOWUP_STATUSES = (
    MentionFollowupStatus.CLASSIFYING,
    MentionFollowupStatus.PENDING,
    MentionFollowupStatus.PROCESSING,
)

_DEBT_RUN_BUCKET = {
    DebtReminderStatus.SENT: "sent",
    DebtReminderStatus.SKIPPED: "skipped",
    DebtReminderStatus.FAILED: "failed",
}


async def gateway_events_healthy() -> bool | None:
    """Whether the gateway says it can still observe Zalo replies.

    Returns None when the gateway cannot be reached at all — a different thing
    from a reachable gateway reporting a broken channel, and the strip says so.
    Separate function so tests can substitute it without doing any HTTP.
    """
    with contextlib.suppress(Exception):
        state = await asyncio.wait_for(
            zalo_gateway.get_status(), timeout=GATEWAY_PROBE_TIMEOUT_SECONDS
        )
        return bool(state.get("events_healthy", False))
    return None


def _local(moment: datetime) -> datetime:
    """Read a stored timestamp as Vietnam-local wall clock.

    Drivers differ on whether they hand back an aware datetime, and calling
    astimezone on a naive one silently assumes the *host* timezone rather than
    UTC — which put every hour in the wrong bucket on SQLite.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(LOCAL_TIMEZONE)


def _start_of_local_day(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=LOCAL_TIMEZONE).astimezone(
        UTC
    )


@router.get("", response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DASHBOARD_READ)),
) -> DashboardResponse:
    # Probe before the first DB read. AsyncSession begins a transaction lazily;
    # doing external I/O after that would hold a pool connection for up to the
    # gateway timeout whenever the gateway is slow or unreachable.
    events_healthy = await gateway_events_healthy()
    account = await db.scalar(select(ZaloAccount).order_by(ZaloAccount.created_at).limit(1))
    local_now = datetime.now(UTC).astimezone(LOCAL_TIMEZONE)
    today = local_now.date()
    yesterday = today - timedelta(days=1)
    trend_days = [today - timedelta(days=offset) for offset in range(TREND_DAYS - 1, -1, -1)]
    trend_start = _start_of_local_day(trend_days[0])
    tomorrow_start = _start_of_local_day(today + timedelta(days=1))

    customer_count = int(await db.scalar(select(func.count()).select_from(Customer)) or 0)
    customers_with_debt = int(
        await db.scalar(
            select(func.count()).select_from(Customer).where(Customer.has_debt.is_(True))
        )
        or 0
    )

    # One pass over the retained delivery logs feeds every message figure below.
    # Reading them separately meant four round trips for the same rows, and the
    # today-only counters silently disagreed about their upper bound.
    delivery_rows = (
        await db.execute(
            select(
                BotDeliveryLog.created_at,
                BotDeliveryLog.status,
                BotDeliveryLog.type,
            ).where(
                BotDeliveryLog.created_at >= trend_start,
                BotDeliveryLog.created_at < tomorrow_start,
            )
        )
    ).all()

    messages_by_hour = [0] * 24
    by_day: dict[date, dict[str, int]] = defaultdict(lambda: {"sent": 0, "failed": 0})
    by_type_today: dict[str, int] = {"debt": 0, "mention": 0, "manual": 0}
    messages_today = failed_today = messages_yesterday = 0

    for created_at, status, delivery_type in delivery_rows:
        local_created = _local(created_at)
        day = local_created.date()
        sent = status == DeliveryStatus.SENT
        by_day[day]["sent" if sent else "failed"] += 1
        if day == yesterday and sent:
            messages_yesterday += 1
        if day != today:
            continue
        if sent:
            messages_today += 1
            messages_by_hour[local_created.hour] += 1
            feature = _DELIVERY_FEATURE.get(delivery_type)
            if feature:
                by_type_today[feature] += 1
        else:
            failed_today += 1

    last_sync = await db.scalar(select(func.max(ZaloGroup.last_synced_at)))
    last_sent = await db.scalar(
        select(func.max(BotDeliveryLog.created_at)).where(
            BotDeliveryLog.status == DeliveryStatus.SENT
        )
    )

    groups_unavailable = int(
        await db.scalar(
            select(func.count())
            .select_from(ZaloGroup)
            .where(ZaloGroup.is_available.is_(False))
        )
        or 0
    )
    # The quiet failure mode: marked as owing, but sync_debt_reminder_state has
    # blanked next_run_at because there is no Sheet to render.
    debt_missing_file = int(
        await db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(
                Customer.has_debt.is_(True),
                or_(Customer.debt_file_url.is_(None), Customer.debt_file_url == ""),
            )
        )
        or 0
    )
    # Read-only: get_or_create would write to the database from a GET.
    classifier_settings = await db.get(MentionClassifierSettings, GLOBAL_SETTINGS_ID)
    ai_classifier_enabled = (
        True if classifier_settings is None else classifier_settings.ai_classifier_enabled
    )

    due_filters = (
        DebtReminderAutomation.next_run_at.is_not(None),
        DebtReminderAutomation.next_run_at < tomorrow_start,
    )
    reminders_due_today_count = int(
        await db.scalar(
            select(func.count()).select_from(DebtReminderAutomation).where(*due_filters)
        )
        or 0
    )
    upcoming_rows = (
        await db.execute(
            select(
                Customer.id,
                ZaloGroup.name,
                DebtReminderAutomation.next_run_at,
            )
            .join(Customer, Customer.id == DebtReminderAutomation.customer_id)
            .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
            .where(*due_filters)
            .order_by(DebtReminderAutomation.next_run_at.asc())
            .limit(UPCOMING_REMINDER_LIMIT)
        )
    ).all()
    active_mention_followups = int(
        await db.scalar(
            select(func.count())
            .select_from(MentionFollowup)
            .where(MentionFollowup.status.in_(_ACTIVE_FOLLOWUP_STATUSES))
        )
        or 0
    )

    month_start = _start_of_local_day(today.replace(day=1))
    next_month = (
        date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    )
    debt_runs_month = {"sent": 0, "skipped": 0, "failed": 0}
    debt_run_rows = (
        await db.execute(
            select(DebtReminderRun.status, func.count())
            .where(
                DebtReminderRun.scheduled_for >= month_start,
                DebtReminderRun.scheduled_for < _start_of_local_day(next_month),
                DebtReminderRun.status.in_(list(_DEBT_RUN_BUCKET)),
            )
            .group_by(DebtReminderRun.status)
        )
    ).all()
    for run_status, count in debt_run_rows:
        debt_runs_month[_DEBT_RUN_BUCKET[run_status]] = int(count)

    today_start = _start_of_local_day(today)
    ai_row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(ModelCallLog.input_tokens), 0),
                func.coalesce(func.sum(ModelCallLog.output_tokens), 0),
            ).where(
                ModelCallLog.created_at >= today_start,
                ModelCallLog.created_at < tomorrow_start,
            )
        )
    ).one()
    ai_blocked_today = int(
        await db.scalar(
            select(func.count())
            .select_from(ModelCallLog)
            .where(
                ModelCallLog.created_at >= today_start,
                ModelCallLog.created_at < tomorrow_start,
                ModelCallLog.outcome == "SKIPPED",
            )
        )
        or 0
    )
    ai_avg_latency = await db.scalar(
        select(func.avg(ModelCallLog.latency_ms)).where(
            ModelCallLog.created_at >= today_start,
            ModelCallLog.created_at < tomorrow_start,
            ModelCallLog.status == ModelCallStatus.SUCCEEDED,
            ModelCallLog.latency_ms.is_not(None),
        )
    )

    return DashboardResponse(
        bot_status=account.status if account else BotStatus.AUTH_REQUIRED,
        customer_count=customer_count,
        customers_with_debt=customers_with_debt,
        customers_without_debt=max(0, customer_count - customers_with_debt),
        messages_today=messages_today,
        messages_by_hour=[
            DashboardHourlyMessages(hour=hour, count=count)
            for hour, count in enumerate(messages_by_hour)
        ],
        failed_today=failed_today,
        last_sync_at=last_sync,
        last_successful_message_at=last_sent,
        messages_yesterday=messages_yesterday,
        daily_messages=[
            DashboardDailyMessages(
                date=day.isoformat(),
                sent=by_day[day]["sent"],
                failed=by_day[day]["failed"],
            )
            for day in trend_days
        ],
        messages_by_type_today=by_type_today,
        groups_unavailable=groups_unavailable,
        debt_missing_file=debt_missing_file,
        ai_classifier_enabled=ai_classifier_enabled,
        events_healthy=events_healthy,
        reminders_due_today=[
            DashboardUpcomingReminder(
                customer_id=customer_id,
                customer_name=customer_name,
                next_run_at=next_run_at,
            )
            for customer_id, customer_name, next_run_at in upcoming_rows
        ],
        reminders_due_today_count=reminders_due_today_count,
        active_mention_followups=active_mention_followups,
        debt_runs_month=debt_runs_month,
        ai_calls_today=int(ai_row[0] or 0),
        ai_blocked_today=ai_blocked_today,
        ai_avg_latency_ms=round(ai_avg_latency) if ai_avg_latency is not None else None,
        ai_tokens_today={"input": int(ai_row[1] or 0), "output": int(ai_row[2] or 0)},
    )
