from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    BotDeliveryLog,
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionFollowup,
    ModelCallLog,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    DebtReminderStatus,
    DeliveryStatus,
    DeliveryType,
    MentionFollowupStatus,
    MentionFollowupTrigger,
    ModelCallStatus,
)
from app.services.log_retention import (
    delete_expired_delivery_logs,
    delete_expired_model_call_logs,
)


async def test_delivery_logs_are_deleted_only_after_seven_days() -> None:
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
                    created_at=now - timedelta(days=8),
                ),
                BotDeliveryLog(
                    customer_id=group.id,
                    type=DeliveryType.MENTION_AUTOMATION,
                    status=DeliveryStatus.FAILED,
                    created_at=now - timedelta(days=7),
                ),
                BotDeliveryLog(
                    customer_id=group.id,
                    type=DeliveryType.MANUAL_MESSAGE,
                    status=DeliveryStatus.SENT,
                    created_at=now - timedelta(days=6),
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
        assert remaining_logs[0].created_at == (now - timedelta(days=7)).replace(tzinfo=None)

    await engine.dispose()


async def test_model_call_logs_keep_exactly_seven_days() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 24, 2, tzinfo=UTC)

    async with session_factory() as db:
        for age in (8, 7, 6):
            db.add(
                ModelCallLog(
                    customer_name=f"Khách {age}",
                    trigger=MentionFollowupTrigger.MENTION,
                    provider="fptcloud",
                    model="DeepSeek-V4-Flash",
                    request_payload={"conversation": [{"text": f"tin {age}"}]},
                    status=ModelCallStatus.SUCCEEDED,
                    outcome="SKIPPED",
                    created_at=now - timedelta(days=age),
                )
            )
        await db.commit()

        assert await delete_expired_model_call_logs(db, now=now) == 1
        remaining = list(
            await db.scalars(select(ModelCallLog).order_by(ModelCallLog.created_at))
        )
        assert [row.customer_name for row in remaining] == ["Khách 7", "Khách 6"]

    await engine.dispose()


async def test_finished_debt_reminder_runs_keep_exactly_45_days() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 24, 2, tzinfo=UTC)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="debt-run-retention",
            name="Khách kiểm thử lịch sử công nợ",
            member_count=2,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        customer = Customer(zalo_group_id=group.id)
        db.add(customer)
        await db.flush()
        automation = DebtReminderAutomation(
            customer_id=customer.id,
            message_parts=[{"type": "text", "text": "Nhắc nợ"}],
        )
        db.add(automation)
        await db.flush()
        for age in (46, 45, 10):
            processed_at = now - timedelta(days=age)
            db.add(
                DebtReminderRun(
                    automation_id=automation.id,
                    scheduled_for=processed_at,
                    retry_at=processed_at,
                    status=DebtReminderStatus.SENT,
                    processed_at=processed_at,
                )
            )
        db.add(
            DebtReminderRun(
                automation_id=automation.id,
                scheduled_for=now - timedelta(days=90),
                retry_at=now - timedelta(days=90),
                status=DebtReminderStatus.PENDING,
            )
        )
        await db.commit()

        await delete_expired_delivery_logs(db, now=now)
        remaining = list(await db.scalars(select(DebtReminderRun)))

        assert len(remaining) == 3
        assert any(run.status == DebtReminderStatus.PENDING for run in remaining)
        assert sorted(
            (now.replace(tzinfo=None) - run.processed_at).days
            for run in remaining
            if run.processed_at is not None
        ) == [10, 45]

    await engine.dispose()


async def test_only_finished_mention_followups_are_purged() -> None:
    """Live loops must survive retention; a cancelled one from months ago must not."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 17, 2, tzinfo=UTC)
    long_ago = now - timedelta(days=90)

    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="followup-retention",
            name="Nhóm dọn followup",
            member_count=2,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=60,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add_all(
            [
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="old-cancelled",
                    target_user_ids=["u1"],
                    target_display_names=["Người 1"],
                    due_at=long_ago,
                    processed_at=long_ago,
                    status=MentionFollowupStatus.CANCELLED,
                ),
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="old-failed",
                    target_user_ids=["u2"],
                    target_display_names=["Người 2"],
                    due_at=long_ago,
                    processed_at=long_ago,
                    status=MentionFollowupStatus.FAILED,
                ),
                # Still looping: no processed_at, must never be deleted.
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="still-waiting",
                    target_user_ids=["u3"],
                    target_display_names=["Người 3"],
                    due_at=long_ago,
                    status=MentionFollowupStatus.PENDING,
                ),
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="recently-cancelled",
                    target_user_ids=["u4"],
                    target_display_names=["Người 4"],
                    due_at=now,
                    processed_at=now - timedelta(days=2),
                    status=MentionFollowupStatus.CANCELLED,
                ),
            ]
        )
        await db.commit()

        await delete_expired_delivery_logs(db, now=now)

        remaining = sorted(
            row for row in (await db.scalars(select(MentionFollowup.source_message_id))).all()
        )
        assert remaining == ["recently-cancelled", "still-waiting"]

    await engine.dispose()
