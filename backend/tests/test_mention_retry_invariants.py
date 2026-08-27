"""Regression cover for the retry/idempotency/replay invariants.

Each test here corresponds to a defect the previous suite let through: the send
retry budget could not be exhausted, the idempotency key changed on every retry,
the repoint cap never applied, and a replayed old message invalidated newer
loops.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    Customer,
    MentionAutomation,
    MentionContextMessage,
    MentionFollowup,
    MentionTarget,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import MentionFollowupStatus, MentionFollowupTrigger
from app.schemas.api import IncomingGroupMessage, IncomingMention
from app.services import mention_classifier, mention_scheduler
from app.services.mention_automation_service import schedule_from_incoming_event


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory, *, group_id: str = "group-retry") -> tuple:
    async with session_factory() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id=group_id,
            name="Nhóm thử lại",
            member_count=5,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            mention_tag_enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="target-user",
                display_name="Người cần trả lời",
            )
        )
        await db.commit()
        return group.id, automation.id


async def _healthy_status() -> dict[str, object]:
    return {"status": "CONNECTED", "events_healthy": True, "events_caught_up": True}


async def test_repeated_gateway_failures_eventually_fail_the_followup(monkeypatch) -> None:
    """The send budget must survive the re-classification each failure forces.

    Both counters used to be `attempt_count`, which the classifier resets, so a
    follow-up bounced between PENDING and PROCESSING forever and never reached
    MAX_ATTEMPTS — a broken gateway produced an endless tag loop and no alert.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory)

    async def failing_send(*_args, **_kwargs) -> dict[str, str]:
        raise mention_scheduler.GatewayError("ZALO_API_ERROR", "Zalo từ chối.", 502)

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", _healthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", failing_send)

    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-fail",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC) - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    for _ in range(mention_scheduler.MAX_ATTEMPTS):
        claimed = await mention_scheduler.claim_due_followups()
        assert claimed == [followup_id]
        await mention_scheduler.process_followup(followup_id)
        async with session_factory() as db:
            current = await db.get(MentionFollowup, followup_id)
            assert current is not None
            # Stand in for the mandatory re-classification: it clears
            # attempt_count and re-approves the same due_at.
            current.attempt_count = 0
            current.evaluated_due_at = current.due_at
            current.due_at = datetime.now(UTC) - timedelta(minutes=1)
            current.evaluated_due_at = current.due_at
            await db.commit()

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.send_attempt_count == mention_scheduler.MAX_ATTEMPTS
        assert current.status == MentionFollowupStatus.FAILED
        assert current.processed_at is not None

    await engine.dispose()


async def test_a_cancelled_claim_does_not_spend_the_retry_budget(monkeypatch) -> None:
    """Only a refused gateway call may cost an attempt.

    The budget used to be charged when the scheduler claimed the row. Several
    paths drop that claim before the gateway is ever called — here, a new message
    arriving — so a busy group burned the budget without a single failed send and
    the first real failure could mark the loop FAILED outright.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-leak")

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="source-leak",
                message_aliases=["source-leak"],
                sender_id="customer-user",
                content="@Người cần trả lời chốt giúp em",
                mentions=[{"user_id": "target-user", "text": "@Người cần trả lời"}],
                sent_at=now - timedelta(minutes=10),
            )
        )
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-leak",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    # Two rounds of "claimed, then new context arrives before the send".
    for index in range(2):
        claimed = await _claim_with(session_factory, monkeypatch)
        assert claimed == [followup_id]
        async with session_factory() as db:
            await schedule_from_incoming_event(
                db,
                IncomingGroupMessage(
                    group_id="group-leak",
                    message_id=f"interrupting-{index}",
                    sender_id="colleague-user",
                    sender_display_name="Đồng nghiệp",
                    content="để em xem đã",
                    sent_at=datetime.now(UTC),
                    mentions=[],
                ),
            )
        async with session_factory() as db:
            current = await db.get(MentionFollowup, followup_id)
            assert current is not None
            assert current.status == MentionFollowupStatus.PENDING
            assert current.send_attempt_count == 0, (
                "claim bi huy truoc khi gui van tru vao ngan sach thu lai"
            )
            # The invalidation cleared evaluated_due_at, so a re-classification
            # has to approve the send again. Stand in for it.
            current.evaluated_due_at = current.due_at
            await db.commit()

    # Now one genuine gateway failure: it must retry, not fail outright.
    async def failing_send(*_args, **_kwargs) -> dict[str, str]:
        raise mention_scheduler.GatewayError("ZALO_API_ERROR", "Zalo từ chối.", 502)

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", _healthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", failing_send)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        current.due_at = datetime.now(UTC) - timedelta(minutes=1)
        current.evaluated_due_at = current.due_at
        await db.commit()

    await mention_scheduler.claim_due_followups()
    await mention_scheduler.process_followup(followup_id)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.send_attempt_count == 1
        assert current.status == MentionFollowupStatus.PENDING
        assert current.processed_at is None

    await engine.dispose()


async def _claim_with(session_factory, monkeypatch) -> list:
    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    return await mention_scheduler.claim_due_followups()


async def test_retrying_a_send_reuses_one_idempotency_key(monkeypatch) -> None:
    """A timeout after Zalo accepted the tag must not send it twice.

    The key used to embed due_at, which every retry path rewrites, so the
    gateway's receipt store saw each attempt as a brand-new send.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-idem")

    keys: list[str] = []

    async def timing_out_send(*_args, idempotency_key: str = "", **_kwargs) -> dict[str, str]:
        keys.append(idempotency_key)
        raise mention_scheduler.GatewayError(
            "ZALO_GATEWAY_UNAVAILABLE", "Hết thời gian chờ.", 503
        )

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", _healthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", timing_out_send)

    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-idem",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC) - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    for _ in range(3):
        await mention_scheduler.claim_due_followups()
        await mention_scheduler.process_followup(followup_id)
        async with session_factory() as db:
            current = await db.get(MentionFollowup, followup_id)
            assert current is not None
            current.attempt_count = 0
            current.status = MentionFollowupStatus.PENDING
            current.claimed_at = None
            current.due_at = datetime.now(UTC) - timedelta(minutes=1)
            current.evaluated_due_at = current.due_at
            await db.commit()

    assert len(keys) == 3
    assert len(set(keys)) == 1, f"khoa idempotency doi giua cac lan thu lai: {keys}"
    assert keys[0] == f"mention:{followup_id}:0"

    await engine.dispose()


async def test_a_confirmed_send_starts_a_new_idempotency_key(monkeypatch) -> None:
    """The next cycle's tag is a genuinely new send and must get its own key."""
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-idem-2")

    keys: list[str] = []

    async def ok_send(*_args, idempotency_key: str = "", **_kwargs) -> dict[str, str]:
        keys.append(idempotency_key)
        return {"message_id": "sent"}

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", _healthy_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", ok_send)

    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-cycle",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC) - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    for _ in range(2):
        await mention_scheduler.claim_due_followups()
        await mention_scheduler.process_followup(followup_id)
        async with session_factory() as db:
            current = await db.get(MentionFollowup, followup_id)
            assert current is not None
            current.due_at = datetime.now(UTC) - timedelta(minutes=1)
            current.evaluated_due_at = current.due_at
            await db.commit()

    assert keys == [f"mention:{followup_id}:0", f"mention:{followup_id}:1"]
    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.send_count == 2
        assert current.send_attempt_count == 0

    await engine.dispose()


async def test_a_backlogged_event_channel_only_delays_briefly(monkeypatch) -> None:
    """Events in flight are the channel working, not a lost channel.

    `pending > 0` used to make events_healthy false, so one event mid-POST cost
    every due follow-up five minutes and raised a misleading warning.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-backlog")

    async def behind_status() -> dict[str, object]:
        return {
            "status": "CONNECTED",
            "events_healthy": True,
            "events_caught_up": False,
            "event_backlog": 2,
            "event_backlog_age_ms": 400,
        }

    alerts: list[str] = []

    async def record_alert(code: str, *_args, **_kwargs) -> None:
        alerts.append(code)

    sent: list[object] = []

    async def ok_send(*_args, **_kwargs) -> dict[str, str]:
        sent.append(_args)
        return {"message_id": "sent"}

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", behind_status)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "send_mention", ok_send)
    monkeypatch.setattr(mention_scheduler, "report_async", record_alert)

    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-backlog",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC) - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    before = datetime.now(UTC)
    await mention_scheduler.claim_due_followups()
    await mention_scheduler.process_followup(followup_id)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.status == MentionFollowupStatus.PENDING
        due_at = current.due_at.replace(tzinfo=UTC)
        # Seconds, not the five-minute outage delay.
        assert due_at < before + mention_scheduler.EVENTS_DOWN_DELAY
        assert due_at >= before
        # Nothing was sent, so the attempt is returned to the budget.
        assert current.send_attempt_count == 0
    assert sent == []
    assert alerts == [], "backlog thoang qua khong duoc bao dong"

    await engine.dispose()


async def test_a_long_lived_backlog_escalates_to_the_outage_path(monkeypatch) -> None:
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-stalled")

    async def stalled_status() -> dict[str, object]:
        return {
            "status": "CONNECTED",
            "events_healthy": True,
            "events_caught_up": False,
            "event_backlog": 9,
            "event_backlog_age_ms": 10 * 60 * 1000,
        }

    alerts: list[str] = []

    async def record_alert(code: str, *_args, **_kwargs) -> None:
        alerts.append(code)

    monkeypatch.setattr(mention_scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_scheduler.zalo_gateway, "get_status", stalled_status)
    monkeypatch.setattr(mention_scheduler, "report_async", record_alert)

    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-stalled",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=datetime.now(UTC) - timedelta(minutes=1),
            status=MentionFollowupStatus.PENDING,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    before = datetime.now(UTC)
    await mention_scheduler.claim_due_followups()
    await mention_scheduler.process_followup(followup_id)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.due_at.replace(tzinfo=UTC) >= before + timedelta(minutes=4)
    assert alerts == ["MENTION_FOLLOWUP_POSTPONED"]

    await engine.dispose()


async def test_a_replayed_old_message_leaves_a_newer_loop_alone() -> None:
    """The gateway outbox retries for hours, so an event can arrive long after it happened.

    Such a message is history, not new context for a loop that opened after it.
    The reaction path already guarded this; the message path did not, so a replay
    knocked a live PROCESSING claim back to PENDING and bought a model call.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-replay")

    now = datetime.now(UTC)
    old_sent_at = now - timedelta(hours=2)

    async with session_factory() as db:
        # The loop's own source arrived after the message about to be replayed.
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="source-new",
                message_aliases=["source-new"],
                sender_id="customer-user",
                content="@Người cần trả lời chốt giúp em đơn này",
                mentions=[{"user_id": "target-user", "text": "@Người cần trả lời"}],
                sent_at=now - timedelta(minutes=5),
            )
        )
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-new",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=now,
            attempt_count=1,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    async with session_factory() as db:
        replayed = IncomingGroupMessage(
            group_id="group-replay",
            message_id="message-replayed",
            sender_id="someone-else",
            sender_display_name="Đồng nghiệp",
            content="chuyện cũ từ hai tiếng trước",
            sent_at=old_sent_at,
            mentions=[],
        )
        await schedule_from_incoming_event(db, replayed)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.status == MentionFollowupStatus.PROCESSING, "mat claim dang bay"
        assert current.claimed_at is not None
        assert current.evaluated_due_at is not None, "bi buoc phan loai lai vo co"
        # The replay is still recorded as conversation history.
        stored = await db.scalar(
            select(MentionContextMessage).where(
                MentionContextMessage.message_id == "message-replayed"
            )
        )
        assert stored is not None

    await engine.dispose()


async def test_a_current_message_still_invalidates_the_loop() -> None:
    """The guard must not stop a genuinely new message from forcing a re-read."""
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-fresh")

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="source-old",
                message_aliases=["source-old"],
                sender_id="customer-user",
                content="@Người cần trả lời báo giá giúp em",
                mentions=[{"user_id": "target-user", "text": "@Người cần trả lời"}],
                sent_at=now - timedelta(hours=1),
            )
        )
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="source-old",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=now,
            attempt_count=1,
        )
        followup.evaluated_due_at = followup.due_at
        db.add(followup)
        await db.commit()
        followup_id = followup.id

    async with session_factory() as db:
        await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="group-fresh",
                message_id="message-now",
                sender_id="colleague-user",
                sender_display_name="Đồng nghiệp",
                content="em gửi khách báo giá rồi nhé",
                sent_at=now,
                mentions=[],
            ),
        )

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        assert current.status == MentionFollowupStatus.PENDING
        assert current.evaluated_due_at is None, "phai doi mot phan dinh AI moi"

    await engine.dispose()


async def test_a_duplicate_source_keeps_the_acknowledgements_already_made() -> None:
    """A losing race on uq_mention_followup_source must not undo the whole event.

    The insert used to roll the transaction back wholesale, discarding the
    acknowledgements and the context row committed alongside it — the very work
    that stops a loop from running forever.
    """
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-dup")

    now = datetime.now(UTC)
    async with session_factory() as db:
        winner = MentionFollowup(
            automation_id=automation_id,
            source_message_id="contested",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.PENDING,
        )
        db.add(winner)
        other = MentionFollowup(
            automation_id=automation_id,
            source_message_id="other-loop",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.PENDING,
        )
        db.add(other)
        await db.commit()
        winner_id = winner.id
        other_id = other.id

    async with session_factory() as db:
        automation = await db.get(MentionAutomation, automation_id)
        assert automation is not None
        # Stand in for the work `schedule_from_incoming_event` accumulates before
        # it reaches the insert: a context row plus an acknowledgement.
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="contested",
                message_aliases=["contested"],
                sender_id="target-user",
                content="em trả lời rồi nhé",
                mentions=[],
                sent_at=now,
            )
        )
        loser = await db.get(MentionFollowup, other_id)
        assert loser is not None
        loser.status = MentionFollowupStatus.CANCELLED
        loser.processed_at = now

        from app.services.mention_automation_service import _create_followup

        result = await _create_followup(
            db,
            automation,
            IncomingGroupMessage(
                group_id="group-dup",
                message_id="contested",
                sender_id="target-user",
                sender_display_name="Người cần trả lời",
                content="em trả lời rồi nhé",
                sent_at=now,
                mentions=[
                    IncomingMention(user_id="target-user", position=0, length=2, text="@x")
                ],
            ),
            [],
            now,
            trigger=MentionFollowupTrigger.MENTION,
            initial_status=MentionFollowupStatus.PENDING,
            acknowledged_followups=1,
        )

    assert result.scheduled is False
    assert result.followup_id == winner_id
    assert result.acknowledged_followups == 1

    async with session_factory() as db:
        # The acknowledgement survived the conflict.
        settled = await db.get(MentionFollowup, other_id)
        assert settled is not None
        assert settled.status == MentionFollowupStatus.CANCELLED
        # So did the conversation history.
        stored = await db.scalar(
            select(MentionContextMessage).where(
                MentionContextMessage.message_id == "contested"
            )
        )
        assert stored is not None
        # And no second follow-up was created for the contested message.
        rows = list(
            (
                await db.scalars(
                    select(MentionFollowup).where(
                        MentionFollowup.source_message_id == "contested"
                    )
                )
            ).all()
        )
        assert len(rows) == 1

    await engine.dispose()


async def test_repointing_stops_at_the_configured_cap(monkeypatch) -> None:
    """MAX_REPOINTS read attempt_count, which this very stage resets, so it was 0 forever."""
    engine, session_factory = await _database()
    _group_id, automation_id = await _seed(session_factory, group_id="group-repoint")

    now = datetime.now(UTC)
    async with session_factory() as db:
        followup = MentionFollowup(
            automation_id=automation_id,
            source_message_id="m0",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.CLASSIFYING,
            claimed_at=now,
        )
        followup.repoint_count = mention_classifier.MAX_REPOINTS
        db.add(followup)
        await db.flush()
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="m0",
                message_aliases=["m0"],
                sender_id="customer-user",
                content="@Người cần trả lời ok",
                mentions=[{"user_id": "target-user", "text": "@Người cần trả lời"}],
                sent_at=now,
            )
        )
        db.add(
            MentionContextMessage(
                automation_id=automation_id,
                message_id="m1",
                message_aliases=["m1"],
                sender_id="customer-user",
                content="@Người cần trả lời vâng",
                mentions=[{"user_id": "target-user", "text": "@Người cần trả lời"}],
                sent_at=now + timedelta(seconds=5),
            )
        )
        await db.commit()
        followup_id = followup.id
        claimed_at = followup.claimed_at

    calls = 0

    async def skipping_classify(_payload, *, model=None, prompt=None):
        nonlocal calls
        calls += 1
        return mention_classifier._ModelResult(
            decisions=[
                mention_classifier.MentionDecision(
                    target_id="T1",
                    classification=mention_classifier.MentionClassification.ACKNOWLEDGEMENT,
                    confidence=0.99,
                    reason_code=mention_classifier.MentionReasonCode.ACK_ONLY,
                )
            ],
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(mention_classifier, "SessionLocal", session_factory)
    monkeypatch.setattr(mention_classifier, "classify_payload", skipping_classify)
    await mention_classifier.process_classification(followup_id, claimed_at)

    async with session_factory() as db:
        current = await db.get(MentionFollowup, followup_id)
        assert current is not None
        # A newer qualifying message exists, but the budget is spent, so the
        # verdict is settled instead of buying another model call.
        assert current.status == MentionFollowupStatus.SKIPPED
        assert current.source_message_id == "m0"
    assert calls == 1

    await engine.dispose()
