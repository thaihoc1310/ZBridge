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
    MentionAutomation,
    MentionContextMessage,
    ModelCallLog,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    DebtReminderStatus,
    DeliveryStatus,
    DeliveryType,
    MentionFollowupTrigger,
    ModelCallStatus,
    PaymentConfirmationStatus,
)
from app.schemas.api import IncomingGroupMessage
from app.services import debt_payment_service
from app.services.debt_payment_service import (
    CLASSIFY_TASK,
    REPLY_TASK,
    PaymentConfirmationVerdict,
    apply_payment_confirmation,
    classify_confirmation,
    expire_stuck_confirmations,
    process_confirmation,
)
from app.services.mention_classifier import StructuredCompletion
from app.services.zalo_gateway_client import GatewayError
from app.tasks import debt_reminder_tasks
from app.tasks.debt_reminder_tasks import (
    classify_payment_confirmation,
    send_payment_confirmation_reply,
)

SERVICE = "app.services.debt_payment_service"
SHEET = "https://docs.google.com/spreadsheets/d/debt-sheet"
# 12:32 Vietnam time, the owner's usual pattern: a screenshot, then the phrase.
SENT_AT = datetime(2026, 9, 28, 5, 32, 49, tzinfo=UTC)


async def _setup(*, has_debt: bool = False):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="paid-message-group",
            name="Hùng TM",
            member_count=3,
            is_available=True,
            last_synced_at=SENT_AT,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            id=group.id, zalo_group_id=group.id, has_debt=has_debt, debt_file_url=SHEET
        )
        debt = DebtReminderAutomation(customer_id=group.id, next_run_at=None)
        mention = MentionAutomation(zalo_group_id=group.id, enabled=True)
        db.add_all(
            [
                customer,
                debt,
                mention,
                DebtPaymentSettings(
                    id=1,
                    tracked_members=[
                        {"user_id": "owner-1", "display_name": "Anh Tuấn", "avatar_url": None}
                    ],
                    notification_targets=[
                        {"user_id": "accountant-1", "display_name": "Kế toán", "avatar_url": None}
                    ],
                    phrases=["đã thanh toán", "đã nhận thanh toán", "đã tt"],
                ),
            ]
        )
        await db.flush()
        db.add(
            MentionContextMessage(
                automation_id=mention.id,
                message_id="receipt-image",
                message_aliases=["receipt-image"],
                sender_id="owner-1",
                sender_display_name="Anh Tuấn",
                content="[image]",
                mentions=[],
                sent_at=SENT_AT - timedelta(seconds=6),
            )
        )
        run = DebtReminderRun(
            automation_id=debt.id,
            scheduled_for=SENT_AT,
            retry_at=SENT_AT,
            status=DebtReminderStatus.PENDING,
        )
        db.add(run)
        await db.commit()
        return engine, sessions, group.zalo_group_id, customer.id, run.id


def _event(message_id: str, content: str, *, sent_at: datetime = SENT_AT, sender="owner-1"):
    return IncomingGroupMessage(
        group_id="paid-message-group",
        message_id=message_id,
        sender_id=sender,
        sender_display_name="Anh Tuấn",
        sent_at=sent_at,
        content=content,
    )


def _verdict(confirmed: bool, confidence: float) -> AsyncMock:
    return AsyncMock(
        return_value=StructuredCompletion(
            parsed=PaymentConfirmationVerdict(
                is_payment_confirmation=confirmed, confidence=confidence, reason="test"
            ),
            input_tokens=10,
            output_tokens=5,
            latency_ms=42,
        )
    )


def _page(customer_id) -> str:
    return debt_payment_service.customer_link(customer_id)


async def _confirmation(db, message_id: str) -> DebtPaymentConfirmation:
    row = await db.scalar(
        select(DebtPaymentConfirmation)
        .where(DebtPaymentConfirmation.source_message_id == message_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _record_and_classify(db, event, verdict) -> DebtPaymentConfirmation:
    enqueue = MagicMock()
    with patch(f"{SERVICE}.celery_app.send_task", enqueue), patch(
        f"{SERVICE}.complete_structured", verdict
    ):
        assert await apply_payment_confirmation(db, event) is True
        confirmation = await _confirmation(db, event.message_id)
        assert enqueue.call_args_list[0].args == (CLASSIFY_TASK,)
        assert await classify_confirmation(db, confirmation.id) is True
    return await _confirmation(db, event.message_id)


async def test_an_affirmative_message_notifies_twice_and_leaves_the_debt_alone() -> None:
    engine, sessions, group_id, customer_id, run_id = await _setup(has_debt=False)
    key = f"debt-payment-confirmation:{customer_id}:pay-1"
    verdict = _verdict(True, 0.95)
    enqueue = MagicMock()
    send_text = AsyncMock(return_value={"message_id": "zalo-text"})
    send_link = AsyncMock(return_value={"message_id": "zalo-link"})
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", enqueue), patch(
            f"{SERVICE}.complete_structured", verdict
        ), patch(f"{SERVICE}.zalo_gateway.send_rich_text", send_text), patch(
            f"{SERVICE}.zalo_gateway.send_link", send_link
        ):
            # Recorded although the customer is already marked paid: a customer
            # can pay several times and switching state is the accountant's job.
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
            send_text.assert_not_awaited()
            confirmation = await _confirmation(db, "pay-1")
            assert confirmation.status == PaymentConfirmationStatus.PENDING
            assert enqueue.call_args.args == (CLASSIFY_TASK,)
            assert enqueue.call_args.kwargs["args"] == [str(confirmation.id)]

            assert await classify_confirmation(db, confirmation.id) is True
            assert enqueue.call_args.args == (REPLY_TASK,)
            assert await process_confirmation(db, confirmation.id) is True

        payload = verdict.await_args.args[0]
        assert payload["current_message"] == {"sender": "S", "text": "Đã thanh toán"}
        assert payload["earlier_messages"] == [{"sender": "S", "text": "[image]"}]
        assert verdict.await_args.kwargs["schema"] is PaymentConfirmationVerdict

        send_text.assert_awaited_once_with(
            group_id,
            [
                {"type": "text", "text": "Hệ thống đã xác nhận thanh toán, vui lòng "},
                {"type": "mention", "user_id": "accountant-1", "display_name": "Kế toán"},
                {"type": "text", "text": f" vào chỉnh sửa công nợ.\n{_page(customer_id)}"},
            ],
            idempotency_key=key,
        )
        send_link.assert_awaited_once_with(group_id, SHEET, idempotency_key=f"{key}:link")

        confirmation = await _confirmation(db, "pay-1")
        assert confirmation.status == PaymentConfirmationStatus.SENT
        assert confirmation.applied_at is not None
        assert confirmation.ai_confidence == 0.95
        customer = await db.get(Customer, customer_id)
        await db.refresh(customer)
        assert customer.has_debt is False
        assert customer.last_debt_paid_at is None
        # Reminders are no longer touched either.
        run = await db.get(DebtReminderRun, run_id)
        await db.refresh(run)
        assert run.status == DebtReminderStatus.PENDING
        log = await db.scalar(select(ModelCallLog))
        assert log.trigger == MentionFollowupTrigger.PAYMENT_CONFIRMATION
        assert log.status == ModelCallStatus.SUCCEEDED
        assert log.outcome == "SCHEDULED"
        deliveries = (await db.scalars(select(BotDeliveryLog))).all()
        assert [(d.type, d.status) for d in deliveries] == [
            (DeliveryType.DEBT_PAYMENT_CONFIRMATION, DeliveryStatus.SENT)
        ] * 2

        # A replayed or backfilled event does not start a second check.
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is False
    await engine.dispose()


async def test_a_question_or_an_unsure_verdict_posts_nothing() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    async with sessions() as db:
        question = await _record_and_classify(
            db, _event("ask-1", "đã thanh toán chưa em?"), _verdict(False, 0.97)
        )
        unsure = await _record_and_classify(
            db, _event("unsure-1", "đã tt"), _verdict(True, 0.5)
        )
        assert question.status == PaymentConfirmationStatus.SKIPPED
        assert unsure.status == PaymentConfirmationStatus.SKIPPED
        # A skipped row is never sent, even if a send task somehow runs for it.
        send = AsyncMock()
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", send):
            assert await process_confirmation(db, question.id) is True
        send.assert_not_awaited()
    await engine.dispose()


async def test_a_second_confirmation_the_same_day_is_not_announced_again() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            # A question first must not use up the day's notice.
            asked = await _record_and_classify(
                db, _event("ask", "đã thanh toán chưa anh?"), _verdict(False, 0.9)
            )
            assert asked.status == PaymentConfirmationStatus.SKIPPED
            first = await _record_and_classify(
                db, _event("pay-10m", "Đã thanh toán 10.000.000"), _verdict(True, 0.95)
            )
            assert await process_confirmation(db, first.id) is True
            second = await _record_and_classify(
                db,
                _event(
                    "pay-12m",
                    "đã nhận thanh toán 12.000.000",
                    sent_at=SENT_AT + timedelta(hours=3),
                ),
                _verdict(True, 0.95),
            )
            assert await process_confirmation(db, second.id) is True
            assert ok.await_count == 2
            assert (await _confirmation(db, "pay-10m")).status == PaymentConfirmationStatus.SENT
            assert (await _confirmation(db, "pay-12m")).status == (
                PaymentConfirmationStatus.DUPLICATE
            )

            # The next day (Vietnam time) is a new notice.
            tomorrow = await _record_and_classify(
                db,
                _event("pay-next-day", "Đã thanh toán", sent_at=SENT_AT + timedelta(days=1)),
                _verdict(True, 0.95),
            )
            assert await process_confirmation(db, tomorrow.id) is True
            assert ok.await_count == 4
            assert (await _confirmation(db, "pay-next-day")).status == (
                PaymentConfirmationStatus.SENT
            )
    await engine.dispose()


async def test_the_day_boundary_is_vietnam_midnight_not_utc() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    # 23:30 and 00:30 Vietnam time: the same UTC day, two different local days.
    late = datetime(2026, 9, 28, 16, 30, tzinfo=UTC)
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            moments = (("late", late), ("after-midnight", late + timedelta(hours=1)))
            for message_id, sent_at in moments:
                row = await _record_and_classify(
                    db, _event(message_id, "Đã thanh toán", sent_at=sent_at), _verdict(True, 0.9)
                )
                assert await process_confirmation(db, row.id) is True
                assert (await _confirmation(db, message_id)).status == (
                    PaymentConfirmationStatus.SENT
                )
    await engine.dispose()


async def test_an_ai_outage_retries_alerting_then_gives_up_without_posting() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    alert = AsyncMock()
    down = AsyncMock(side_effect=TimeoutError("model took too long"))
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", MagicMock()), patch(
            f"{SERVICE}.complete_structured", down
        ), patch(f"{SERVICE}.report_async", alert):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
            confirmation = await _confirmation(db, "pay-1")
            assert await classify_confirmation(db, confirmation.id, attempt=0) is False
            assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_RETRY"
            assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.PENDING
            assert await classify_confirmation(db, confirmation.id, attempt=3, final=True) is False
        assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_FAILED"
        assert alert.await_count == 2
        failed = await _confirmation(db, "pay-1")
        assert failed.status == PaymentConfirmationStatus.FAILED
        logs = (await db.scalars(select(ModelCallLog))).all()
        assert [log.status for log in logs] == [ModelCallStatus.FAILED] * 2
    await engine.dispose()


async def test_a_failed_notice_alerts_and_resumes_where_it_stopped() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    send_text = AsyncMock(return_value={"message_id": "zalo-text"})
    send_link = AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503))
    alert = AsyncMock()
    async with sessions() as db:
        confirmation = await _record_and_classify(
            db, _event("pay-1", "Đã thanh toán"), _verdict(True, 0.95)
        )
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", send_text), patch(
            f"{SERVICE}.zalo_gateway.send_link", send_link
        ), patch(f"{SERVICE}.report_async", alert):
            assert await process_confirmation(db, confirmation.id, attempt=0) is False
            assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_RETRY"
            assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.SENDING
            send_link.side_effect = None
            send_link.return_value = {"message_id": "zalo-link"}
            assert await process_confirmation(db, confirmation.id, attempt=1) is True
        # The accepted notice is not posted again; only the link was outstanding.
        assert send_text.await_count == 1
        assert send_link.await_count == 2
        done = await _confirmation(db, "pay-1")
        assert done.status == PaymentConfirmationStatus.SENT
        assert done.link_message_id == "zalo-link"
    await engine.dispose()


async def test_an_exhausted_notice_fails_and_frees_the_day_for_another_try() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    down = AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503))
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        first = await _record_and_classify(
            db, _event("pay-1", "Đã thanh toán"), _verdict(True, 0.9)
        )
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", down), patch(
            f"{SERVICE}.report_async", AsyncMock()
        ):
            assert await process_confirmation(db, first.id, attempt=4, final=True) is False
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.FAILED
        # Staff were never told, so a later confirmation the same day is not a duplicate.
        second = await _record_and_classify(
            db, _event("pay-2", "đã tt", sent_at=SENT_AT + timedelta(hours=1)), _verdict(True, 0.9)
        )
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            assert await process_confirmation(db, second.id) is True
        assert (await _confirmation(db, "pay-2")).status == PaymentConfirmationStatus.SENT
    await engine.dispose()


async def test_untracked_senders_and_unmatched_text_are_ignored() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    enqueue = MagicMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(
                db, _event("x-1", "Đã thanh toán", sender="stranger")
            ) is False
            assert await apply_payment_confirmation(db, _event("x-2", "ok em")) is False
        enqueue.assert_not_called()
        assert await db.scalar(select(DebtPaymentConfirmation)) is None
    await engine.dispose()


async def test_a_queue_outage_closes_the_confirmation_and_alerts() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    alert = AsyncMock()
    async with sessions() as db:
        with patch(
            f"{SERVICE}.celery_app.send_task", MagicMock(side_effect=OSError("redis down"))
        ), patch(f"{SERVICE}.report_async", alert):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.FAILED
        assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_FAILED"
    await engine.dispose()


async def test_a_confirmation_whose_task_was_lost_is_closed_and_alerted() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    alert = AsyncMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", MagicMock()):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        confirmation = await _confirmation(db, "pay-1")
        with patch(f"{SERVICE}.report_async", alert):
            # Recent: its task may still be retrying, so it is left alone.
            assert await expire_stuck_confirmations(db) == 0
            confirmation.created_at = datetime.now(UTC) - timedelta(hours=3)
            await db.commit()
            assert await expire_stuck_confirmations(db) == 1
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.FAILED
        alert.assert_awaited_once()
        assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_FAILED"
    await engine.dispose()


def _run_task_recording(task, patched_name: str):
    calls: list[tuple[bool, int]] = []

    async def fail(_confirmation_id, final, attempt):
        calls.append((final, attempt))
        if attempt == 1:
            raise RuntimeError("database blip")
        return False

    countdowns: list[float] = []
    original_retry = task.retry

    def spy_retry(*args, **kwargs):
        countdowns.append(kwargs["countdown"])
        return original_retry(*args, **kwargs)

    with patch.object(debt_reminder_tasks, patched_name, fail), patch.object(
        task, "retry", spy_retry
    ):
        task.apply(args=[str(uuid.uuid4())])
    return calls, countdowns


def test_the_classify_task_retries_on_schedule_and_only_the_last_attempt_is_final() -> None:
    calls, countdowns = _run_task_recording(classify_payment_confirmation, "_classify")
    assert calls == [(False, 0), (False, 1), (False, 2), (True, 3)]
    assert countdowns == [30, 120, 300]


def test_the_reply_task_retries_on_schedule_and_only_the_last_attempt_is_final() -> None:
    calls, countdowns = _run_task_recording(send_payment_confirmation_reply, "_deliver_reply")
    assert calls == [(False, 0), (False, 1), (False, 2), (False, 3), (True, 4)]
    assert countdowns == [60, 300, 900, 1800]
