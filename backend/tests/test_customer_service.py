from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import BotDeliveryLog, Customer, ZaloAccount, ZaloGroup
from app.models.entities import DeliveryStatus, DeliveryType
from app.schemas.api import CustomerUpdate
from app.services import customer_service
from app.services.customer_service import update_customer
from app.services.delivery_service import list_delivery_logs
from app.services.google_sheets_service import SheetExportError


async def test_customer_fields_and_debt_paid_timestamp(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Saving a debt file asks Google whether it can read it; stub that out.
    async def describe(url: str) -> tuple[str, str]:
        return "example", "Công nợ tháng 8"

    monkeypatch.setattr(customer_service.google_sheets, "describe", describe)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="customer-group",
            name="Công ty Minh Anh",
            member_count=3,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        await db.commit()

        owing = await update_customer(
            db,
            group.id,
            CustomerUpdate(
                has_debt=True,
                note="Cần đối soát cuối tháng",
                debt_file_url="https://docs.google.com/spreadsheets/d/example/edit",
            ),
        )
        assert owing.has_debt is True
        assert owing.last_debt_paid_at is None
        assert owing.note == "Cần đối soát cuối tháng"
        assert owing.debt_file_url == "https://docs.google.com/spreadsheets/d/example/edit"

        paid = await update_customer(db, group.id, CustomerUpdate(has_debt=False))
        assert paid.has_debt is False
        assert paid.last_debt_paid_at is not None

        db.add(
            BotDeliveryLog(
                customer_id=group.id,
                type=DeliveryType.MENTION_AUTOMATION,
                status=DeliveryStatus.FAILED,
                error_code="ZALO_TIMEOUT",
                error_message="Không nhận được phản hồi từ Zalo.",
            )
        )
        await db.commit()
        activity = await list_delivery_logs(
            db,
            search="Minh Anh",
            status=DeliveryStatus.FAILED,
            today=True,
            page=1,
            limit=25,
        )
        assert activity.total == 1
        assert activity.items[0].customer_name == "Công ty Minh Anh"
        assert activity.items[0].error_code == "ZALO_TIMEOUT"

    await engine.dispose()


async def test_saving_a_debt_file_rejects_a_link_google_cannot_read(monkeypatch) -> None:
    """The link is checked while somebody is looking at the form.

    A folder link, a typo, or a sheet nobody shared used to be discovered at
    08:00 on the day a reminder was due, as a failed run.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def refuse(url: str) -> tuple[str, str]:
        raise SheetExportError(
            "INVALID_SHEET_URL", "Đường dẫn phải là link Google Sheets."
        )

    monkeypatch.setattr(customer_service.google_sheets, "describe", refuse)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="g-1",
            name="Khách hàng A",
            member_count=3,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        await db.commit()

        with pytest.raises(AppError) as error:
            await update_customer(
                db,
                group.id,
                CustomerUpdate(
                    debt_file_url="https://drive.google.com/drive/folders/abc"
                ),
            )
        assert error.value.code == "INVALID_SHEET_URL"

        customer = await db.scalar(select(Customer))
        assert customer.debt_file_url is None, "khong duoc luu link chua kiem tra duoc"

        # Clearing it needs no round trip to Google.
        cleared = await update_customer(db, group.id, CustomerUpdate(debt_file_url=""))
        assert cleared.debt_file_url is None
    await engine.dispose()
