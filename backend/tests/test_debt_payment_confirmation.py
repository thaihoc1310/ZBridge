import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
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
from app.services.debt_payment_service import (
    REPLY_TASK,
    apply_payment_confirmation,
    expire_stuck_confirmations,
    process_confirmation,
)
from app.services.zalo_gateway_client import GatewayError
from app.tasks import debt_reminder_tasks
from app.tasks.debt_reminder_tasks import send_payment_confirmation_reply


async def _paid_customer_setup():
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
        customer = Customer(
            id=group.id,
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/debt-sheet",
        )
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
                    notification_targets=[
                        {
                            "user_id": "accountant-1",
                            "display_name": "Kế toán",
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
    return engine, sessions, group.zalo_group_id, customer.id, run.id, event, sent_at


SERVICE = "app.services.debt_payment_service"
SHEET = "https://docs.google.com/spreadsheets/d/debt-sheet"


def _expected_parts() -> list[dict[str, str]]:
    return [
        {"type": "text", "text": "Hệ thống đã xác nhận thanh toán, vui lòng "},
        {"type": "mention", "user_id": "accountant-1", "display_name": "Kế toán"},
        {"type": "text", "text": " vào chỉnh sửa công nợ."},
    ]


async def test_the_event_only_records_and_queues_then_the_task_notifies_and_pays() -> None:
    engine, sessions, group_id, customer_id, run_id, event, sent_at = (
        await _paid_customer_setup()
    )
    key = f"debt-payment-confirmation:{customer_id}:paid-message-1"

    async def still_owes(*_args, **_kwargs):
        async with sessions() as other:
            assert (await other.get(Customer, customer_id)).has_debt is True
        return {"message_id": "zalo-msg"}

    send_text = AsyncMock(side_effect=still_owes)
    send_link = AsyncMock(side_effect=still_owes)
    enqueue = MagicMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", send_text), patch(
            f"{SERVICE}.zalo_gateway.send_link", send_link
        ), patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, event) is True
            # The event request never talks to Zalo: it must stay fast.
            send_text.assert_not_awaited()
            confirmation = await db.scalar(select(DebtPaymentConfirmation))
            enqueue.assert_called_once()
            assert enqueue.call_args.args == (REPLY_TASK,)
            assert enqueue.call_args.kwargs["args"] == [str(confirmation.id)]
            assert "countdown" not in enqueue.call_args.kwargs
            assert (await db.get(Customer, customer_id)).has_debt is True

            assert await process_confirmation(db, confirmation.id) is True

        send_text.assert_awaited_once_with(group_id, _expected_parts(), idempotency_key=key)
        send_link.assert_awaited_once_with(group_id, SHEET, idempotency_key=f"{key}:link")
        customer = await db.get(Customer, customer_id)
        await db.refresh(customer)
        assert customer.has_debt is False
        assert customer.last_debt_paid_at == sent_at.replace(tzinfo=None)
        automation = await db.scalar(select(DebtReminderAutomation))
        assert automation.next_run_at is None
        assert (await db.get(DebtReminderRun, run_id)).status == DebtReminderStatus.CANCELLED
        await db.refresh(confirmation)
        assert confirmation.applied_at is not None
        assert confirmation.reply_message_id == confirmation.link_message_id == "zalo-msg"
        deliveries = (await db.scalars(select(BotDeliveryLog))).all()
        assert [(d.type, d.status) for d in deliveries] == [
            (DeliveryType.DEBT_PAYMENT_CONFIRMATION, DeliveryStatus.SENT)
        ] * 2

        # A replayed outbox event must not close a later debt cycle again.
        customer.has_debt = True
        await db.commit()
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, event) is False
        await db.refresh(customer)
        assert customer.has_debt is True

        # A different but delayed message from the previous debt cycle is stale.
        customer.last_debt_paid_at = sent_at + timedelta(hours=1)
        await db.commit()
        stale = event.model_copy(update={"message_id": "paid-message-stale"})
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, stale) is False
        await db.refresh(customer)
        assert customer.has_debt is True
        assert enqueue.call_count == 1

    await engine.dispose()


async def test_failed_notice_keeps_debt_open_alerts_and_resumes_where_it_stopped() -> None:
    engine, sessions, _group_id, customer_id, _run_id, event, _sent_at = (
        await _paid_customer_setup()
    )
    send_text = AsyncMock(return_value={"message_id": "zalo-text"})
    send_link = AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503))
    alert = AsyncMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", send_text), patch(
            f"{SERVICE}.zalo_gateway.send_link", send_link
        ), patch(f"{SERVICE}.celery_app.send_task", MagicMock()), patch(
            f"{SERVICE}.report_async", alert
        ):
            assert await apply_payment_confirmation(db, event) is True
            confirmation = await db.scalar(select(DebtPaymentConfirmation))
            assert await process_confirmation(db, confirmation.id, attempt=0) is False
            assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_RETRY"
            assert alert.await_args.kwargs["dedup_key"] == (
                f"DEBT_PAYMENT_CONFIRMATION_RETRY:{confirmation.id}:0"
            )
            customer = await db.get(Customer, customer_id)
            assert customer.has_debt is True
            await db.refresh(confirmation)
            assert confirmation.reply_message_id == "zalo-text"
            assert confirmation.applied_at is None

            # Staff repeating "đã thanh toán" while the notice retries must not
            # start a second pair of messages.
            again = event.model_copy(update={"message_id": "paid-message-2"})
            assert await apply_payment_confirmation(db, again) is False

            # Every failed attempt reaches Telegram under its own key.
            assert await process_confirmation(db, confirmation.id, attempt=1) is False
            assert alert.await_args.kwargs["dedup_key"].endswith(":1")

            send_link.side_effect = None
            send_link.return_value = {"message_id": "zalo-link"}
            assert await process_confirmation(db, confirmation.id, attempt=2) is True

        # The accepted text is not posted again; only the link was outstanding.
        assert send_text.await_count == 1
        assert send_link.await_count == 3
        await db.refresh(customer)
        await db.refresh(confirmation)
        assert customer.has_debt is False
        assert confirmation.applied_at is not None
        assert confirmation.link_message_id == "zalo-link"

    await engine.dispose()


async def test_exhausted_retries_leave_debt_open_alert_and_free_the_customer() -> None:
    engine, sessions, _group_id, customer_id, _run_id, event, _sent_at = (
        await _paid_customer_setup()
    )
    down = AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503))
    alert = AsyncMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", down), patch(
            f"{SERVICE}.celery_app.send_task", MagicMock()
        ), patch(f"{SERVICE}.report_async", alert):
            assert await apply_payment_confirmation(db, event) is True
            confirmation = await db.scalar(select(DebtPaymentConfirmation))
            assert await process_confirmation(
                db, confirmation.id, final=True, attempt=4
            ) is False

        assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_FAILED"
        await db.refresh(confirmation)
        assert confirmation.failed_at is not None
        assert (await db.get(Customer, customer_id)).has_debt is True
        # A later run of the task for a closed confirmation does nothing.
        assert await process_confirmation(db, confirmation.id) is True
        assert down.await_count == 1

        ok = AsyncMock(return_value={"message_id": "zalo-msg"})
        enqueue = MagicMock()
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ), patch(f"{SERVICE}.celery_app.send_task", enqueue):
            again = event.model_copy(update={"message_id": "paid-message-2"})
            assert await apply_payment_confirmation(db, again) is True
            second = (
                await db.scalars(
                    select(DebtPaymentConfirmation).where(
                        DebtPaymentConfirmation.source_message_id == "paid-message-2"
                    )
                )
            ).one()
            assert await process_confirmation(db, second.id) is True
        customer = await db.get(Customer, customer_id)
        await db.refresh(customer)
        assert customer.has_debt is False

    await engine.dispose()


async def test_when_the_queue_is_down_one_attempt_runs_in_process() -> None:
    engine, sessions, _group_id, customer_id, _run_id, event, _sent_at = (
        await _paid_customer_setup()
    )
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ), patch(
            f"{SERVICE}.celery_app.send_task", MagicMock(side_effect=OSError("redis down"))
        ):
            assert await apply_payment_confirmation(db, event) is True
        assert ok.await_count == 2
        customer = await db.get(Customer, customer_id)
        await db.refresh(customer)
        assert customer.has_debt is False

    await engine.dispose()


async def test_queue_down_and_send_failing_closes_the_confirmation_and_alerts() -> None:
    engine, sessions, _group_id, customer_id, _run_id, event, _sent_at = (
        await _paid_customer_setup()
    )
    alert = AsyncMock()
    async with sessions() as db:
        with patch(
            f"{SERVICE}.zalo_gateway.send_rich_text",
            AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503)),
        ), patch(
            f"{SERVICE}.celery_app.send_task", MagicMock(side_effect=OSError("redis down"))
        ), patch(f"{SERVICE}.report_async", alert):
            assert await apply_payment_confirmation(db, event) is True
        confirmation = await db.scalar(select(DebtPaymentConfirmation))
        assert confirmation.failed_at is not None
        assert (await db.get(Customer, customer_id)).has_debt is True
        assert [call.args[0] for call in alert.await_args_list] == [
            "DEBT_PAYMENT_CONFIRMATION_FAILED"
        ]

    await engine.dispose()


async def test_a_confirmation_whose_task_was_lost_is_closed_and_alerted() -> None:
    engine, sessions, _group_id, customer_id, _run_id, event, _sent_at = (
        await _paid_customer_setup()
    )
    alert = AsyncMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", MagicMock()):
            assert await apply_payment_confirmation(db, event) is True
        confirmation = await db.scalar(select(DebtPaymentConfirmation))
        with patch(f"{SERVICE}.report_async", alert):
            # Recent: its task may still be retrying, so it is left alone.
            assert await expire_stuck_confirmations(db) == 0
            confirmation.created_at = datetime.now(UTC) - timedelta(hours=3)
            await db.commit()
            assert await expire_stuck_confirmations(db) == 1
        await db.refresh(confirmation)
        assert confirmation.failed_at is not None
        assert (await db.get(Customer, customer_id)).has_debt is True
        alert.assert_awaited_once()
        assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_FAILED"

    await engine.dispose()


def test_reply_task_retries_on_schedule_and_marks_only_the_last_attempt_final() -> None:
    calls: list[tuple[bool, int]] = []

    async def fail(_confirmation_id, final, attempt):
        calls.append((final, attempt))
        if attempt == 1:
            raise RuntimeError("database blip")
        return False

    countdowns: list[float] = []
    original_retry = send_payment_confirmation_reply.retry

    def spy_retry(*args, **kwargs):
        countdowns.append(kwargs["countdown"])
        return original_retry(*args, **kwargs)

    with patch.object(debt_reminder_tasks, "_deliver_reply", fail), patch.object(
        send_payment_confirmation_reply, "retry", spy_retry
    ):
        send_payment_confirmation_reply.apply(args=[str(uuid.uuid4())])
    assert calls == [(False, 0), (False, 1), (False, 2), (False, 3), (True, 4)]
    assert countdowns == [60, 300, 900, 1800]
