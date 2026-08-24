from datetime import UTC, datetime, time

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import (
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionFollowup,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import DebtReminderStatus, MentionFollowupStatus
from app.schemas.api import DebtReminderBulkApply, DebtReminderBulkSchedule
from app.services.drive_conversion_service import (
    _raise_drive_response_error,
    extract_folder_id,
)
from app.services.google_sheets_service import SheetExportError
from app.services.tools_service import (
    apply_bulk_debt_reminders,
    cancel_mention_followup,
    list_active_mention_followups,
    list_debt_reminder_runs,
    preview_bulk_debt_reminders,
)


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 24, 3, tzinfo=UTC)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="tools-group",
            name="Công ty Tools",
            member_count=3,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/test/edit",
        )
        db.add(customer)
        await db.flush()
        mention = MentionAutomation(zalo_group_id=group.id)
        db.add(mention)
        debt = DebtReminderAutomation(
            customer_id=customer.id,
            enabled=True,
            day_of_month=25,
            repeat_interval_days=3,
            send_time=time(9, 0),
            message_parts=[{"type": "text", "text": "Nội dung riêng không được ghi đè"}],
            next_run_at=now,
        )
        db.add(debt)
        await db.flush()
        followup = MentionFollowup(
            automation_id=mention.id,
            source_message_id="source-1",
            target_user_ids=["u-a", "u-b"],
            target_display_names=["Anh A", "Chị B"],
            due_at=now,
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=now,
        )
        db.add(followup)
        run = DebtReminderRun(
            automation_id=debt.id,
            scheduled_for=now,
            retry_at=now,
            status=DebtReminderStatus.PROCESSING,
            image_message_id="image-id",
            attempt_count=1,
            claimed_at=now,
        )
        db.add(run)
        await db.commit()
        return engine, sessions, customer.id, followup.id, run.id


async def test_active_followups_are_grouped_and_cancelled_atomically() -> None:
    engine, sessions, _customer_id, followup_id, _run_id = await _database()
    async with sessions() as db:
        result = await list_active_mention_followups(
            db, search="chị b", sort="next_due", direction="asc", page=1, limit=20
        )
        assert result.total_companies == 1
        assert result.total_tasks == 1
        assert result.items[0].tasks[0].target_display_names == ["Anh A", "Chị B"]
        stopped = await cancel_mention_followup(db, followup_id)
        assert stopped.status == MentionFollowupStatus.CANCELLED

    async with sessions() as db:
        stored = await db.get(MentionFollowup, followup_id)
        assert stored.status == MentionFollowupStatus.CANCELLED
        assert stored.claimed_at is None
        assert stored.processed_at is not None
    await engine.dispose()


async def test_bulk_debt_schedule_preserves_message_and_cancels_old_run() -> None:
    engine, sessions, customer_id, _followup_id, run_id = await _database()
    schedule = DebtReminderBulkSchedule(day_of_month=28, repeat_interval_days=5, send_time="10:30")
    async with sessions() as db:
        preview = await preview_bulk_debt_reminders(db, schedule)
        assert preview.rows[0].will_change is True
        result = await apply_bulk_debt_reminders(
            db,
            DebtReminderBulkApply(**schedule.model_dump(), customer_ids=[customer_id]),
        )
        assert result.updated == 1
        assert result.cancelled_runs == 1

    async with sessions() as db:
        automation = await db.scalar(
            select(DebtReminderAutomation).where(DebtReminderAutomation.customer_id == customer_id)
        )
        assert automation.message_parts == [
            {"type": "text", "text": "Nội dung riêng không được ghi đè"}
        ]
        assert automation.enabled is True
        assert automation.day_of_month == 28
        assert automation.repeat_interval_days == 5
        assert automation.send_time == time(10, 30)
        old_run = await db.get(DebtReminderRun, run_id)
        assert old_run.status == DebtReminderStatus.CANCELLED
        assert old_run.claimed_at is None
    await engine.dispose()


async def test_bulk_debt_schedule_activates_owing_customers_and_pauses_blocked_ones() -> None:
    engine, sessions, _customer_id, _followup_id, _run_id = await _database()
    async with sessions() as db:
        account_id = await db.scalar(select(ZaloAccount.id))
        assert account_id is not None
        customers = []
        for suffix, has_debt, sheet_url in (
            ("active", True, "https://docs.google.com/spreadsheets/d/active/edit"),
            ("missing-sheet", True, None),
            ("paid", False, "https://docs.google.com/spreadsheets/d/paid/edit"),
        ):
            group = ZaloGroup(
                zalo_account_id=account_id,
                zalo_group_id=f"bulk-{suffix}",
                name=f"Công ty {suffix}",
                member_count=2,
                is_available=True,
                last_synced_at=datetime(2026, 8, 24, 3, tzinfo=UTC),
            )
            db.add(group)
            await db.flush()
            customer = Customer(
                zalo_group_id=group.id,
                has_debt=has_debt,
                debt_file_url=sheet_url,
            )
            db.add(customer)
            await db.flush()
            customers.append(customer)
        await db.commit()

        schedule = DebtReminderBulkSchedule(
            day_of_month=28, repeat_interval_days=5, send_time="10:30"
        )
        preview = await preview_bulk_debt_reminders(db, schedule)
        new_rows = [row for row in preview.rows if row.customer_id in {c.id for c in customers}]
        assert all(row.has_automation is False for row in new_rows)
        assert all(row.enabled is True for row in new_rows)
        assert all(row.current_day_of_month == 25 for row in new_rows)

        result = await apply_bulk_debt_reminders(
            db,
            DebtReminderBulkApply(
                **schedule.model_dump(), customer_ids=[customer.id for customer in customers]
            ),
        )
        assert result.created == 3

    async with sessions() as db:
        automations = {
            automation.customer_id: automation
            for automation in await db.scalars(
                select(DebtReminderAutomation).where(
                    DebtReminderAutomation.customer_id.in_([customer.id for customer in customers])
                )
            )
        }
        active, missing_sheet, paid = customers
        assert all(automation.enabled is True for automation in automations.values())
        assert automations[active.id].next_run_at is not None
        assert automations[missing_sheet.id].next_run_at is None
        assert automations[paid.id].next_run_at is None
    await engine.dispose()


async def test_debt_history_expands_the_three_delivery_steps() -> None:
    engine, sessions, _customer_id, _followup_id, _run_id = await _database()
    async with sessions() as db:
        result = await list_debt_reminder_runs(
            db,
            month="2026-08",
            status=None,
            search="tools",
            sort="scheduled",
            direction="desc",
            page=1,
            limit=20,
        )
        assert result.retention_days == 45
        assert result.total == 1
        assert [step.status for step in result.items[0].steps] == [
            "SENT",
            "PROCESSING",
            "PENDING",
        ]
    await engine.dispose()


def test_drive_folder_url_parser_is_strict() -> None:
    assert (
        extract_folder_id(
            "https://drive.google.com/drive/folders/1iieiGavI5OxyGKIfAP7ipTIkJEcQs9SR?usp=drive_link"
        )
        == "1iieiGavI5OxyGKIfAP7ipTIkJEcQs9SR"
    )
    with pytest.raises(AppError):
        extract_folder_id("https://docs.google.com/spreadsheets/d/not-a-folder/edit")


def test_drive_storage_quota_error_is_reported_clearly() -> None:
    response = httpx.Response(
        403,
        request=httpx.Request("POST", "https://www.googleapis.com/upload/drive/v3/files"),
        json={
            "error": {
                "errors": [
                    {
                        "reason": "storageQuotaExceeded",
                        "message": "The user's Drive storage quota has been exceeded.",
                    }
                ]
            }
        },
    )
    with pytest.raises(SheetExportError) as raised:
        _raise_drive_response_error(response)
    assert raised.value.code == "GOOGLE_DRIVE_STORAGE_QUOTA"
    assert "hết dung lượng" in raised.value.message
