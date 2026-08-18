from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import BotDeliveryLog, Customer, ZaloAccount, ZaloGroup
from app.models.entities import DeliveryStatus, DeliveryType
from app.schemas.api import CustomerUpdate
from app.services.customer_service import update_customer
from app.services.delivery_service import list_delivery_logs


async def test_customer_fields_and_debt_paid_timestamp() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

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
                folder_url="https://drive.google.com/drive/folders/example",
            ),
        )
        assert owing.has_debt is True
        assert owing.last_debt_paid_at is None
        assert owing.note == "Cần đối soát cuối tháng"
        assert owing.folder_url == "https://drive.google.com/drive/folders/example"

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
