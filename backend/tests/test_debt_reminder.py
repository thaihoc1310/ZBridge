import os
from datetime import UTC, datetime, time, timedelta

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
from app.services.debt_reminder_scheduler import process_debt_reminder
from app.services.debt_reminder_service import (
    next_debt_reminder_run,
    next_monthly_run,
    save_debt_reminder,
)
from app.services.google_sheets_service import (
    SheetArtifact,
    crop_white_margins,
    extract_drive_folder_id,
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
        now=datetime(2027, 2, 1, tzinfo=UTC),
    )
    assert february_run == datetime(2027, 2, 28, 2, tzinfo=UTC)


def test_next_debt_reminder_repeats_and_preserves_monthly_anchor() -> None:
    send_time = time(9, 0)
    august_25 = datetime(2026, 8, 25, 2, tzinfo=UTC)
    september_24 = datetime(2026, 9, 24, 2, tzinfo=UTC)

    assert next_debt_reminder_run(
        25, send_time, 3, august_25, has_debt=True, now=august_25
    ) == datetime(2026, 8, 28, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        25, send_time, 3, september_24, has_debt=True, now=september_24
    ) == datetime(2026, 9, 25, 2, tzinfo=UTC)
    assert next_debt_reminder_run(
        25, send_time, 3, august_25, has_debt=False, now=august_25
    ) == datetime(2026, 9, 25, 2, tzinfo=UTC)


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


def test_extract_drive_folder_id() -> None:
    assert (
        extract_drive_folder_id(
            "https://drive.google.com/drive/folders/1Abc_def-234?usp=sharing"
        )
        == "1Abc_def-234"
    )


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
            folder_url="https://drive.google.com/drive/folders/folder-overdue",
        )
        db.add(customer)
        await db.commit()

        config = DebtReminderUpdate(
            enabled=True,
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
            folder_url="https://drive.google.com/drive/folders/folder-123",
        )
        db.add(customer)
        await db.commit()

        config = DebtReminderUpdate(
            enabled=True,
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
        assert response.enabled is True
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

    async def export_first_sheet(_folder_url: str):
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

    async def send_link(_group_id: str, _link: str):
        calls.append("link")
        return {"message_id": "link-message"}

    async def send_rich_text(_group_id: str, _parts: list[dict[str, str]]):
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
