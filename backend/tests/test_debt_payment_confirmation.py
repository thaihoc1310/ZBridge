import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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


@pytest.fixture(autouse=True)
def _public_urls(monkeypatch):
    # The group link must use the public app, never the (possibly internal)
    # alert host, so the two are set apart here.
    monkeypatch.setattr(debt_payment_service.app_settings, "app_url", "http://app.example")
    monkeypatch.setattr(
        debt_payment_service.app_settings, "alert_link_base_url", "http://alerts.internal"
    )


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
    # Owing, with a reminder queued: the old flow switched this customer to paid
    # and cancelled the run, so these assertions would fail against it.
    engine, sessions, group_id, customer_id, run_id = await _setup(has_debt=True)
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
            # The debt state is never read either: a customer can pay several
            # times and switching state is the accountant's job.
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
                {
                    "type": "text",
                    "text": f" vào chỉnh sửa công nợ.\nhttp://app.example/customers/{customer_id}",
                },
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
        assert customer.has_debt is True
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


async def test_every_confirmed_message_is_announced_even_several_a_day() -> None:
    """A customer can pay several times; each confirmation reaches the accountant."""
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            for message_id, text, delay in (
                ("pay-10m", "Đã thanh toán 10.000.000", timedelta(0)),
                ("pay-12m", "đã nhận thanh toán 12.000.000", timedelta(minutes=5)),
            ):
                row = await _record_and_classify(
                    db, _event(message_id, text, sent_at=SENT_AT + delay), _verdict(True, 0.95)
                )
                assert await process_confirmation(db, row.id) is True
                assert (await _confirmation(db, message_id)).status == (
                    PaymentConfirmationStatus.SENT
                )
        assert ok.await_count == 4
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


async def test_an_exhausted_notice_fails_and_a_later_confirmation_still_sends() -> None:
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
        second = await _record_and_classify(
            db, _event("pay-2", "đã tt", sent_at=SENT_AT + timedelta(hours=1)), _verdict(True, 0.9)
        )
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            assert await process_confirmation(db, second.id) is True
        assert (await _confirmation(db, "pay-2")).status == PaymentConfirmationStatus.SENT
    await engine.dispose()


async def test_a_customer_without_a_sheet_gets_no_notice_and_no_ai_call() -> None:
    engine, sessions, _group_id, customer_id, _run_id = await _setup()
    enqueue = MagicMock()
    verdict = _verdict(True, 0.99)
    send = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        customer = await db.get(Customer, customer_id)
        customer.debt_file_url = None
        await db.commit()
        with patch(f"{SERVICE}.celery_app.send_task", enqueue), patch(
            f"{SERVICE}.complete_structured", verdict
        ), patch(f"{SERVICE}.zalo_gateway.send_rich_text", send):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        enqueue.assert_not_called()
        verdict.assert_not_awaited()
        send.assert_not_awaited()
        skipped = await _confirmation(db, "pay-1")
        assert skipped.status == PaymentConfirmationStatus.SKIPPED
        assert skipped.ai_reason == debt_payment_service.NO_SHEET_REASON
    await engine.dispose()


async def test_a_sheet_removed_while_the_ai_decided_stops_the_notice() -> None:
    engine, sessions, _group_id, customer_id, _run_id = await _setup()
    send = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        confirmation = await _record_and_classify(
            db, _event("pay-1", "Đã thanh toán"), _verdict(True, 0.95)
        )
        assert confirmation.status == PaymentConfirmationStatus.CONFIRMED
        customer = await db.get(Customer, customer_id)
        customer.debt_file_url = None
        await db.commit()
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", send), patch(
            f"{SERVICE}.zalo_gateway.send_link", send
        ):
            assert await process_confirmation(db, confirmation.id) is True
        send.assert_not_awaited()
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.SKIPPED
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


async def test_no_notification_targets_means_no_notice_and_no_ai_call() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    enqueue = MagicMock()
    async with sessions() as db:
        settings = await db.get(DebtPaymentSettings, 1)
        settings.notification_targets = []
        await db.commit()
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        enqueue.assert_not_called()
        skipped = await _confirmation(db, "pay-1")
        assert skipped.status == PaymentConfirmationStatus.SKIPPED
        assert skipped.ai_reason == debt_payment_service.NO_TARGETS_REASON
    await engine.dispose()


async def test_the_confidence_threshold_is_inclusive() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    async with sessions() as db:
        at = await _record_and_classify(db, _event("at", "Đã thanh toán"), _verdict(True, 0.75))
        below = await _record_and_classify(
            db, _event("below", "Đã thanh toán"), _verdict(True, 0.74)
        )
        assert at.status == PaymentConfirmationStatus.CONFIRMED
        assert below.status == PaymentConfirmationStatus.SKIPPED
    await engine.dispose()


async def test_a_verdict_arriving_after_the_sweep_closed_the_row_posts_nothing() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    enqueue = MagicMock()
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", enqueue):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        confirmation = await _confirmation(db, "pay-1")

        async def slow_verdict(*_args, **_kwargs):
            # The sweep gives up on the row while the model is still answering.
            async with sessions() as other:
                row = await other.get(DebtPaymentConfirmation, confirmation.id)
                row.status = PaymentConfirmationStatus.FAILED
                await other.commit()
            return await _verdict(True, 0.99)()

        with patch(f"{SERVICE}.celery_app.send_task", enqueue), patch(
            f"{SERVICE}.complete_structured", slow_verdict
        ):
            assert await classify_confirmation(db, confirmation.id) is True
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.FAILED
        # Only the classify task was ever queued: no reply after the manual-handling alert.
        assert [call.args[0] for call in enqueue.call_args_list] == [CLASSIFY_TASK]
    await engine.dispose()


async def test_a_duplicate_copy_of_the_reply_task_does_not_send_again() -> None:
    """Two copies of the first attempt: only the one that claimed the row sends."""
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    ok = AsyncMock(return_value={"message_id": "zalo-msg"})
    async with sessions() as db:
        confirmation = await _record_and_classify(
            db, _event("pay-1", "Đã thanh toán"), _verdict(True, 0.95)
        )
        # The other copy claimed it and is mid-send (nothing recorded yet).
        async with sessions() as other:
            row = await other.get(DebtPaymentConfirmation, confirmation.id)
            row.status = PaymentConfirmationStatus.SENDING
            await other.commit()
        with patch(f"{SERVICE}.zalo_gateway.send_rich_text", ok), patch(
            f"{SERVICE}.zalo_gateway.send_link", ok
        ):
            assert await process_confirmation(db, confirmation.id, attempt=0) is True
            ok.assert_not_awaited()
            # The claimant's own retry does resume the send.
            assert await process_confirmation(db, confirmation.id, attempt=1) is True
        assert ok.await_count == 2
        assert len((await db.scalars(select(BotDeliveryLog))).all()) == 2
    await engine.dispose()


async def test_the_gateway_retrying_a_slow_post_is_a_duplicate_not_an_error() -> None:
    """Two requests for one message: the loser hits the unique constraint."""
    engine, sessions, _group_id, customer_id, _run_id = await _setup()
    async with sessions() as db:
        # The first request already committed this message...
        db.add(
            DebtPaymentConfirmation(
                customer_id=customer_id,
                source_message_id="pay-1",
                sender_id="owner-1",
                content="Đã thanh toán",
                matched_phrase="đã thanh toán",
                message_sent_at=SENT_AT,
                status=PaymentConfirmationStatus.PENDING,
            )
        )
        await db.commit()
        # ...after the second one had already run its duplicate check.
        with patch.object(db, "scalar", AsyncMock(return_value=None)), patch(
            f"{SERVICE}.celery_app.send_task", MagicMock()
        ) as enqueue:
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is False
        enqueue.assert_not_called()
        rows = (await db.scalars(select(DebtPaymentConfirmation))).all()
        assert len(rows) == 1
    await engine.dispose()


async def test_a_cancelled_model_call_never_leaves_its_log_processing() -> None:
    """A task cancelled mid-call (deploy, timeout) skips the model-error branch."""
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    async with sessions() as db:
        with patch(f"{SERVICE}.celery_app.send_task", MagicMock()):
            assert await apply_payment_confirmation(db, _event("pay-1", "Đã thanh toán")) is True
        confirmation = await _confirmation(db, "pay-1")
        with patch(
            f"{SERVICE}.complete_structured", AsyncMock(side_effect=asyncio.CancelledError())
        ), pytest.raises(asyncio.CancelledError):
            await classify_confirmation(db, confirmation.id)
        log = await db.scalar(select(ModelCallLog).execution_options(populate_existing=True))
        assert log.status == ModelCallStatus.FAILED
        assert log.outcome == "INTERNAL_ERROR"
        # Still PENDING: the retry (or the stuck sweep) decides what happens next.
        assert (await _confirmation(db, "pay-1")).status == PaymentConfirmationStatus.PENDING
    await engine.dispose()


async def test_model_logs_abandoned_by_a_dead_worker_are_closed() -> None:
    engine, sessions, _group_id, customer_id, _run_id = await _setup()
    async with sessions() as db:
        for minutes, name in ((30, "stale"), (1, "fresh")):
            db.add(
                ModelCallLog(
                    customer_id=customer_id,
                    customer_name=name,
                    trigger=MentionFollowupTrigger.MENTION,
                    provider="fptcloud",
                    model="m",
                    request_payload={},
                    status=ModelCallStatus.PROCESSING,
                    created_at=datetime.now(UTC) - timedelta(minutes=minutes),
                )
            )
        await db.commit()
        assert await debt_payment_service.close_abandoned_model_calls(db) == 1
        rows = {
            row.customer_name: row
            for row in (
                await db.scalars(select(ModelCallLog).execution_options(populate_existing=True))
            ).all()
        }
        assert rows["stale"].status == ModelCallStatus.FAILED
        assert rows["stale"].outcome == "ABANDONED"
        assert rows["fresh"].status == ModelCallStatus.PROCESSING
    await engine.dispose()


async def test_a_final_failure_after_the_tag_went_out_says_only_the_link_is_missing() -> None:
    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    alert = AsyncMock()
    async with sessions() as db:
        confirmation = await _record_and_classify(
            db, _event("pay-1", "Đã thanh toán"), _verdict(True, 0.95)
        )
        with patch(
            f"{SERVICE}.zalo_gateway.send_rich_text",
            AsyncMock(return_value={"message_id": "zalo-text"}),
        ), patch(
            f"{SERVICE}.zalo_gateway.send_link",
            AsyncMock(side_effect=GatewayError("ZALO_GATEWAY_UNAVAILABLE", "down", 503)),
        ), patch(f"{SERVICE}.report_async", alert):
            assert await process_confirmation(db, confirmation.id, attempt=4, final=True) is False
        assert "chưa gửi được link công nợ" in alert.await_args.args[1]
    await engine.dispose()


def test_the_payment_check_is_routed_to_the_ai_worker() -> None:
    # Misrouted, it would run on celery-worker (no model key) and quietly fail.
    from app.celery_app import celery_app

    assert celery_app.amqp.router.route({}, CLASSIFY_TASK)["queue"].name == "ai"
    assert celery_app.amqp.router.route({}, REPLY_TASK)["queue"].name == "celery"


async def test_a_payment_hook_error_does_not_block_replies_and_mentions() -> None:
    """It used to fail the whole event, which the gateway then retried forever."""
    from app.api import internal_events

    engine, sessions, _group_id, _customer_id, _run_id = await _setup()
    scheduled = AsyncMock(return_value={"scheduled": False})
    alert = AsyncMock()
    async with sessions() as db:
        with patch.object(
            internal_events,
            "apply_payment_confirmation",
            AsyncMock(side_effect=RuntimeError("payment feature broke")),
        ), patch.object(internal_events, "schedule_from_incoming_event", scheduled), patch.object(
            internal_events, "report_async", alert
        ), patch.object(internal_events.settings, "zalo_event_secret", "s3cret"):
            result = await internal_events.receive_zalo_event(
                _event("pay-1", "Đã thanh toán"), event_secret="s3cret", db=db
            )
    assert result == {"scheduled": False}
    scheduled.assert_awaited_once()
    assert alert.await_args.args[0] == "DEBT_PAYMENT_CONFIRMATION_HOOK_FAILED"
    await engine.dispose()
