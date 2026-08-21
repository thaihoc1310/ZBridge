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
from app.models.entities import MentionFollowupStatus
from app.schemas.api import IncomingGroupMessage, IncomingMention
from app.services import mention_classifier
from app.services.mention_automation_service import schedule_from_incoming_event
from app.services.mention_classifier import (
    MentionClassification,
    MentionDecision,
    MentionReasonCode,
    _ModelResult,
)


async def _database():
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
            zalo_group_id="classifier-group",
            name="Nhóm classifier",
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
            delay_minutes=120,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="target-user",
                display_name="Abcd",
            )
        )
        await db.commit()
    return engine, sessions


def _mention_event(message_id: str, content: str) -> IncomingGroupMessage:
    mention_position = content.index("@Abcd")
    return IncomingGroupMessage(
        group_id="classifier-group",
        message_id=message_id,
        sender_id="sender-user",
        sender_display_name="Minh",
        sent_at=datetime.now(UTC),
        content=content,
        mentions=[
            IncomingMention(
                user_id="target-user",
                position=mention_position,
                length=5,
                text="@Abcd",
            )
        ],
    )


async def test_rules_skip_ack_but_keep_bare_mention_with_context() -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        skipped = await schedule_from_incoming_event(
            db, _mention_event("ack", "cảm ơn @Abcd")
        )
        skipped_followup = await db.get(MentionFollowup, skipped.followup_id)
        assert skipped.scheduled is False
        assert skipped_followup.status == MentionFollowupStatus.SKIPPED
        assert skipped_followup.classification_model == "rules:v1"

        await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="classifier-group",
                message_id="question",
                sender_id="sender-user",
                sender_display_name="Minh",
                content="Anh kiểm tra số liệu giúp em được không?",
            ),
        )
        bare = await schedule_from_incoming_event(
            db, _mention_event("bare", "@Abcd")
        )
        bare_followup = await db.get(MentionFollowup, bare.followup_id)
        context = list(
            (
                await db.scalars(
                    select(MentionContextMessage).order_by(MentionContextMessage.sent_at)
                )
            ).all()
        )
        assert bare.scheduled is True
        assert bare_followup.status == MentionFollowupStatus.PENDING
        assert bare_followup.classification_result[0]["reason_code"] == "BARE_MENTION"
        assert [message.message_id for message in context] == ["ack", "question", "bare"]
    await engine.dispose()


async def test_ai_skips_only_high_confidence_ack(monkeypatch) -> None:
    engine, sessions = await _database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    captured_payloads: list[dict[str, object]] = []

    async def classify(payload, *, model=None):
        captured_payloads.append(payload)
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification.ACKNOWLEDGEMENT,
                    confidence=0.99,
                    reason_code=MentionReasonCode.ACK_ONLY,
                )
            ],
            input_tokens=100,
            output_tokens=20,
            latency_ms=42,
        )

    monkeypatch.setattr(mention_classifier, "classify_payload", classify)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _mention_event("ai-ack", "mình báo để bạn biết nhé @Abcd")
        )
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup.status == MentionFollowupStatus.CLASSIFYING

    claimed = await mention_classifier.claim_pending_classifications()
    assert [followup_id for followup_id, _ in claimed] == [response.followup_id]
    await mention_classifier.process_classification(*claimed[0])

    async with sessions() as db:
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup.status == MentionFollowupStatus.SKIPPED
        assert followup.target_user_ids == []
        assert followup.classification_input_tokens == 100
        assert followup.classification_result[0]["skipped"] is True
    assert captured_payloads[0]["targets"] == [{"target_id": "T1"}]
    assert "Abcd" not in str(captured_payloads[0])
    assert captured_payloads[0]["conversation"][0]["text"].endswith("<MENTION:T1>")
    await engine.dispose()


async def test_ai_error_safely_schedules_followup(monkeypatch) -> None:
    engine, sessions = await _database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)

    async def fail(_payload, *, model=None):
        raise TimeoutError("test timeout")

    monkeypatch.setattr(mention_classifier, "classify_payload", fail)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _mention_event("ai-error", "@Abcd xem thông tin này nhé")
        )
    claimed = await mention_classifier.claim_pending_classifications()
    await mention_classifier.process_classification(*claimed[0])

    async with sessions() as db:
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup.status == MentionFollowupStatus.PENDING
        assert followup.classification_error.startswith("TimeoutError")
    await engine.dispose()


async def test_overdue_classification_is_released_and_alerts(monkeypatch) -> None:
    """A stopped AI worker must not silently stop everyone from being tagged."""
    engine, sessions = await _database()
    async with sessions() as db:
        automation = await db.scalar(select(MentionAutomation))
        assert automation is not None
        stale = datetime.now(UTC) - timedelta(minutes=40)
        fresh = datetime.now(UTC)
        db.add_all(
            [
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="stuck-long-ago",
                    target_user_ids=["target-user"],
                    target_display_names=["Abcd"],
                    due_at=fresh,
                    status=MentionFollowupStatus.CLASSIFYING,
                    created_at=stale,
                ),
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="just-arrived",
                    target_user_ids=["target-user"],
                    target_display_names=["Abcd"],
                    due_at=fresh,
                    status=MentionFollowupStatus.CLASSIFYING,
                    created_at=fresh,
                ),
            ]
        )
        await db.commit()

    alerts: list[tuple[str, str]] = []

    async def capture(code, _message, **kwargs):
        alerts.append((code, kwargs.get("severity")))

    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    monkeypatch.setattr(mention_classifier, "report_async", capture)

    released = await mention_classifier.release_overdue_classifications()

    assert released == 1
    assert [code for code, _ in alerts] == ["MENTION_CLASSIFICATION_STUCK"]
    async with sessions() as db:
        rows = {
            row.source_message_id: row
            for row in (await db.scalars(select(MentionFollowup))).all()
        }
        # Released so the sender picks it up: better a tag than silence.
        assert rows["stuck-long-ago"].status == MentionFollowupStatus.PENDING
        assert rows["stuck-long-ago"].classification_error == "CLASSIFICATION_DEADLINE_EXCEEDED"
        assert rows["stuck-long-ago"].attempt_count == 0
        # Still inside the deadline, so the AI worker keeps its chance.
        assert rows["just-arrived"].status == MentionFollowupStatus.CLASSIFYING

    # Nothing left to release, so no repeat alert.
    alerts.clear()
    assert await mention_classifier.release_overdue_classifications() == 0
    assert alerts == []

    await engine.dispose()


async def test_classification_failure_alerts_and_still_tags(monkeypatch) -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        scheduled = await schedule_from_incoming_event(
            db, _mention_event("needs-ai", "@Abcd xem giúp mình file này với")
        )
    followup_id = scheduled.followup_id
    assert followup_id is not None

    async def explode(*_args, **_kwargs):
        raise TimeoutError("openai took too long")

    alerts: list[str] = []

    async def capture(code, _message, **_kwargs):
        alerts.append(code)

    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    monkeypatch.setattr(mention_classifier, "classify_payload", explode)
    monkeypatch.setattr(mention_classifier, "report_async", capture)

    claimed = await mention_classifier.claim_pending_classifications()
    assert [row[0] for row in claimed] == [followup_id]
    await mention_classifier.process_classification(*claimed[0])

    assert alerts == ["MENTION_CLASSIFICATION_FAILED"]
    async with sessions() as db:
        followup = await db.get(MentionFollowup, followup_id)
        assert followup is not None
        assert followup.status == MentionFollowupStatus.PENDING
        assert "TimeoutError" in (followup.classification_error or "")

    await engine.dispose()


async def test_stale_duplicate_task_does_not_spend_another_openai_call(monkeypatch) -> None:
    """A leftover task from an earlier claim must not re-classify the same follow-up."""
    engine, sessions = await _database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    calls: list[dict] = []

    async def classify(payload, *, model=None):
        calls.append(payload)
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification.FYI,
                    confidence=0.99,
                    reason_code=MentionReasonCode.INFO_ONLY,
                )
            ],
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(mention_classifier, "classify_payload", classify)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _mention_event("dup", "@Abcd gui lai file giup minh nhe")
        )
    followup_id = response.followup_id
    assert followup_id is not None

    claimed = await mention_classifier.claim_pending_classifications()
    stale_stamp = claimed[0][1]

    # The dispatcher re-claims after the stale window, so the stamp moves on.
    async with sessions() as db:
        followup = await db.get(MentionFollowup, followup_id)
        followup.claimed_at = stale_stamp + timedelta(minutes=11)
        await db.commit()

    await mention_classifier.process_classification(followup_id, stale_stamp)
    assert calls == [], "task cu khong duoc goi OpenAI nua"

    async with sessions() as db:
        followup = await db.get(MentionFollowup, followup_id)
        # Untouched, so the current claim owner still gets to do the work.
        assert followup.status == MentionFollowupStatus.CLASSIFYING

    await engine.dispose()


async def test_low_confidence_ack_is_still_tagged(monkeypatch) -> None:
    """The skip threshold is the safety valve: below it, we tag rather than guess."""
    engine, sessions = await _database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    monkeypatch.setattr(mention_classifier.settings, "llm_skip_confidence", 0.70)

    async def classify(_payload, *, model=None):
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification.ACKNOWLEDGEMENT,
                    confidence=0.65,
                    reason_code=MentionReasonCode.ACK_ONLY,
                )
            ],
            input_tokens=10,
            output_tokens=5,
            latency_ms=7,
        )

    monkeypatch.setattr(mention_classifier, "classify_payload", classify)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _mention_event("low-conf", "chuyen nay xong roi @Abcd nhe")
        )
    claimed = await mention_classifier.claim_pending_classifications()
    await mention_classifier.process_classification(*claimed[0])

    async with sessions() as db:
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup is not None
        assert followup.status == MentionFollowupStatus.PENDING
        assert followup.target_user_ids == ["target-user"]
        assert followup.classification_result[0]["skipped"] is False
        assert followup.classification_result[0]["confidence"] == 0.65

    await engine.dispose()
