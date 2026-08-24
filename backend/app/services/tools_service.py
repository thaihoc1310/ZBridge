import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionFollowup,
    ZaloGroup,
)
from app.models.entities import DebtReminderStatus, MentionFollowupStatus
from app.schemas.api import (
    ActiveMentionCompanyListResponse,
    ActiveMentionCompanyResponse,
    ActiveMentionTaskResponse,
    DebtReminderBulkApply,
    DebtReminderBulkApplyResponse,
    DebtReminderBulkPreviewResponse,
    DebtReminderBulkPreviewRow,
    DebtReminderBulkSchedule,
    DebtReminderRunListResponse,
    DebtReminderRunResponse,
    DebtReminderRunStepResponse,
)
from app.services.debt_reminder_service import (
    next_debt_reminder_run,
    next_monthly_run,
)

ACTIVE_MENTION_STATUSES = (
    MentionFollowupStatus.CLASSIFYING,
    MentionFollowupStatus.PENDING,
    MentionFollowupStatus.PROCESSING,
)
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


async def list_active_mention_followups(
    db: AsyncSession,
    *,
    search: str | None,
    sort: str,
    direction: str,
    page: int,
    limit: int,
) -> ActiveMentionCompanyListResponse:
    rows = list(
        (
            await db.execute(
                select(MentionFollowup, Customer.id, ZaloGroup.name)
                .join(MentionAutomation, MentionAutomation.id == MentionFollowup.automation_id)
                .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
                .join(Customer, Customer.zalo_group_id == ZaloGroup.id)
                .where(MentionFollowup.status.in_(ACTIVE_MENTION_STATUSES))
                .order_by(MentionFollowup.due_at.asc())
            )
        ).all()
    )
    needle = (search or "").strip().casefold()
    if needle:
        rows = [
            row
            for row in rows
            if needle in row[2].casefold()
            or any(needle in name.casefold() for name in row[0].target_display_names)
        ]

    grouped: dict[tuple[uuid.UUID, str], list[MentionFollowup]] = defaultdict(list)
    for followup, customer_id, customer_name in rows:
        grouped[(customer_id, customer_name)].append(followup)

    companies = [
        ActiveMentionCompanyResponse(
            customer_id=customer_id,
            customer_name=customer_name,
            task_count=len(tasks),
            next_due_at=min(task.due_at for task in tasks),
            tasks=[
                ActiveMentionTaskResponse(
                    id=task.id,
                    trigger=task.trigger,
                    status=task.status,
                    target_user_ids=list(task.target_user_ids),
                    target_display_names=list(task.target_display_names),
                    due_at=task.due_at,
                    created_at=task.created_at,
                    attempt_count=task.attempt_count,
                    send_count=task.send_count,
                    error_message=task.error_message,
                )
                for task in tasks
            ],
        )
        for (customer_id, customer_name), tasks in grouped.items()
    ]
    key_functions = {
        "name": lambda company: company.customer_name.casefold(),
        "count": lambda company: company.task_count,
        "next_due": lambda company: company.next_due_at,
        "newest": lambda company: max(task.created_at for task in company.tasks),
    }
    companies.sort(
        key=key_functions.get(sort, key_functions["next_due"]),
        reverse=direction == "desc",
    )
    total_companies = len(companies)
    total_tasks = sum(company.task_count for company in companies)
    start = (page - 1) * limit
    return ActiveMentionCompanyListResponse(
        items=companies[start : start + limit],
        total_companies=total_companies,
        total_tasks=total_tasks,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total_companies / limit)),
    )


async def cancel_mention_followup(
    db: AsyncSession, followup_id: uuid.UUID
) -> ActiveMentionTaskResponse:
    followup = await db.scalar(
        select(MentionFollowup).where(MentionFollowup.id == followup_id).with_for_update()
    )
    if followup is None:
        raise AppError("MENTION_FOLLOWUP_NOT_FOUND", "Không tìm thấy vòng tag.", 404)
    if followup.status in ACTIVE_MENTION_STATUSES:
        followup.status = MentionFollowupStatus.CANCELLED
        followup.claimed_at = None
        followup.processed_at = datetime.now(UTC)
        followup.error_message = "Đã dừng thủ công từ trang Công cụ."
        await db.commit()
    return ActiveMentionTaskResponse(
        id=followup.id,
        trigger=followup.trigger,
        status=followup.status,
        target_user_ids=list(followup.target_user_ids),
        target_display_names=list(followup.target_display_names),
        due_at=followup.due_at,
        created_at=followup.created_at,
        attempt_count=followup.attempt_count,
        send_count=followup.send_count,
        error_message=followup.error_message,
    )


async def preview_bulk_debt_reminders(
    db: AsyncSession, data: DebtReminderBulkSchedule
) -> DebtReminderBulkPreviewResponse:
    customers = list(
        (
            await db.scalars(
                select(Customer)
                .options(selectinload(Customer.group), selectinload(Customer.debt_reminder))
                .join(Customer.group)
                .order_by(ZaloGroup.name.asc())
            )
        ).all()
    )
    rows = []
    for customer in customers:
        automation = customer.debt_reminder
        if automation is None:
            raise AppError(
                "DEBT_REMINDER_CONFIG_MISSING",
                f"Khách hàng {customer.group.name} thiếu cấu hình nhắc công nợ.",
                500,
            )
        current_day = automation.day_of_month
        current_repeat = automation.repeat_interval_days
        current_time = automation.send_time.strftime("%H:%M")
        runnable = (
            customer.group.is_available
            and customer.has_debt
            and bool(customer.debt_file_url)
        )
        will_change = (
            automation.day_of_month != data.day_of_month
            or automation.repeat_interval_days != data.repeat_interval_days
            or current_time != data.send_time
            or runnable != (automation.next_run_at is not None)
        )
        rows.append(
            DebtReminderBulkPreviewRow(
                customer_id=customer.id,
                name=customer.group.name,
                is_available=customer.group.is_available,
                has_debt=customer.has_debt,
                has_debt_file=bool(customer.debt_file_url),
                current_day_of_month=current_day,
                current_repeat_interval_days=current_repeat,
                current_send_time=current_time,
                will_change=will_change,
            )
        )
    return DebtReminderBulkPreviewResponse(rows=rows)


async def apply_bulk_debt_reminders(
    db: AsyncSession, data: DebtReminderBulkApply
) -> DebtReminderBulkApplyResponse:
    if not data.customer_ids:
        raise AppError("NO_CUSTOMERS_SELECTED", "Hãy chọn ít nhất một khách hàng.", 422)
    customers = list(
        (
            await db.scalars(
                select(Customer)
                .options(selectinload(Customer.group), selectinload(Customer.debt_reminder))
                .where(Customer.id.in_(set(data.customer_ids)))
                .with_for_update()
            )
        ).all()
    )
    found = {customer.id for customer in customers}
    missing = set(data.customer_ids) - found
    if missing:
        raise AppError("CUSTOMER_NOT_FOUND", "Có khách hàng không còn tồn tại.", 404)

    # The scheduler locks automation rows while materialising due runs. Lock the
    # same rows here before deciding which runs to cancel and where to reschedule,
    # otherwise a beat tick can create a run from the old schedule concurrently
    # with this bulk update.
    automation_by_customer = {
        automation.customer_id: automation
        for automation in (
            await db.scalars(
                select(DebtReminderAutomation)
                .where(DebtReminderAutomation.customer_id.in_(found))
                .with_for_update()
            )
        ).all()
    }

    parsed_time = time.fromisoformat(data.send_time)
    now = datetime.now(UTC)
    updated_count = unchanged = cancelled = 0
    skipped: list[str] = []
    for customer in customers:
        if not customer.group.is_available:
            skipped.append(customer.group.name)
            continue
        automation = automation_by_customer.get(customer.id)
        runnable = (
            customer.group.is_available
            and customer.has_debt
            and bool(customer.debt_file_url)
        )
        if automation is None:
            raise AppError(
                "DEBT_REMINDER_CONFIG_MISSING",
                f"Khách hàng {customer.group.name} thiếu cấu hình nhắc công nợ.",
                500,
            )
        schedule_unchanged = (
            automation.day_of_month == data.day_of_month
            and automation.repeat_interval_days == data.repeat_interval_days
            and automation.send_time == parsed_time
        )
        state_unchanged = runnable == (automation.next_run_at is not None)
        if schedule_unchanged and state_unchanged:
            unchanged += 1
            continue
        result = await db.execute(
            update(DebtReminderRun)
            .where(
                DebtReminderRun.automation_id == automation.id,
                DebtReminderRun.status.in_(
                    [DebtReminderStatus.PENDING, DebtReminderStatus.PROCESSING]
                ),
            )
            .values(
                status=DebtReminderStatus.CANCELLED,
                claimed_at=None,
                processed_at=now,
                error_message="Lịch nhắc công nợ đã được thay đổi hàng loạt.",
            )
        )
        cancelled += result.rowcount or 0
        automation.day_of_month = data.day_of_month
        automation.repeat_interval_days = data.repeat_interval_days
        automation.send_time = parsed_time
        if runnable:
            next_run_at = next_monthly_run(data.day_of_month, parsed_time, now=now)
            last_sent = await db.scalar(
                select(DebtReminderRun)
                .where(
                    DebtReminderRun.automation_id == automation.id,
                    DebtReminderRun.status == DebtReminderStatus.SENT,
                )
                .order_by(DebtReminderRun.scheduled_for.desc())
                .limit(1)
            )
            if last_sent is not None:
                next_run_at = next_debt_reminder_run(
                    data.day_of_month,
                    parsed_time,
                    data.repeat_interval_days,
                    last_sent.scheduled_for,
                    has_debt=True,
                    now=now,
                )
            automation.next_run_at = next_run_at
        else:
            automation.next_run_at = None
        updated_count += 1
    await db.commit()
    return DebtReminderBulkApplyResponse(
        created=0,
        updated=updated_count,
        unchanged=unchanged,
        cancelled_runs=cancelled,
        skipped=skipped,
    )


def _run_steps(run: DebtReminderRun) -> list[DebtReminderRunStepResponse]:
    values = [
        ("IMAGE", run.image_message_id),
        ("LINK", run.link_message_id),
        ("MESSAGE", run.text_message_id),
    ]
    first_missing = next(
        (index for index, (_, message_id) in enumerate(values) if not message_id), None
    )
    steps = []
    for index, (step_type, message_id) in enumerate(values):
        if message_id:
            status = "SENT"
        elif run.status == DebtReminderStatus.SKIPPED:
            status = "SKIPPED"
        elif run.status == DebtReminderStatus.CANCELLED:
            status = "CANCELLED"
        elif run.status == DebtReminderStatus.FAILED and index == first_missing:
            status = "FAILED"
        elif run.status == DebtReminderStatus.PROCESSING and index == first_missing:
            status = "PROCESSING"
        else:
            status = "PENDING"
        steps.append(
            DebtReminderRunStepResponse(
                type=step_type,
                status=status,
                zalo_message_id=message_id,
                error_message=run.error_message if index == first_missing else None,
            )
        )
    return steps


async def list_debt_reminder_runs(
    db: AsyncSession,
    *,
    month: str | None,
    status: DebtReminderStatus | None,
    search: str | None,
    sort: str,
    direction: str,
    page: int,
    limit: int,
) -> DebtReminderRunListResponse:
    local_now = datetime.now(UTC).astimezone(LOCAL_TIMEZONE)
    if month:
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            month_start = datetime(year, month_number, 1, tzinfo=LOCAL_TIMEZONE)
        except (ValueError, TypeError) as exc:
            raise AppError("INVALID_MONTH", "Tháng phải có định dạng YYYY-MM.", 422) from exc
    else:
        month_start = datetime(local_now.year, local_now.month, 1, tzinfo=LOCAL_TIMEZONE)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    filters = [
        DebtReminderRun.scheduled_for >= month_start.astimezone(UTC),
        DebtReminderRun.scheduled_for < month_end.astimezone(UTC),
    ]
    if status:
        filters.append(DebtReminderRun.status == status)
    if search and search.strip():
        filters.append(ZaloGroup.name.ilike(f"%{search.strip()}%"))
    base = (
        select(DebtReminderRun, Customer.id, ZaloGroup.name)
        .join(DebtReminderAutomation, DebtReminderAutomation.id == DebtReminderRun.automation_id)
        .join(Customer, Customer.id == DebtReminderAutomation.customer_id)
        .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
        .where(*filters)
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(DebtReminderRun)
            .join(
                DebtReminderAutomation, DebtReminderAutomation.id == DebtReminderRun.automation_id
            )
            .join(Customer, Customer.id == DebtReminderAutomation.customer_id)
            .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
            .where(*filters)
        )
        or 0
    )
    order_columns = {
        "scheduled": DebtReminderRun.scheduled_for,
        "company": ZaloGroup.name,
        "status": DebtReminderRun.status,
    }
    order_column = order_columns.get(sort, DebtReminderRun.scheduled_for)
    order = order_column.desc() if direction == "desc" else order_column.asc()
    rows = (await db.execute(base.order_by(order).offset((page - 1) * limit).limit(limit))).all()
    count_rows = (
        await db.execute(
            select(DebtReminderRun.status, func.count())
            .select_from(DebtReminderRun)
            .join(
                DebtReminderAutomation, DebtReminderAutomation.id == DebtReminderRun.automation_id
            )
            .join(Customer, Customer.id == DebtReminderAutomation.customer_id)
            .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
            .where(
                DebtReminderRun.scheduled_for >= month_start.astimezone(UTC),
                DebtReminderRun.scheduled_for < month_end.astimezone(UTC),
                *(
                    [ZaloGroup.name.ilike(f"%{search.strip()}%")]
                    if search and search.strip()
                    else []
                ),
            )
            .group_by(DebtReminderRun.status)
        )
    ).all()
    status_counts = {item_status.value: int(count) for item_status, count in count_rows}
    status_counts["ALL"] = sum(status_counts.values())
    return DebtReminderRunListResponse(
        items=[
            DebtReminderRunResponse(
                id=run.id,
                customer_id=customer_id,
                customer_name=customer_name,
                status=run.status,
                scheduled_for=run.scheduled_for,
                retry_at=run.retry_at,
                attempt_count=run.attempt_count,
                created_at=run.created_at,
                processed_at=run.processed_at,
                sheet_name=run.sheet_name,
                sheet_url=run.sheet_url,
                error_code=run.error_code,
                error_message=run.error_message,
                steps=_run_steps(run),
            )
            for run, customer_id, customer_name in rows
        ],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)),
        status_counts=status_counts,
    )
