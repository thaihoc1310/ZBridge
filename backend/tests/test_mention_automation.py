from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    BotDeliveryLog,
    Customer,
    MentionAutomation,
    MentionContextMessage,
    MentionFollowup,
    MentionTarget,
    ModelCallLog,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    DeliveryStatus,
    DeliveryType,
    MentionFollowupStatus,
    MentionFollowupTrigger,
    ModelCallStatus,
)
from app.schemas.api import (
    IncomingGroupMessage,
    IncomingGroupReaction,
    IncomingMention,
    MentionAutomationUpdate,
    MentionTargetInput,
    MentionTimeWindow,
)
from app.services import mention_scheduler
from app.services.mention_automation_service import (
    acknowledge_from_reaction,
    save_mention_automation,
    schedule_from_incoming_event,
)


async def test_incoming_mention_creates_one_durable_followup() -> None:
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
            zalo_group_id="group-100",
            name="Nhóm kế toán",
            member_count=100,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=120,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="target-user",
                display_name="Nguyễn Minh Anh",
            )
        )
        await db.commit()

        event = IncomingGroupMessage(
            group_id="group-100",
            message_id="message-1",
            sender_id="sender-user",
            content="@Nguyễn Minh Anh",
            mentions=[IncomingMention(user_id="target-user", position=0, length=17)],
        )
        scheduled_at = datetime.now(UTC)
        first = await schedule_from_incoming_event(db, event)
        duplicate = await schedule_from_incoming_event(db, event)

        followups = list((await db.scalars(select(MentionFollowup))).all())
        assert first.scheduled is True
        assert first.matched_targets == 1
        assert duplicate.scheduled is False
        assert duplicate.followup_id == first.followup_id
        assert len(followups) == 1
        assert followups[0].status == MentionFollowupStatus.PENDING
        due_at = followups[0].due_at.replace(tzinfo=UTC)
        assert scheduled_at + timedelta(minutes=119) < due_at
        assert due_at < scheduled_at + timedelta(minutes=121)

        await save_mention_automation(
            db,
            group.id,
            MentionAutomationUpdate(
                enabled=True,
                delay_minutes=120,
                active_windows=[MentionTimeWindow(start="00:00", end="23:59")],
                targets=[
                    MentionTargetInput(
                        user_id="target-user",
                        display_name="Nguyễn Minh Anh",
                    )
                ],
            ),
        )
        await db.refresh(followups[0])
        assert followups[0].status == MentionFollowupStatus.PENDING

        updated = await save_mention_automation(
            db,
            group.id,
            MentionAutomationUpdate(
                enabled=True,
                delay_minutes=180,
                active_windows=[MentionTimeWindow(start="00:00", end="23:59")],
                targets=[
                    MentionTargetInput(
                        user_id="replacement-user",
                        display_name="Trần Hoàng Nam",
                    )
                ],
            ),
        )
        await db.refresh(followups[0])
        assert updated.delay_minutes == 180
        assert [target.user_id for target in updated.targets] == ["replacement-user"]
        assert followups[0].status == MentionFollowupStatus.CANCELLED

    await engine.dispose()


async def test_member_message_stops_only_their_active_reminders() -> None:
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
            zalo_group_id="group-ack",
            name="Nhóm cần phản hồi",
            member_count=3,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add_all(
            [
                MentionTarget(
                    automation_id=automation.id,
                    zalo_user_id="target-a",
                    display_name="Thành viên A",
                ),
                MentionTarget(
                    automation_id=automation.id,
                    zalo_user_id="target-b",
                    display_name="Thành viên B",
                ),
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="source-both",
                    target_user_ids=["target-a", "target-b"],
                    target_display_names=["Thành viên A", "Thành viên B"],
                    due_at=datetime.now(UTC),
                    status=MentionFollowupStatus.PENDING,
                ),
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="source-a",
                    target_user_ids=["target-a"],
                    target_display_names=["Thành viên A"],
                    due_at=datetime.now(UTC),
                    status=MentionFollowupStatus.PROCESSING,
                ),
            ]
        )
        await db.commit()

        response = await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="group-ack",
                message_id="reply-a",
                sender_id="target-a",
                content="Mình đã nhận được rồi",
            ),
        )

        followups = list(
            (
                await db.scalars(
                    select(MentionFollowup).order_by(MentionFollowup.source_message_id)
                )
            ).all()
        )
        assert response.scheduled is False
        assert followups[0].source_message_id == "source-a"
        assert followups[0].status == MentionFollowupStatus.CANCELLED
        assert followups[1].source_message_id == "source-both"
        assert followups[1].status == MentionFollowupStatus.PENDING
        assert followups[1].target_user_ids == ["target-b"]
        assert followups[1].target_display_names == ["Thành viên B"]

    await engine.dispose()


async def test_heart_and_like_stop_only_the_reactors_active_reminders() -> None:
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
            zalo_group_id="group-reaction-ack",
            name="Nhóm xác nhận bằng reaction",
            member_count=4,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        both = MentionFollowup(
            automation_id=automation.id,
            source_message_id="source-both-reaction",
            target_user_ids=["target-a", "target-b"],
            target_display_names=["Thành viên A", "Thành viên B"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=datetime.now(UTC),
        )
        only_a = MentionFollowup(
            automation_id=automation.id,
            source_message_id="source-a-reaction",
            target_user_ids=["target-a"],
            target_display_names=["Thành viên A"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=datetime.now(UTC),
        )
        db.add_all([both, only_a])
        await db.commit()

        heart = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-reaction-ack",
                reactor_id="target-a",
                reaction="heart",
            ),
        )
        await db.refresh(both)
        await db.refresh(only_a)
        assert heart.acknowledged_followups == 2
        assert both.status == MentionFollowupStatus.PENDING
        assert both.claimed_at is None
        assert both.target_user_ids == ["target-b"]
        assert both.target_display_names == ["Thành viên B"]
        assert only_a.status == MentionFollowupStatus.CANCELLED
        assert only_a.claimed_at is None
        assert only_a.processed_at is not None

        duplicate = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-reaction-ack",
                reactor_id="target-a",
                reaction="heart",
            ),
        )
        ignored = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-reaction-ack",
                reactor_id="target-b",
                reaction="haha",
            ),
        )
        outsider = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-reaction-ack",
                reactor_id="not-a-target",
                reaction="like",
            ),
        )
        assert duplicate.acknowledged_followups == 0
        assert ignored.acknowledged_followups == 0
        assert outsider.acknowledged_followups == 0

        like = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-reaction-ack",
                reactor_id="target-b",
                reaction="like",
            ),
        )
        await db.refresh(both)
        assert like.acknowledged_followups == 1
        assert both.status == MentionFollowupStatus.CANCELLED

    await engine.dispose()


async def test_reaction_uses_source_event_time_not_db_insert_time() -> None:
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
            zalo_group_id="group-delayed-reaction",
            name="Nhóm reaction đến trễ",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        now = datetime.now(UTC)
        stale_reaction_time = now - timedelta(minutes=5)
        stale_source_time = now - timedelta(minutes=4)
        quick_source_time = now - timedelta(seconds=2)
        db.add_all(
            [
                MentionContextMessage(
                    automation_id=automation.id,
                    message_id="created-after-reaction",
                    sender_id="sender",
                    content="@A hỏi sau reaction cũ",
                    mentions=[],
                    sent_at=stale_source_time,
                ),
                MentionContextMessage(
                    automation_id=automation.id,
                    message_id="quick-reaction-source",
                    sender_id="sender",
                    content="@B báo giá giúp anh",
                    mentions=[],
                    sent_at=quick_source_time,
                ),
            ]
        )
        newer_followup = MentionFollowup(
            automation_id=automation.id,
            source_message_id="created-after-reaction",
            target_user_ids=["target-a"],
            target_display_names=["Thành viên A"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PENDING,
        )
        quick_followup = MentionFollowup(
            automation_id=automation.id,
            source_message_id="quick-reaction-source",
            target_user_ids=["target-b"],
            target_display_names=["Thành viên B"],
            due_at=now,
            status=MentionFollowupStatus.CLASSIFYING,
            claimed_at=now,
        )
        db.add_all([newer_followup, quick_followup])
        await db.commit()

        stale = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-delayed-reaction",
                reactor_id="target-a",
                reacted_at=stale_reaction_time,
                reaction="like",
            ),
        )
        quick = await acknowledge_from_reaction(
            db,
            IncomingGroupReaction(
                event_type="reaction",
                group_id="group-delayed-reaction",
                reactor_id="target-b",
                # It happened after the source message but before the row's
                # server-side created_at timestamp.
                reacted_at=now - timedelta(seconds=1),
                reaction="heart",
            ),
        )
        await db.refresh(newer_followup)
        await db.refresh(quick_followup)

        assert stale.acknowledged_followups == 0
        assert newer_followup.status == MentionFollowupStatus.PENDING
        assert quick.acknowledged_followups == 1
        assert quick_followup.status == MentionFollowupStatus.CANCELLED
        assert quick_followup.claimed_at is None

    await engine.dispose()


async def test_successful_followup_is_scheduled_again(monkeypatch) -> None:
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
            zalo_group_id="group-repeat",
            name="Nhóm nhắc lặp",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        # Deliberately not reusing the group id: delivery logs must be attached to
        # the customer that owns the group, not to the group itself.
        customer = Customer(zalo_group_id=group.id)
        db.add(customer)
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        followup = MentionFollowup(
            automation_id=automation.id,
            source_message_id="source-repeat",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=datetime.now(UTC),
            attempt_count=1,
        )
        db.add(followup)
        await db.flush()
        model_log = ModelCallLog(
            followup_id=followup.id,
            customer_id=customer.id,
            customer_name=group.name,
            trigger=MentionFollowupTrigger.MENTION,
            provider="fptcloud",
            model="DeepSeek-V4-Flash",
            request_payload={"conversation": []},
            response_payload={"decisions": []},
            status=ModelCallStatus.SUCCEEDED,
            outcome="SCHEDULED",
            scheduled_for_send=True,
        )
        db.add(model_log)
        await db.commit()
        followup_id = followup.id
        model_log_id = model_log.id
        customer_id = customer.id

    sent: list[tuple[str, list[dict[str, str]]]] = []

    async def fake_send_mention(
        group_id: str, targets: list[dict[str, str]], **_kwargs
    ) -> dict[str, str]:
        sent.append((group_id, targets))
        return {"message_id": "sent-message"}

    async def healthy_status() -> dict[str, object]:
        return {"status": "CONNECTED", "events_healthy": True}

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", healthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", fake_send_mention)
    before = datetime.now(UTC)
    await mention_scheduler.process_followup(followup_id)

    async with session_factory() as db:
        repeated = await db.get(MentionFollowup, followup_id)
        delivery_log = await db.scalar(select(BotDeliveryLog))
        stored_model_log = await db.get(ModelCallLog, model_log_id)
        assert repeated is not None
        assert repeated.status == MentionFollowupStatus.PENDING
        assert repeated.attempt_count == 0
        assert repeated.claimed_at is None
        assert repeated.processed_at is None
        assert repeated.sent_message_id == "sent-message"
        assert repeated.due_at.replace(tzinfo=UTC) >= before + timedelta(seconds=59)
        assert delivery_log is not None
        assert delivery_log.status == DeliveryStatus.SENT
        assert delivery_log.type == DeliveryType.MENTION_AUTOMATION
        assert delivery_log.customer_id == customer_id
        assert delivery_log.customer_id != group.id
        assert stored_model_log is not None
        assert stored_model_log.message_sent is True
        assert stored_model_log.zalo_message_id == "sent-message"
        assert stored_model_log.message_sent_at is not None
    assert sent == [
        (
            "group-repeat",
            [{"user_id": "target-user", "display_name": "Người cần trả lời"}],
        )
    ]

    await engine.dispose()


async def test_followup_waits_while_zalo_event_channel_is_down(monkeypatch) -> None:
    """Without the event channel a reply cannot be observed, so tagging must pause."""
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
            zalo_group_id="group-events-down",
            name="Nhóm mất kênh sự kiện",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        followup = MentionFollowup(
            automation_id=automation.id,
            source_message_id="source-events-down",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC),
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=datetime.now(UTC),
            attempt_count=1,
        )
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    sent: list[str] = []

    async def unhealthy_status() -> dict[str, object]:
        return {"status": "CONNECTED", "events_healthy": False}

    async def fake_send_mention(group_id: str, _targets: list[dict[str, str]]) -> dict[str, str]:
        sent.append(group_id)
        return {"message_id": "must-not-be-sent"}

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", unhealthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", fake_send_mention)
    before = datetime.now(UTC)
    await mention_scheduler.process_followup(followup_id)

    async with session_factory() as db:
        postponed = await db.get(MentionFollowup, followup_id)
        assert sent == []
        assert postponed is not None
        assert postponed.status == MentionFollowupStatus.PENDING
        assert postponed.claimed_at is None
        assert postponed.attempt_count == 0
        assert postponed.due_at.replace(tzinfo=UTC) > before
        assert await db.scalar(select(BotDeliveryLog)) is None

    await engine.dispose()
