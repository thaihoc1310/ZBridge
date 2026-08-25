import os
import time as system_time
from datetime import UTC, datetime, time, timedelta

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    BotDeliveryLog,
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import BotStatus, DebtReminderStatus, DeliveryStatus, DeliveryType
from app.schemas.api import DebtReminderUpdate
from app.services import debt_reminder_scheduler, google_sheets_service
from app.services.debt_reminder_scheduler import (
    claim_due_debt_reminders,
    process_debt_reminder,
)
from app.services.debt_reminder_service import (
    defer_debt_reminder,
    is_debt_reminder_blackout,
    next_debt_reminder_run,
    next_monthly_run,
    save_debt_reminder,
)
from app.services.google_sheets_service import (
    SheetArtifact,
    SheetExportError,
    crop_white_margins,
    extract_spreadsheet_id,
)


def test_next_monthly_run_uses_vietnam_time_and_clamps_short_months() -> None:
    august_run = next_monthly_run(
        25,
        time(9, 0),
        now=datetime(2026, 8, 24, 10, tzinfo=UTC),
    )
    assert august_run == datetime(2026, 8, 25, 2, tzinfo=UTC)

    february_run = next_monthly_run(
        31,
        time(9, 0),
        # February 2031 ends on lunar 08/02, outside the Tết blackout.
        now=datetime(2031, 2, 1, tzinfo=UTC),
    )
    assert february_run == datetime(2031, 2, 28, 2, tzinfo=UTC)


@pytest.mark.parametrize("server_timezone", ["UTC", "Asia/Singapore"])
def test_debt_schedule_is_independent_of_the_server_timezone(
    server_timezone: str,
) -> None:
    previous_timezone = os.environ.get("TZ")
    try:
        os.environ["TZ"] = server_timezone
        system_time.tzset()
        assert next_monthly_run(
            25,
            time(9, 0),
            now=datetime(2026, 8, 24, 10, tzinfo=UTC),
        ) == datetime(2026, 8, 25, 2, tzinfo=UTC)
    finally:
        if previous_timezone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_timezone
        system_time.tzset()


def test_vietnamese_lunar_blackouts_are_deferred_even_across_solar_months() -> None:
    # Tết 2026 is mùng 1 and 2026-03-03 is rằm tháng Giêng in Vietnam.
    assert is_debt_reminder_blackout(datetime(2026, 2, 17).date())
    assert is_debt_reminder_blackout(datetime(2026, 3, 3).date())
    assert is_debt_reminder_blackout(datetime(2026, 3, 19).date())
    assert is_debt_reminder_blackout(datetime(2026, 4, 2).date())
    assert not is_debt_reminder_blackout(datetime(2026, 3, 20).date())

    assert defer_debt_reminder(
        datetime(2026, 2, 17, 2, tzinfo=UTC)
    ) == datetime(2026, 3, 20, 2, tzinfo=UTC)

    # 31/05/2026 is lunar 15/04, so a configured day 31 must run on 01/06.
    assert next_monthly_run(
        31,
        time(9, 0),
        # It is already after the configured 09:00 on 31/05, but the deferred
        # occurrence has not run yet and must not be skipped to the end of June.
        now=datetime(2026, 5, 31, 3, tzinfo=UTC),
    ) == datetime(2026, 6, 1, 2, tzinfo=UTC)


def test_solar_new_year_is_deferred_to_january_second() -> None:
    assert is_debt_reminder_blackout(datetime(2027, 1, 1).date())
    assert not is_debt_reminder_blackout(datetime(2027, 1, 2).date())
    assert defer_debt_reminder(
        datetime(2027, 1, 1, 2, tzinfo=UTC)
    ) == datetime(2027, 1, 2, 2, tzinfo=UTC)


def test_fixed_solar_holidays_are_deferred_to_the_next_working_day() -> None:
    for month, day in ((4, 30), (5, 1), (9, 2)):
        assert is_debt_reminder_blackout(datetime(2027, month, day).date())

    # 30/04 and 01/05 are consecutive, so the first allowed day is 02/05.
    assert defer_debt_reminder(
        datetime(2027, 4, 30, 2, tzinfo=UTC)
    ) == datetime(2027, 5, 2, 2, tzinfo=UTC)
    assert defer_debt_reminder(
        datetime(2027, 5, 1, 2, tzinfo=UTC)
    ) == datetime(2027, 5, 2, 2, tzinfo=UTC)
    assert defer_debt_reminder(
        datetime(2027, 9, 2, 2, tzinfo=UTC)
    ) == datetime(2027, 9, 3, 2, tzinfo=UTC)
    assert next_monthly_run(
        1,
        time(9, 0),
        now=datetime(2026, 12, 31, 10, tzinfo=UTC),
    ) == datetime(2027, 1, 2, 2, tzinfo=UTC)


def test_tet_break_runs_from_28_thang_chap_until_mung_2_thang_hai() -> None:
    # In 2026: 14/02 is 27/12, 15/02 is 28/12, 19/03 is 01/02,
    # and reminders resume on 20/03, which is 02/02.
    assert not is_debt_reminder_blackout(datetime(2026, 2, 14).date())
    assert is_debt_reminder_blackout(datetime(2026, 2, 15).date())
    assert is_debt_reminder_blackout(datetime(2026, 3, 4).date())
    assert is_debt_reminder_blackout(datetime(2026, 3, 19).date())
    assert not is_debt_reminder_blackout(datetime(2026, 3, 20).date())

    # Keep the configured Vietnam-local send time while crossing the solar month.
    assert defer_debt_reminder(
        datetime(2026, 2, 15, 2, tzinfo=UTC)
    ) == datetime(2026, 3, 20, 2, tzinfo=UTC)

    # The clamped end of February can also fall inside tháng Giêng and must
    # wait for mùng 2 tháng Hai rather than send at the solar month boundary.
    assert next_monthly_run(
        31,
        time(9, 0),
        now=datetime(2027, 2, 1, tzinfo=UTC),
    ) == datetime(2027, 3, 9, 2, tzinfo=UTC)

    # An interval landing on 28 tháng Chạp also resumes on 02 tháng Hai.
    february_12 = datetime(2026, 2, 12, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        31,
        time(9, 0),
        3,
        february_12,
        has_debt=True,
        now=february_12,
    ) == datetime(2026, 3, 20, 2, tzinfo=UTC)


def test_debt_reminder_has_no_independent_enabled_field() -> None:
    assert "enabled" not in DebtReminderUpdate.model_fields


def test_next_debt_reminder_repeats_and_preserves_monthly_anchor() -> None:
    send_time = time(9, 0)
    august_25 = datetime(2026, 8, 25, 2, tzinfo=UTC)
    september_24 = datetime(2026, 9, 24, 2, tzinfo=UTC)

    assert next_debt_reminder_run(
        25, send_time, 3, august_25, has_debt=True, now=august_25
    ) == datetime(2026, 8, 28, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        25, send_time, 3, september_24, has_debt=True, now=september_24
    ) == datetime(2026, 9, 26, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        25, send_time, 3, august_25, has_debt=False, now=august_25
    ) == datetime(2026, 9, 26, 2, tzinfo=UTC)


def test_lunar_deferred_repeat_becomes_the_next_interval_anchor() -> None:
    # 27/08/2026 is lunar 15/07. The 3-day interval from 24/08 therefore
    # moves to 28/08, and the following interval is anchored at 28 -> 31.
    august_24 = datetime(2026, 8, 24, 2, tzinfo=UTC)
    august_28 = datetime(2026, 8, 28, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        31, time(9, 0), 3, august_24, has_debt=True, now=august_24
    ) == august_28
    assert next_debt_reminder_run(
        31, time(9, 0), 3, august_28, has_debt=True, now=august_28
    ) == datetime(2026, 8, 31, 2, tzinfo=UTC)


def test_disabled_repeat_waits_for_the_next_monthly_anchor() -> None:
    august_25 = datetime(2026, 8, 25, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        25,
        time(9, 0),
        3,
        august_25,
        repeat_enabled=False,
        has_debt=True,
        now=august_25,
    ) == datetime(2026, 9, 26, 2, tzinfo=UTC)


def test_outage_does_not_replay_every_missed_reminder() -> None:
    """A 10-day outage must not fire four reminders a beat tick apart.

    Advancing purely from the missed slot leaves next_run_at in the past, so the
    scheduler would claim it again on the very next tick, and the customer would
    receive one full reminder (image + link + text) per minute until it caught up.
    """
    now = datetime(2026, 8, 20, 18, tzinfo=UTC)
    missed = now - timedelta(days=10)

    following = next_debt_reminder_run(
        18, time(0, 53), 3, missed, has_debt=True, now=now
    )

    # Keeps the 3-day rhythm of the original schedule instead of resetting to now.
    assert following == datetime(2026, 8, 22, 18, tzinfo=UTC)
    assert following > now
    # Feeding the result back in must stay in the future, i.e. no runaway loop.
    assert next_debt_reminder_run(
        18, time(0, 53), 3, following, has_debt=True, now=now
    ) > now


async def test_scheduler_defers_a_legacy_blackout_schedule_before_creating_a_run(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lunar_new_year = datetime(2026, 2, 17, 2, tzinfo=UTC)

    async with sessions() as db:
        account = ZaloAccount(status=BotStatus.CONNECTED)
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="legacy-lunar-blackout",
            name="Lịch cũ trùng mùng một",
            member_count=2,
            is_available=True,
            last_synced_at=lunar_new_year,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/legacy/edit",
        )
        db.add(customer)
        await db.flush()
        db.add(
            DebtReminderAutomation(
                customer_id=customer.id,
                next_run_at=lunar_new_year,
            )
        )
        await db.commit()

    monkeypatch.setattr(debt_reminder_scheduler, "SessionLocal", sessions)
    assert await claim_due_debt_reminders() == []

    async with sessions() as db:
        automation = await db.scalar(select(DebtReminderAutomation))
        assert automation is not None
        assert automation.next_run_at.replace(tzinfo=UTC) == datetime(
            2026, 3, 20, 2, tzinfo=UTC
        )
        assert list((await db.scalars(select(DebtReminderRun))).all()) == []
    await engine.dispose()


def test_extract_spreadsheet_id() -> None:
    assert (
        extract_spreadsheet_id(
            "https://docs.google.com/spreadsheets/d/1Abc_def-234/edit#gid=0"
        )
        == "1Abc_def-234"
    )
    # A folder link used to be accepted and the first sheet inside it guessed at.
    for rejected in (
        "https://drive.google.com/drive/folders/1Abc_def-234",
        "https://docs.google.com/document/d/1Abc_def-234/edit",
        "https://example.com/spreadsheets/d/1Abc_def-234",
    ):
        with pytest.raises(SheetExportError) as error:
            extract_spreadsheet_id(rejected)
        assert error.value.code == "INVALID_SHEET_URL"


def test_crop_white_margins_keeps_content_and_padding() -> None:
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 80, 300, 200), fill="black")

    cropped = crop_white_margins(image, padding=10)

    assert cropped.size == (221, 141)
    assert cropped.getpixel((10, 10)) == (0, 0, 0)
    cropped.close()
    image.close()


def test_encode_png_shrinks_until_the_gateway_accepts_it(monkeypatch) -> None:
    monkeypatch.setattr(google_sheets_service, "MAX_PNG_BYTES", 20_000)
    noisy = Image.frombytes("RGB", (600, 600), os.urandom(600 * 600 * 3))

    data, width, height = google_sheets_service.encode_png_within_limit(noisy)

    assert len(data) <= 20_000
    assert width < 600 and height < 600
    assert data.startswith(b"\x89PNG")
    noisy.close()


async def test_overdue_repeat_stays_due_after_editing_the_config() -> None:
    """Editing the config must not push a still-indebted customer to next month."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 17, 2, tzinfo=UTC)

    async with session_factory() as db:
        account = ZaloAccount(status=BotStatus.CONNECTED)
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="overdue-group",
            name="Khách quá hạn nhắc lại",
            member_count=2,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/sheet-overdue/edit",
        )
        db.add(customer)
        await db.flush()
        db.add(DebtReminderAutomation(customer_id=customer.id, next_run_at=None))
        await db.commit()

        config = DebtReminderUpdate(
            day_of_month=25,
            repeat_interval_days=3,
            send_time="09:00",
            message_parts=[{"type": "text", "text": "Nhắc thanh toán công nợ."}],
        )
        await save_debt_reminder(db, customer.id, config, now=now)
        automation = await db.scalar(select(DebtReminderAutomation))
        assert automation is not None
        db.add(
            DebtReminderRun(
                automation_id=automation.id,
                scheduled_for=now - timedelta(days=10),
                retry_at=now - timedelta(days=10),
                status=DebtReminderStatus.SENT,
                processed_at=now - timedelta(days=10),
                attempt_count=1,
            )
        )
        await db.commit()

        # The repeat (10 days ago + 3 days) is already overdue, so it is due now.
        updated = await save_debt_reminder(db, customer.id, config, now=now)
        assert updated.next_run_at is not None
        assert updated.next_run_at.replace(tzinfo=UTC) == now

        # During the Tết blackout, the same overdue path must resume at the
        # configured 09:00 rather than at the wall-clock time the form was saved.
        tet_now = datetime(2027, 2, 10, 7, 37, tzinfo=UTC)
        updated_during_tet = await save_debt_reminder(
            db,
            customer.id,
            config,
            now=tet_now,
        )
        assert updated_during_tet.next_run_at is not None
        assert updated_during_tet.next_run_at.replace(tzinfo=UTC) == datetime(
            2027, 3, 9, 2, tzinfo=UTC
        )

    await engine.dispose()


async def test_debt_reminder_config_and_three_required_deliveries(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 17, 2, tzinfo=UTC)

    async with session_factory() as db:
        account = ZaloAccount(status=BotStatus.CONNECTED)
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="debt-reminder-group",
            name="Khách hàng công nợ",
            member_count=3,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            id=group.id,
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/sheet-123/edit",
        )
        db.add(customer)
        db.add(DebtReminderAutomation(customer_id=group.id, next_run_at=None))
        await db.commit()

        config = DebtReminderUpdate(
            day_of_month=25,
            send_time="09:00",
            message_parts=[
                {"type": "text", "text": "Vui lòng "},
                {
                    "type": "mention",
                    "user_id": "member-1",
                    "display_name": "Nguyễn An",
                },
                {"type": "text", "text": " thanh toán công nợ giúp mình nhé."},
            ],
        )
        response = await save_debt_reminder(db, customer.id, config, now=now)
        assert response.repeat_enabled is True
        assert response.repeat_interval_days == 3
        assert response.next_run_at is not None
        assert response.next_run_at.replace(tzinfo=UTC) == datetime(
            2026, 8, 25, 2, tzinfo=UTC
        )

        automation = await db.scalar(select(DebtReminderAutomation))
        assert automation is not None
        run = DebtReminderRun(
            automation_id=automation.id,
            scheduled_for=now,
            retry_at=now,
            status=DebtReminderStatus.PROCESSING,
            attempt_count=1,
            claimed_at=now,
        )
        db.add(run)
        await db.commit()
        run_id = run.id

    calls: list[str] = []

    async def get_status():
        return {"status": "CONNECTED"}

    async def get_group_members(_group_id: str):
        return [{"user_id": "member-1", "display_name": "Nguyễn An"}]

    async def export_first_sheet(_sheet_url: str):
        calls.append("export")
        return SheetArtifact(
            file_id="sheet-1",
            file_name="Công nợ tháng 8",
            web_view_link="https://docs.google.com/spreadsheets/d/sheet-1/edit",
            png_data=b"fake-png",
            width=1200,
            height=1600,
        )

    async def send_image(_group_id: str, _image: bytes, **_kwargs):
        calls.append("image")
        return {"message_id": "image-message"}

    async def send_link(_group_id: str, _link: str, **_kwargs):
        calls.append("link")
        return {"message_id": "link-message"}

    async def send_rich_text(
        _group_id: str, _parts: list[dict[str, str]], **_kwargs
    ):
        calls.append("text")
        return {"message_id": "text-message"}

    monkeypatch.setattr(debt_reminder_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(debt_reminder_scheduler.zalo_gateway, "get_status", get_status)
    monkeypatch.setattr(
        debt_reminder_scheduler.zalo_gateway,
        "get_group_members",
        get_group_members,
    )
    monkeypatch.setattr(
        debt_reminder_scheduler.google_sheets,
        "export_first_sheet",
        export_first_sheet,
    )
    monkeypatch.setattr(debt_reminder_scheduler.zalo_gateway, "send_image", send_image)
    monkeypatch.setattr(debt_reminder_scheduler.zalo_gateway, "send_link", send_link)
    monkeypatch.setattr(
        debt_reminder_scheduler.zalo_gateway,
        "send_rich_text",
        send_rich_text,
    )

    await process_debt_reminder(run_id)

    async with session_factory() as db:
        stored_run = await db.get(DebtReminderRun, run_id)
        logs = list(
            await db.scalars(select(BotDeliveryLog).order_by(BotDeliveryLog.created_at))
        )
        assert stored_run is not None
        assert stored_run.status == DebtReminderStatus.SENT
        assert stored_run.image_message_id == "image-message"
        assert stored_run.link_message_id == "link-message"
        assert stored_run.text_message_id == "text-message"
        assert calls == ["export", "image", "link", "text"]
        assert [log.type for log in logs] == [
            DeliveryType.DEBT_REMINDER_IMAGE,
            DeliveryType.DEBT_REMINDER_LINK,
            DeliveryType.DEBT_REMINDER_MESSAGE,
        ]
        assert all(log.status == DeliveryStatus.SENT for log in logs)

        rescheduled = await save_debt_reminder(
            db,
            customer.id,
            config,
            now=now + timedelta(hours=1),
        )
        assert rescheduled.next_run_at is not None
        assert rescheduled.next_run_at.replace(tzinfo=UTC) == now + timedelta(days=3)

    await engine.dispose()
