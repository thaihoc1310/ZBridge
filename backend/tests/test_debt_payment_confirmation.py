from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    BotDeliveryLog,
    Customer,
    DebtPaymentConfirmation,
    DebtPaymentSettings,
    DebtReminderAutomation,
    DebtReminderRun,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import DebtReminderStatus, DeliveryStatus, DeliveryType
from app.schemas.api import IncomingGroupMessage
from app.services.debt_payment_service import apply_payment_confirmation


async def test_trusted_message_marks_paid_without_prior_sent_reminder() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sent_at = datetime(2026, 9, 19, 3, 30, tzinfo=UTC)

    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="paid-message-group",
            name="Khách thanh toán",
            member_count=3,
            is_available=True,
            last_synced_at=sent_at,
        )
        db.add(group)
        await db.flush()
        customer = Customer(id=group.id, zalo_group_id=group.id, has_debt=True)
        automation = DebtReminderAutomation(
            customer_id=group.id, next_run_at=sent_at
        )
        db.add_all(
            [
                customer,
                automation,
                DebtPaymentSettings(
                    id=1,
                    tracked_members=[
                        {
                            "user_id": "employee-1",
                            "display_name": "Thu ngân",
                            "avatar_url": None,
                        }
                    ],
                    phrases=["đã thanh toán"],
                ),
            ]
        )
        await db.flush()
        run = DebtReminderRun(
            automation_id=automation.id,
            scheduled_for=sent_at,
            retry_at=sent_at,
            status=DebtReminderStatus.PENDING,
        )
        db.add(run)
        await db.commit()

        event = IncomingGroupMessage(
            group_id=group.zalo_group_id,
            message_id="paid-message-1",
            sender_id="employee-1",
            sender_display_name="Thu ngân",
            sent_at=sent_at,
            content="KHÁCH ĐÃ   THANH TOÁN!!!",
        )
        send_reply = AsyncMock(return_value={"message_id": "payment-reply-1"})
        with patch(
            "app.services.debt_payment_service.zalo_gateway.send_rich_text",
            send_reply,
        ):
            assert await apply_payment_confirmation(db, event) is True

        await db.refresh(customer)
        await db.refresh(automation)
        await db.refresh(run)
        assert customer.has_debt is False
        assert customer.last_debt_paid_at == sent_at.replace(tzinfo=None)
        assert automation.next_run_at is None
        assert run.status == DebtReminderStatus.CANCELLED
        assert await db.scalar(select(func.count()).select_from(DebtPaymentConfirmation)) == 1
        delivery = await db.scalar(select(BotDeliveryLog))
        assert delivery is not None
        assert delivery.type == DeliveryType.DEBT_PAYMENT_CONFIRMATION
        assert delivery.status == DeliveryStatus.SENT
        assert delivery.zalo_message_id == "payment-reply-1"
        send_reply.assert_awaited_once_with(
            group.zalo_group_id,
            [
                {
                    "type": "mention",
                    "user_id": "employee-1",
                    "display_name": "Thu ngân",
                },
                {"type": "text", "text": " Hệ thống xác nhận đã thanh toán ạ."},
            ],
            idempotency_key=f"debt-payment-confirmation:{customer.id}:paid-message-1",
        )

        # A replayed outbox event must not close a later debt cycle again.
        customer.has_debt = True
        await db.commit()
        assert await apply_payment_confirmation(db, event) is False
        await db.refresh(customer)
        assert customer.has_debt is True

        # A different but delayed message from the previous debt cycle is stale.
        customer.last_debt_paid_at = sent_at + timedelta(hours=1)
        await db.commit()
        stale = event.model_copy(update={"message_id": "paid-message-stale"})
        assert await apply_payment_confirmation(db, stale) is False
        await db.refresh(customer)
        assert customer.has_debt is True

    await engine.dispose()
