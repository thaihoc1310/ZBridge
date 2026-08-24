import asyncio
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
    ModelCallLog,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import (
    MentionFollowupStatus,
    MentionFollowupTrigger,
    MentionTargetKind,
    ModelCallStatus,
)
from app.schemas.api import IncomingGroupMessage, IncomingGroupReaction, IncomingMention
from app.services import mention_classifier
from app.services.mention_automation_service import (
    acknowledge_from_reaction,
    schedule_from_incoming_event,
)
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

    async def classify(payload, *, model=None, prompt=None):
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

    async def fail(_payload, *, model=None, prompt=None):
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

    async def classify(payload, *, model=None, prompt=None):
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

    async def classify(_payload, *, model=None, prompt=None):
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
        model_log = await db.scalar(select(ModelCallLog))
        assert model_log is not None
        assert model_log.status == ModelCallStatus.SUCCEEDED
        assert model_log.outcome == "SCHEDULED"
        assert model_log.scheduled_for_send is True
        assert model_log.message_sent is False
        assert model_log.request_payload["conversation"][-1]["text"]
        assert model_log.response_payload["decisions"][0]["classification"] == "ACKNOWLEDGEMENT"

    await engine.dispose()


async def _price_database(*, price_enabled: bool = True):
    """The same fixture with a separate sales list, as the UI configures it."""
    engine, sessions = await _database()
    async with sessions() as db:
        automation = await db.scalar(select(MentionAutomation))
        automation.price_inquiry_enabled = price_enabled
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="sales-user",
                display_name="Sales",
                kind=MentionTargetKind.PRICE,
            )
        )
        await db.commit()
    return engine, sessions


async def test_reaction_while_ai_is_in_flight_cannot_resurrect_loop(monkeypatch) -> None:
    for trigger in ("mention", "price"):
        engine, sessions = (
            await _database() if trigger == "mention" else await _price_database()
        )
        monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
        model_started = asyncio.Event()
        model_can_finish = asyncio.Event()

        async def classify(
            _payload,
            *,
            model=None,
            prompt=None,
            _started=model_started,
            _finish=model_can_finish,
        ):
            _started.set()
            await _finish.wait()
            return _ModelResult(
                decisions=[
                    MentionDecision(
                        target_id="T1",
                        classification=MentionClassification.NEED_RESPONSE,
                        confidence=0.99,
                        reason_code=MentionReasonCode.REQUEST,
                    )
                ],
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

        monkeypatch.setattr(mention_classifier, "classify_payload", classify)
        async with sessions() as db:
            response = await schedule_from_incoming_event(
                db,
                _mention_event("race-mention", "gửi giúp anh nhé @Abcd")
                if trigger == "mention"
                else _plain_event("race-price", "báo giá giúp anh nhé"),
            )
        claimed = await mention_classifier.claim_pending_classifications()
        task = asyncio.create_task(mention_classifier.process_classification(*claimed[0]))
        await asyncio.wait_for(model_started.wait(), timeout=1)

        async with sessions() as db:
            acknowledged = await acknowledge_from_reaction(
                db,
                IncomingGroupReaction(
                    event_type="reaction",
                    group_id="classifier-group",
                    reactor_id="target-user" if trigger == "mention" else "sales-user",
                    reacted_at=datetime.now(UTC),
                    reaction="heart",
                ),
            )
        model_can_finish.set()
        await task

        async with sessions() as db:
            followup = await db.get(MentionFollowup, response.followup_id)
            assert acknowledged.acknowledged_followups == 1
            assert followup.status == MentionFollowupStatus.CANCELLED
            assert followup.target_user_ids == []
            assert followup.classification_result is None
            model_log = await db.scalar(select(ModelCallLog))
            assert model_log.status == ModelCallStatus.SUCCEEDED
            assert model_log.outcome == "CLAIM_LOST"
            assert model_log.scheduled_for_send is False
            assert model_log.message_sent is False
        await engine.dispose()


def _plain_event(message_id: str, content: str, sender: str = "sender-user"):
    return IncomingGroupMessage(
        group_id="classifier-group",
        message_id=message_id,
        sender_id=sender,
        sender_display_name="Minh",
        sent_at=datetime.now(UTC),
        content=content,
    )


async def test_price_keyword_from_a_customer_queues_the_sales_list() -> None:
    engine, sessions = await _price_database()
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _plain_event("ask", "Báo giá cho anh cái này với")
        )
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup.trigger == MentionFollowupTrigger.PRICE_INQUIRY
        assert followup.status == MentionFollowupStatus.CLASSIFYING
        # The sales list, not the people who chase unanswered mentions.
        assert followup.target_user_ids == ["sales-user"]
    await engine.dispose()


async def test_price_trigger_ignores_staff_and_messages_without_the_keyword() -> None:
    engine, sessions = await _price_database()
    async with sessions() as db:
        # Staff talking about price among themselves must not summon each other.
        from_sales = await schedule_from_incoming_event(
            db, _plain_event("staff", "giá bên mình đang là 200k nhé", sender="sales-user")
        )
        assert from_sales.followup_id is None
        no_keyword = await schedule_from_incoming_event(
            db, _plain_event("chat", "anh chuyển tiền chưa em")
        )
        assert no_keyword.followup_id is None
    await engine.dispose()


async def test_price_trigger_stays_off_until_enabled() -> None:
    engine, sessions = await _price_database(price_enabled=False)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _plain_event("ask", "Báo giá cho anh với")
        )
        assert response.followup_id is None
    await engine.dispose()


async def test_price_inquiry_tags_only_on_a_confident_yes(monkeypatch) -> None:
    """The decision inverts here: anything but a confident yes must stay silent."""
    outcomes = {
        "yes": (MentionClassification.NEED_RESPONSE, 0.90, MentionFollowupStatus.PENDING),
        "weak": (MentionClassification.NEED_RESPONSE, 0.40, MentionFollowupStatus.SKIPPED),
        "unsure": (MentionClassification.UNCERTAIN, 0.99, MentionFollowupStatus.SKIPPED),
        "incidental": (MentionClassification.FYI, 0.99, MentionFollowupStatus.SKIPPED),
    }
    for key, (label, confidence, expected) in outcomes.items():
        engine, sessions = await _price_database()
        monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
        prompts: list[str] = []

        async def classify(
            _payload, *, model=None, prompt=None, _label=label, _conf=confidence, _seen=prompts
        ):
            _seen.append(prompt)
            return _ModelResult(
                decisions=[
                    MentionDecision(
                        target_id="T1",
                        classification=_label,
                        confidence=_conf,
                        reason_code=MentionReasonCode.QUESTION,
                    )
                ],
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            )

        monkeypatch.setattr(mention_classifier, "classify_payload", classify)
        async with sessions() as db:
            response = await schedule_from_incoming_event(
                db, _plain_event(f"ask-{key}", "cái này bao nhiêu tiền v anh")
            )
        claimed = await mention_classifier.claim_pending_classifications()
        await mention_classifier.process_classification(*claimed[0])
        async with sessions() as db:
            followup = await db.get(MentionFollowup, response.followup_id)
            assert followup.status == expected, f"{key}: {followup.status}"
        # It must be asked the price question, not the mention question.
        assert prompts == [mention_classifier.PRICE_CLASSIFIER_PROMPT]
        await engine.dispose()


async def test_price_inquiry_stays_silent_when_the_model_fails(monkeypatch) -> None:
    """A mention falls back to tagging; a price inquiry must fall back to nothing."""
    engine, sessions = await _price_database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)

    async def explode(*_args, **_kwargs):
        raise TimeoutError("model unreachable")

    async def swallow(*_args, **_kwargs):
        return None

    monkeypatch.setattr(mention_classifier, "classify_payload", explode)
    monkeypatch.setattr(mention_classifier, "report_async", swallow)
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db, _plain_event("ask", "báo giá giúp anh")
        )
    claimed = await mention_classifier.claim_pending_classifications()
    await mention_classifier.process_classification(*claimed[0])
    async with sessions() as db:
        followup = await db.get(MentionFollowup, response.followup_id)
        assert followup.status == MentionFollowupStatus.SKIPPED
        assert followup.target_user_ids == []
        assert "TimeoutError" in followup.classification_error
        model_log = await db.scalar(select(ModelCallLog))
        assert model_log.status == ModelCallStatus.FAILED
        assert model_log.outcome == "SAFE_FALLBACK_SKIP"
        assert model_log.error_type == "TimeoutError"
        assert model_log.scheduled_for_send is False
    await engine.dispose()


async def test_overdue_price_inquiry_is_dropped_while_a_mention_is_released(
    monkeypatch,
) -> None:
    """The deadline sweep is the other place the two triggers must part ways."""
    engine, sessions = await _price_database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)

    async def swallow(*_args, **_kwargs):
        return None

    monkeypatch.setattr(mention_classifier, "report_async", swallow)
    stale = datetime.now(UTC) - timedelta(hours=2)
    async with sessions() as db:
        automation = await db.scalar(select(MentionAutomation))
        for trigger, message_id in (
            (MentionFollowupTrigger.MENTION, "old-mention"),
            (MentionFollowupTrigger.PRICE_INQUIRY, "old-price"),
        ):
            db.add(
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id=message_id,
                    trigger=trigger,
                    target_user_ids=["target-user"],
                    target_display_names=["Abcd"],
                    due_at=stale,
                    status=MentionFollowupStatus.CLASSIFYING,
                    created_at=stale,
                )
            )
        await db.commit()

    assert await mention_classifier.release_overdue_classifications() == 2
    async with sessions() as db:
        rows = {
            row.source_message_id: row
            for row in (await db.scalars(select(MentionFollowup))).all()
        }
        assert rows["old-mention"].status == MentionFollowupStatus.PENDING
        assert rows["old-price"].status == MentionFollowupStatus.SKIPPED
        assert rows["old-price"].target_user_ids == []
    await engine.dispose()


async def test_one_person_waiting_is_not_tagged_twice_over() -> None:
    """A second follow-up for somebody already waiting would be an identical tag.

    The bot can only send a bare "@Name", so two pending follow-ups for the same
    person are indistinguishable in the group and only double the noise. They are
    tagged every cycle anyway, and their first reply clears both.
    """
    engine, sessions = await _price_database()
    async with sessions() as db:
        automation = await db.scalar(select(MentionAutomation))
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="sales-user",
                display_name="Sales",
                kind=MentionTargetKind.MENTION,
            )
        )
        await db.commit()

        tagged = await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="classifier-group",
                message_id="tag-sales",
                sender_id="sender-user",
                content="<MENTION:Sales> xem giúp anh cái hợp đồng",
                mentions=[
                    IncomingMention(
                        user_id="sales-user", position=0, length=15, text="<MENTION:Sales>"
                    )
                ],
            ),
        )
        assert (await db.get(MentionFollowup, tagged.followup_id)).status in {
            MentionFollowupStatus.CLASSIFYING,
            MentionFollowupStatus.PENDING,
        }

        # A price question arrives while that tag is still unanswered.
        asked = await schedule_from_incoming_event(
            db, _plain_event("ask-price", "báo giá cho anh với")
        )
        assert asked.followup_id is None

        # One reply from them clears what is waiting, so nothing is stranded.
        await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="classifier-group",
                message_id="reply",
                sender_id="sales-user",
                content="dạ em xem rồi anh",
            ),
        )
        assert (
            await db.get(MentionFollowup, tagged.followup_id)
        ).status == MentionFollowupStatus.CANCELLED
    await engine.dispose()


async def test_a_name_containing_gia_does_not_trigger_the_price_classifier() -> None:
    """The keyword must come from what the sender typed, not from a display name."""
    engine, sessions = await _price_database()
    async with sessions() as db:
        response = await schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="classifier-group",
                message_id="named",
                sender_id="sender-user",
                content="@Giá Nguyễn cho anh hỏi cái này với",
                mentions=[
                    IncomingMention(
                        user_id="nguoi-la", position=0, length=11, text="@Giá Nguyễn"
                    )
                ],
            ),
        )
        assert response.followup_id is None
    await engine.dispose()


async def test_tagging_again_keeps_the_first_reminder_running() -> None:
    """A second tag does not restart the clock, and the usual order still works.

    "@Abcd a cắt cho em nhé" then "@Abcd t2 em lấy nhé" is how people actually
    write: the request first, details after. The second tag is suppressed, but
    the first already carries the request so the reminder still happens.

    The reverse order — an acknowledgement first, the request seconds later — is
    the one case where the second tag is lost. It is left as is: the window is
    the few seconds a classification takes, and the person still got a direct
    Zalo notification from the human tag.
    """
    engine, sessions = await _price_database()
    async with sessions() as db:
        first = await schedule_from_incoming_event(
            db, _mention_event("m1", "@Abcd a cắt cho em nhé")
        )
        again = await schedule_from_incoming_event(
            db, _mention_event("m2", "@Abcd t2 em lấy nhé")
        )
        assert again.followup_id is None

        followups = (await db.scalars(select(MentionFollowup))).all()
        assert len(followups) == 1
        # Still pointed at the first message, on its original schedule.
        assert followups[0].source_message_id == "m1"
        assert followups[0].id == first.followup_id
    await engine.dispose()


def _ack_then(*labels: str):
    """A model stub that answers with the given label per call, in order."""
    calls = iter(labels)

    async def classify(_payload, *, model=None, prompt=None):
        label = next(calls)
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification(label),
                    confidence=0.99,
                    reason_code=MentionReasonCode.AMBIGUOUS,
                )
            ],
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    return classify


async def _drain(limit: int = 6) -> None:
    for _ in range(limit):
        claimed = await mention_classifier.claim_pending_classifications()
        if not claimed:
            return
        for followup_id, stamp in claimed:
            await mention_classifier.process_classification(followup_id, stamp)


async def test_a_skip_looks_at_the_message_that_arrived_meanwhile(monkeypatch) -> None:
    """The message suppressed during classification gets its turn if the first skips.

    "@Abcd ok cảm ơn" then "@Abcd gửi anh báo cáo" seconds later: the second was
    dropped because Abcd was already waiting, and the first then turned out to be
    an acknowledgement. Nobody used to be tagged at all.
    """
    engine, sessions = await _price_database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    monkeypatch.setattr(
        mention_classifier,
        "classify_payload",
        _ack_then("ACKNOWLEDGEMENT", "NEED_RESPONSE"),
    )
    async with sessions() as db:
        first = await schedule_from_incoming_event(
            db, _mention_event("m1", "@Abcd ok anh biết rồi cảm ơn")
        )
        assert (
            await schedule_from_incoming_event(
                db, _mention_event("m2", "@Abcd gửi anh báo cáo quý 3 với")
            )
        ).followup_id is None

    await _drain()
    async with sessions() as db:
        followup = await db.get(MentionFollowup, first.followup_id)
        # Same follow-up, now judged on the later message and scheduled to send.
        assert followup.source_message_id == "m2"
        assert followup.status == MentionFollowupStatus.PENDING
    await engine.dispose()


async def test_a_later_message_cannot_undo_a_decision_to_tag(monkeypatch) -> None:
    """The look-back only ever adds a reason to tag, never removes one.

    Judging the newest message instead would let a trailing "ok" cancel a real
    request that arrived seconds earlier — measured at 2 of 5 sample replies.
    """
    engine, sessions = await _price_database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    calls: list[str] = []

    async def classify(payload, *, model=None, prompt=None):
        calls.append(str(payload["current_message_id"]))
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification.NEED_RESPONSE,
                    confidence=0.99,
                    reason_code=MentionReasonCode.REQUEST,
                )
            ],
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(mention_classifier, "classify_payload", classify)
    async with sessions() as db:
        first = await schedule_from_incoming_event(
            db, _mention_event("m1", "@Abcd gửi anh báo cáo quý 3 với")
        )
        await schedule_from_incoming_event(db, _mention_event("m2", "@Abcd ok"))

    await _drain()
    async with sessions() as db:
        followup = await db.get(MentionFollowup, first.followup_id)
        assert followup.status == MentionFollowupStatus.PENDING
        assert followup.source_message_id == "m1"
        assert calls == ["m1"], "khong duoc phan lai khi da quyet dinh tag"
    await engine.dispose()


async def test_a_run_of_acknowledgements_stops_spending_model_calls(monkeypatch) -> None:
    """Otherwise "ok", "vâng", "cảm ơn" would each buy another classification."""
    engine, sessions = await _price_database()
    monkeypatch.setattr(mention_classifier, "SessionLocal", sessions)
    calls = 0

    async def classify(_payload, *, model=None, prompt=None):
        nonlocal calls
        calls += 1
        return _ModelResult(
            decisions=[
                MentionDecision(
                    target_id="T1",
                    classification=MentionClassification.ACKNOWLEDGEMENT,
                    confidence=0.99,
                    reason_code=MentionReasonCode.ACK_ONLY,
                )
            ],
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(mention_classifier, "classify_payload", classify)
    async with sessions() as db:
        first = await schedule_from_incoming_event(
            db, _mention_event("m1", "@Abcd rõ rồi nha em")
        )
        for index in range(6):
            await schedule_from_incoming_event(
                db, _mention_event(f"m{index + 2}", f"@Abcd vâng em {index}")
            )

    await _drain(limit=10)
    async with sessions() as db:
        followup = await db.get(MentionFollowup, first.followup_id)
        assert followup.status == MentionFollowupStatus.SKIPPED
        assert followup.target_user_ids == []
    assert calls <= mention_classifier.MAX_REPOINTS + 1, f"goi model {calls} lan"
    await engine.dispose()
