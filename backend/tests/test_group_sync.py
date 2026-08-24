from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import (
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionFollowup,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import DebtReminderStatus, MentionFollowupStatus
from app.services import group_service


async def test_group_sync_rejects_empty_snapshot_and_requires_three_misses(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def connected():
        return {"status": "CONNECTED", "zalo_user_id": "bot-1"}

    snapshots: list[list[dict[str, object]]] = [[]]

    async def groups():
        return snapshots.pop(0)

    monkeypatch.setattr(group_service.zalo_gateway, "get_status", connected)
    monkeypatch.setattr(group_service.zalo_gateway, "get_groups", groups)

    async with session_factory() as db:
        account = ZaloAccount(zalo_user_id="bot-1")
        db.add(account)
        await db.flush()
        kept = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="kept",
            name="Nhóm còn lại",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        missing = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="missing",
            name="Nhóm tạm thiếu",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add_all([kept, missing])
        await db.flush()
        missing_customer = Customer(
            zalo_group_id=missing.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/missing/edit",
        )
        missing_debt = DebtReminderAutomation(
            customer=missing_customer,
            next_run_at=datetime.now(UTC),
        )
        missing_mention = MentionAutomation(
            zalo_group_id=missing.id,
            enabled=True,
            mention_tag_enabled=True,
        )
        db.add_all([missing_customer, missing_debt, missing_mention])
        await db.flush()
        debt_run = DebtReminderRun(
            automation_id=missing_debt.id,
            scheduled_for=datetime.now(UTC),
            retry_at=datetime.now(UTC),
            status=DebtReminderStatus.PROCESSING,
            claimed_at=datetime.now(UTC),
        )
        mention_followup = MentionFollowup(
            automation_id=missing_mention.id,
            source_message_id="missing-source",
            target_user_ids=["staff-1"],
            target_display_names=["Nhân viên"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PENDING,
        )
        db.add_all([debt_run, mention_followup])
        await db.commit()

        with pytest.raises(AppError) as empty:
            await group_service.sync_groups(db)
        assert empty.value.code == "GROUP_SYNC_INCOMPLETE"
        await db.refresh(missing)
        assert missing.is_available is True
        assert missing.missing_sync_count == 0

        visible = [
            {
                "group_id": "kept",
                "name": "Nhóm còn lại",
                "member_count": 2,
                "avatar_url": None,
            }
        ]
        snapshots.extend([visible, visible, visible])
        for expected_count in (1, 2):
            result = await group_service.sync_groups(db)
            assert result.unavailable == 0
            await db.refresh(missing)
            assert missing.is_available is True
            assert missing.missing_sync_count == expected_count

        result = await group_service.sync_groups(db)
        assert result.unavailable == 1
        await db.refresh(missing)
        assert missing.is_available is False
        await db.refresh(missing_debt)
        await db.refresh(debt_run)
        await db.refresh(mention_followup)
        assert missing_debt.next_run_at is None
        assert debt_run.status == DebtReminderStatus.CANCELLED
        assert mention_followup.status == MentionFollowupStatus.CANCELLED

        snapshots.append(
            [
                *visible,
                {
                    "group_id": "missing",
                    "name": "Nhóm tạm thiếu",
                    "member_count": 2,
                    "avatar_url": None,
                },
            ]
        )
        result = await group_service.sync_groups(db)
        assert result.updated == 1
        await db.refresh(missing)
        await db.refresh(missing_debt)
        assert missing.is_available is True
        assert missing_debt.next_run_at is not None

    await engine.dispose()


async def test_group_sync_creates_customer_and_default_automations_atomically(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def connected():
        return {"status": "CONNECTED", "zalo_user_id": "bot-1"}

    async def groups():
        return [
            {
                "group_id": "new-group",
                "name": "Khách hàng mới",
                "member_count": 4,
                "avatar_url": None,
            }
        ]

    monkeypatch.setattr(group_service.zalo_gateway, "get_status", connected)
    monkeypatch.setattr(group_service.zalo_gateway, "get_groups", groups)

    async with session_factory() as db:
        result = await group_service.sync_groups(db)
        assert result.inserted == 1

        group = await db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == "new-group"))
        customer = await db.scalar(
            select(Customer).where(Customer.zalo_group_id == group.id)
        )
        debt = await db.scalar(
            select(DebtReminderAutomation).where(
                DebtReminderAutomation.customer_id == customer.id
            )
        )
        mention = await db.scalar(
            select(MentionAutomation).where(MentionAutomation.zalo_group_id == group.id)
        )

        assert customer.id == group.id
        assert debt.day_of_month == 25
        assert debt.repeat_interval_days == 3
        assert debt.next_run_at is None
        assert mention.enabled is False
        assert mention.mention_tag_enabled is False
        assert mention.price_inquiry_enabled is False

    await engine.dispose()
