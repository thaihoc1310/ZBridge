from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.dashboard import dashboard
from app.db.database import Base
from app.models import BotDeliveryLog, Customer, ZaloAccount, ZaloGroup
from app.models.entities import DeliveryStatus, DeliveryType


async def test_dashboard_returns_debt_split_and_sent_messages_by_local_hour() -> None:
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
    assert result.messages_today == 3
    assert result.failed_today == 1
    assert len(result.messages_by_hour) == 24
    assert result.messages_by_hour[local_now.hour].count == 2
    assert sum(point.count for point in result.messages_by_hour) == 2
    await engine.dispose()
