from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import BotDeliveryLog, Customer, ZaloAccount, ZaloGroup
from app.models.entities import DeliveryStatus, DeliveryType
from app.services.log_retention import delete_expired_delivery_logs


async def test_delivery_logs_are_deleted_only_after_30_days() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 17, 2, tzinfo=UTC)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="retention-group",
            name="Khách hàng kiểm thử retention",
            member_count=3,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        await db.flush()
        db.add_all(
            [
                BotDeliveryLog(
                    customer_id=group.id,
                    type=DeliveryType.MENTION_AUTOMATION,
                    status=DeliveryStatus.SENT,
                    created_at=now - timedelta(days=31),
                ),
                BotDeliveryLog(
                    customer_id=group.id,
                    type=DeliveryType.MENTION_AUTOMATION,
                    status=DeliveryStatus.FAILED,
                    created_at=now - timedelta(days=30),
                ),
                BotDeliveryLog(
                    customer_id=group.id,
                    type=DeliveryType.MANUAL_MESSAGE,
                    status=DeliveryStatus.SENT,
                    created_at=now - timedelta(days=29),
                ),
            ]
        )
        await db.commit()

        deleted_count = await delete_expired_delivery_logs(db, now=now)
        remaining_logs = list(
            await db.scalars(select(BotDeliveryLog).order_by(BotDeliveryLog.created_at))
        )

        assert deleted_count == 1
        assert len(remaining_logs) == 2
        assert remaining_logs[0].created_at == (now - timedelta(days=30)).replace(tzinfo=None)

    await engine.dispose()
