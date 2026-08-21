"""What an edit does to reminders that are already running.

Every one of these used to end the same way — any change at all cancelled every
follow-up in the group — which quietly lost real nudges when somebody tuned the
delay or removed an unrelated name.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    Customer,
    MentionAutomation,
    MentionFollowup,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import MentionFollowupStatus, MentionFollowupTrigger
from app.schemas.api import (
    MentionAutomationUpdate,
    MentionTargetInput,
    MentionTimeWindow,
)
from app.services import mention_scheduler
from app.services.mention_automation_service import save_mention_automation

ENG = MentionTargetInput(user_id="u-eng", display_name="Eng")
SA = MentionTargetInput(user_id="u-sa", display_name="Sa")
BOB = MentionTargetInput(user_id="u-bob", display_name="Bob")
ALL_DAY = [MentionTimeWindow(start="00:00", end="23:59")]

BASE = dict(
    mention_tag_enabled=True,
    price_inquiry_enabled=False,
    delay_minutes=120,
    active_windows=ALL_DAY,
    targets=[ENG, SA],
    price_targets=[],
)


async def _automation_with_a_running_reminder(due_at: datetime | None = None):
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
            zalo_group_id="g-1",
            name="Khách hàng A",
            member_count=5,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(zalo_group_id=group.id))
        await db.commit()
        await save_mention_automation(db, group.id, MentionAutomationUpdate(**BASE))
        automation = await db.scalar(select(MentionAutomation))
        await db.execute(delete(MentionFollowup))
        db.add(
            MentionFollowup(
                automation_id=automation.id,
                source_message_id="m-eng",
                trigger=MentionFollowupTrigger.MENTION,
                target_user_ids=["u-eng"],
                target_display_names=["Eng"],
                due_at=due_at or datetime.now(UTC),
                status=MentionFollowupStatus.PENDING,
            )
        )
        await db.commit()
        return engine, sessions, group.id


@pytest.mark.parametrize(
    ("label", "override", "survives"),
    [
        ("không đổi gì", {}, True),
        ("xoá một người khác", {"targets": [ENG]}, True),
        ("thêm người vào nhắc việc", {"targets": [ENG, SA, BOB]}, True),
        (
            "thêm chính người đó vào báo giá",
            {"price_inquiry_enabled": True, "price_targets": [ENG]},
            True,
        ),
        ("đổi thời gian chờ", {"delay_minutes": 60}, True),
        (
            "đổi khung giờ",
            {"active_windows": [MentionTimeWindow(start="08:00", end="17:00")]},
            True,
        ),
        ("xoá chính người đó", {"targets": [SA]}, False),
        ("tắt nhắc việc", {"mention_tag_enabled": False, "targets": []}, False),
    ],
)
async def test_only_dropping_the_person_ends_their_reminder(
    label: str, override: dict, survives: bool
) -> None:
    engine, sessions, group_id = await _automation_with_a_running_reminder()
    async with sessions() as db:
        await save_mention_automation(
            db, group_id, MentionAutomationUpdate(**{**BASE, **override})
        )
        followup = await db.scalar(
            select(MentionFollowup).where(MentionFollowup.source_message_id == "m-eng")
        )
        expected = (
            MentionFollowupStatus.PENDING if survives else MentionFollowupStatus.CANCELLED
        )
        assert followup.status == expected, label
    await engine.dispose()


async def test_a_follow_up_left_outside_the_new_hours_waits_instead_of_dying(
    monkeypatch,
) -> None:
    """Editing the active hours must not send early, nor throw the reminder away."""
    overdue = datetime.now(UTC) - timedelta(minutes=1)
    engine, sessions, group_id = await _automation_with_a_running_reminder(overdue)
    monkeypatch.setattr(mention_scheduler, "SessionLocal", sessions)

    # Move the window to a slot that cannot contain "now" whatever the clock says.
    async with sessions() as db:
        await save_mention_automation(
            db,
            group_id,
            MentionAutomationUpdate(
                **{
                    **BASE,
                    "targets": [ENG],
                    "active_windows": [MentionTimeWindow(start="03:00", end="03:30")],
                }
            ),
        )

    claimed = await mention_scheduler.claim_due_followups()
    assert len(claimed) == 1
    # No job comes back: the send is deferred rather than made out of hours.
    assert await mention_scheduler._prepare_job(claimed[0]) is None

    async with sessions() as db:
        followup = await db.scalar(select(MentionFollowup))
        assert followup.status == MentionFollowupStatus.PENDING
        assert followup.due_at.replace(tzinfo=UTC) > overdue
        assert followup.attempt_count == 0
    await engine.dispose()
