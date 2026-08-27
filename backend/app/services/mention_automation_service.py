import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    MentionAutomation,
    MentionContextMessage,
    MentionFollowup,
    MentionTarget,
    ZaloGroup,
)
from app.models.entities import (
    MentionFollowupStatus,
    MentionFollowupTrigger,
    MentionTargetKind,
)
from app.schemas.api import (
    GroupMemberResponse,
    IncomingEventResponse,
    IncomingGroupMessage,
    IncomingGroupReaction,
    MentionAutomationResponse,
    MentionAutomationUpdate,
    MentionTargetResponse,
    MentionTimeWindow,
)
from app.services.group_service import get_group
from app.services.mention_rules import (
    is_bare_mention,
    matches_skip_phrase,
    mentions_price,
)
from app.services.mention_settings_service import get_or_create_mention_settings
from app.services.mention_time_windows import (
    next_allowed_at,
    normalize_time_windows,
)
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.mention_automation")

ACTIVE_FOLLOWUP_STATUSES = (
    MentionFollowupStatus.CLASSIFYING,
    MentionFollowupStatus.PENDING,
    MentionFollowupStatus.PROCESSING,
)
ACKNOWLEDGING_REACTIONS = {"heart", "like"}


async def _lock_enabled_automation(
    db: AsyncSession,
    zalo_group_id: str,
    *,
    load_targets: bool = False,
) -> MentionAutomation | None:
    """Lock the group, then its automation — the order `sync_groups` uses.

    Two statements rather than one join, for a reason that is easy to get wrong.
    A joined ``FOR UPDATE`` without ``of=`` locks a row in every joined table, and
    then the acquisition order is up to the query plan — it can take the
    automation before the group while a group sync takes them the other way, and
    the two deadlock.

    But narrowing that same join to ``of=MentionAutomation`` trades the deadlock
    for a lost invariant: Postgres only re-checks a predicate against the newest
    row version for rows the statement *locks*. With only the automation locked,
    a sync that flipped ``is_available`` to false mid-wait is invisible, and this
    returns an automation for a group that is already gone — creating follow-ups
    and paying for classifications that the send step will only cancel later.

    Locking the group in its own statement gets both: the order matches
    ``sync_groups``, and the availability predicate is re-checked under the lock.
    """
    group_id = await db.scalar(
        select(ZaloGroup.id)
        .where(
            ZaloGroup.zalo_group_id == zalo_group_id,
            ZaloGroup.is_available.is_(True),
        )
        .with_for_update()
    )
    if group_id is None:
        return None
    statement = select(MentionAutomation).where(
        MentionAutomation.zalo_group_id == group_id,
        MentionAutomation.enabled.is_(True),
    )
    if load_targets:
        statement = statement.options(selectinload(MentionAutomation.targets))
    # lock-scope: single-table — mention_automations only; the group above is
    # locked by its own statement, in order.
    return await db.scalar(statement.with_for_update())


async def _attach_reaction_to_context(
    db: AsyncSession,
    automation_id: uuid.UUID,
    event: IncomingGroupReaction,
    *,
    occurred_at: datetime,
) -> bool:
    """Attach one reaction to its extant message, once.

    zca-js may identify a reacted message by gMsgID on desktop but only cMsgID
    on mobile. Normal messages retain every alias, so matching either is enough.
    Keeping the reaction inside the message also gives both the exact same
    retention lifecycle.
    """
    if not event.event_id or not event.target_message_ids:
        return False

    context_messages = list(
        (
            await db.scalars(
                select(MentionContextMessage)
                .where(MentionContextMessage.automation_id == automation_id)
                .order_by(MentionContextMessage.sent_at.desc())
                .with_for_update()
            )
        ).all()
    )
    for message in context_messages:
        if any(
            str(reaction.get("event_id") or "") == event.event_id
            for reaction in (message.reactions or [])
        ):
            return False

    target_ids = set(event.target_message_ids)
    target_message = next(
        (
            message
            for message in context_messages
            if target_ids.intersection({message.message_id, *(message.message_aliases or [])})
        ),
        None,
    )
    if target_message is None:
        return False

    target_message.reactions = [
        *(target_message.reactions or []),
        {
            "event_id": event.event_id,
            "reactor_id": event.reactor_id,
            "reaction": event.reaction,
            "reacted_at": occurred_at.isoformat(),
        },
    ]
    return True


def _acknowledge_target(
    followups: list[MentionFollowup],
    target_user_id: str,
    *,
    now: datetime,
    requeue_at: datetime,
    occurred_at: datetime,
    started_at_by_source: dict[str, datetime],
) -> int:
    """Remove one person from every active loop currently waiting for them."""
    acknowledged = 0
    for followup in followups:
        started_at = started_at_by_source.get(followup.source_message_id, followup.created_at)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if started_at > occurred_at:
            # A delayed/replayed event must not acknowledge a loop that did not
            # exist when the member actually messaged or reacted. Compare with
            # the source event, not the DB row: a very fast reply/reaction can
            # legitimately happen before the backend finishes inserting the row.
            continue
        remaining_targets = [
            (user_id, display_name)
            for user_id, display_name in zip(
                followup.target_user_ids,
                followup.target_display_names,
                strict=False,
            )
            if user_id != target_user_id
        ]
        if len(remaining_targets) == len(followup.target_user_ids):
            continue
        acknowledged += 1
        if remaining_targets:
            followup.target_user_ids = [target[0] for target in remaining_targets]
            followup.target_display_names = [target[1] for target in remaining_targets]
            followup.evaluated_due_at = None
            # A worker may already hold a snapshot containing the person who just
            # acknowledged. Invalidate that claim so it cannot tag/classify the
            # stale target list, then let the appropriate dispatcher pick it up.
            if followup.status == MentionFollowupStatus.PROCESSING:
                followup.status = MentionFollowupStatus.PENDING
                followup.due_at = requeue_at
                followup.claimed_at = None
                followup.attempt_count = 0
            elif followup.status == MentionFollowupStatus.CLASSIFYING:
                followup.claimed_at = None
                followup.attempt_count = 0
        else:
            followup.target_user_ids = []
            followup.target_display_names = []
            followup.status = MentionFollowupStatus.CANCELLED
            followup.claimed_at = None
            followup.processed_at = now
    return acknowledged


def _invalidate_for_new_context(followups: list[MentionFollowup]) -> None:
    """Make every live loop read a newly arrived message before its next send.

    This also invalidates in-flight classification/send claims. Whichever side
    already holds the row lock commits first; the other side then observes the
    changed claim instead of applying a verdict based on stale conversation.
    """
    for followup in followups:
        if followup.status not in ACTIVE_FOLLOWUP_STATUSES:
            continue
        followup.evaluated_due_at = None
        if followup.status == MentionFollowupStatus.PROCESSING:
            followup.status = MentionFollowupStatus.PENDING
        if followup.status in {
            MentionFollowupStatus.CLASSIFYING,
            MentionFollowupStatus.PENDING,
        }:
            followup.claimed_at = None
            followup.attempt_count = 0


def _followups_started_before(
    followups: list[MentionFollowup],
    occurred_at: datetime,
    started_at_by_source: dict[str, datetime],
) -> list[MentionFollowup]:
    """Loops that already existed when this event actually happened.

    The gateway outbox retries a delayed event for as long as it takes, so an
    event can arrive hours after it occurred. Such an event belongs in history,
    but it is not new context for a loop opened after it: invalidating those
    would drop a live claim and force a needless model call.
    """
    relevant: list[MentionFollowup] = []
    for followup in followups:
        started_at = started_at_by_source.get(
            followup.source_message_id, followup.created_at
        )
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if started_at <= occurred_at:
            relevant.append(followup)
    return relevant


async def _started_at_by_source(
    db: AsyncSession, followups: list[MentionFollowup]
) -> dict[str, datetime]:
    """Return the event time that opened each loop in this automation."""
    if not followups:
        return {}
    source_ids = {followup.source_message_id for followup in followups}
    rows = (
        await db.execute(
            select(MentionContextMessage.message_id, MentionContextMessage.sent_at).where(
                MentionContextMessage.automation_id == followups[0].automation_id,
                MentionContextMessage.message_id.in_(source_ids),
            )
        )
    ).all()
    return {
        message_id: sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=UTC)
        for message_id, sent_at in rows
    }


async def acknowledge_from_reaction(
    db: AsyncSession, event: IncomingGroupReaction
) -> IncomingEventResponse:
    """Treat a live heart/like by a waiting target exactly like their message."""
    if event.reaction not in ACKNOWLEDGING_REACTIONS:
        return IncomingEventResponse(scheduled=False)

    automation = await _lock_enabled_automation(db, event.group_id)
    if automation is None:
        return IncomingEventResponse(scheduled=False)

    followups = list(
        (
            await db.scalars(
                select(MentionFollowup)
                .where(
                    MentionFollowup.automation_id == automation.id,
                    MentionFollowup.status.in_(ACTIVE_FOLLOWUP_STATUSES),
                )
                .with_for_update()
            )
        ).all()
    )
    now = datetime.now(UTC)
    occurred_at = event.reacted_at or now
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    context_changed = await _attach_reaction_to_context(
        db,
        automation.id,
        event,
        occurred_at=occurred_at,
    )
    started_at_by_source = await _started_at_by_source(db, followups)
    acknowledged = _acknowledge_target(
        followups,
        event.reactor_id,
        now=now,
        requeue_at=next_allowed_at(
            now + timedelta(minutes=automation.delay_minutes),
            automation.active_windows,
        ),
        occurred_at=occurred_at,
        started_at_by_source=started_at_by_source,
    )
    if context_changed:
        _invalidate_for_new_context(
            _followups_started_before(followups, occurred_at, started_at_by_source)
        )
    await db.commit()
    if acknowledged:
        logger.info(
            "MENTION_FOLLOWUP_ACKNOWLEDGED group_id=%s target_id=%s"
            " followups=%d acknowledged_by=%s",
            event.group_id,
            event.reactor_id,
            acknowledged,
            event.reaction,
        )
    if context_changed:
        logger.info(
            "MENTION_REACTION_CONTEXT_ATTACHED group_id=%s reactor_id=%s reaction=%s",
            event.group_id,
            event.reactor_id,
            event.reaction,
        )
    return IncomingEventResponse(
        scheduled=False,
        acknowledged_followups=acknowledged,
    )


async def list_group_members(db: AsyncSession, group_id: uuid.UUID) -> list[GroupMemberResponse]:
    group = await get_group(db, group_id)
    if not group.is_available:
        raise AppError("GROUP_UNAVAILABLE", "Nhóm hiện không còn khả dụng.", 409)
    try:
        members = await zalo_gateway.get_group_members(group.zalo_group_id)
    except GatewayError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc
    return [GroupMemberResponse.model_validate(member) for member in members]


async def _load_automation(
    db: AsyncSession, group_id: uuid.UUID, *, for_update: bool = False
) -> MentionAutomation | None:
    statement = (
        select(MentionAutomation)
        .options(selectinload(MentionAutomation.targets))
        .execution_options(populate_existing=True)
        .where(MentionAutomation.zalo_group_id == group_id)
    )
    if for_update:
        # lock-scope: single-table — mention_automations only, no join.
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def _to_response(
    db: AsyncSession, group_id: uuid.UUID, automation: MentionAutomation | None
) -> MentionAutomationResponse:
    if automation is None:
        raise AppError(
            "MENTION_AUTOMATION_CONFIG_MISSING",
            "Nhóm thiếu cấu hình tag tên tự động.",
            500,
        )
    pending = int(
        await db.scalar(
            select(func.count())
            .select_from(MentionFollowup)
            .where(
                MentionFollowup.automation_id == automation.id,
                MentionFollowup.status.in_(
                    [
                        MentionFollowupStatus.CLASSIFYING,
                        MentionFollowupStatus.PENDING,
                        MentionFollowupStatus.PROCESSING,
                    ]
                ),
            )
        )
        or 0
    )
    return MentionAutomationResponse(
        id=automation.id,
        group_id=group_id,
        enabled=automation.enabled,
        mention_tag_enabled=automation.mention_tag_enabled,
        price_inquiry_enabled=automation.price_inquiry_enabled,
        delay_minutes=automation.delay_minutes,
        active_windows=[MentionTimeWindow(**window) for window in automation.active_windows],
        targets=_target_responses(automation, MentionTargetKind.MENTION),
        price_targets=_target_responses(automation, MentionTargetKind.PRICE),
        pending_followups=pending,
        updated_at=automation.updated_at,
    )


def _target_ids(automation: MentionAutomation, kind: MentionTargetKind) -> set[str]:
    return {t.zalo_user_id for t in automation.targets if t.kind == kind}


def _target_responses(
    automation: MentionAutomation, kind: MentionTargetKind
) -> list[MentionTargetResponse]:
    return [
        MentionTargetResponse(
            user_id=target.zalo_user_id,
            display_name=target.display_name,
            avatar_url=target.avatar_url,
        )
        for target in automation.targets
        if target.kind == kind
    ]


async def get_mention_automation(
    db: AsyncSession, group_id: uuid.UUID
) -> MentionAutomationResponse:
    await get_group(db, group_id)
    return await _to_response(db, group_id, await _load_automation(db, group_id))


async def save_mention_automation(
    db: AsyncSession, group_id: uuid.UUID, data: MentionAutomationUpdate
) -> MentionAutomationResponse:
    group = await get_group(db, group_id)
    if not group.is_available:
        raise AppError("GROUP_UNAVAILABLE", "Nhóm hiện không còn khả dụng.", 409)
    unique_targets = {target.user_id: target for target in data.targets}
    unique_price_targets = {target.user_id: target for target in data.price_targets}
    if len(unique_targets) != len(data.targets) or len(unique_price_targets) != len(
        data.price_targets
    ):
        raise AppError("DUPLICATE_TARGET", "Danh sách có thành viên bị trùng.", 422)
    try:
        active_windows = normalize_time_windows(
            [window.model_dump() for window in data.active_windows]
        )
    except ValueError as exc:
        raise AppError("INVALID_TIME_WINDOWS", str(exc), 422) from exc

    # Serialize configuration changes with incoming events. Otherwise an event
    # can read the old targets, wait while this transaction disables them, then
    # create a brand-new follow-up for a target that was just removed.
    automation = await _load_automation(db, group_id, for_update=True)
    if automation is None:
        raise AppError(
            "MENTION_AUTOMATION_CONFIG_MISSING",
            "Nhóm thiếu cấu hình tag tên tự động.",
            500,
        )
    await db.execute(delete(MentionTarget).where(MentionTarget.automation_id == automation.id))
    await reconcile_followups(
        db,
        automation.id,
        allowed={
            MentionFollowupTrigger.MENTION: (
                set(unique_targets) if data.mention_tag_enabled else set()
            ),
            MentionFollowupTrigger.PRICE_INQUIRY: (
                set(unique_price_targets) if data.price_inquiry_enabled else set()
            ),
        },
        now=datetime.now(UTC),
    )
    automation.mention_tag_enabled = data.mention_tag_enabled
    automation.price_inquiry_enabled = data.price_inquiry_enabled
    # The scheduler and classifier still ask one question, so keep the master
    # switch derived from the two features rather than adding a third control.
    automation.enabled = data.mention_tag_enabled or data.price_inquiry_enabled
    automation.delay_minutes = data.delay_minutes
    automation.active_windows = active_windows
    for kind, entries in (
        (MentionTargetKind.MENTION, data.targets),
        (MentionTargetKind.PRICE, data.price_targets),
    ):
        for target in entries:
            db.add(
                MentionTarget(
                    automation_id=automation.id,
                    zalo_user_id=target.user_id,
                    display_name=target.display_name,
                    avatar_url=target.avatar_url,
                    kind=kind,
                )
            )
    await db.commit()
    automation = await _load_automation(db, group_id)
    logger.info(
        "MENTION_AUTOMATION_SAVED group_id=%s mention=%s price=%s targets=%d/%d"
        " delay_minutes=%d windows=%d",
        group_id,
        data.mention_tag_enabled,
        data.price_inquiry_enabled,
        len(data.targets),
        len(data.price_targets),
        data.delay_minutes,
        len(active_windows),
    )
    return await _to_response(db, group_id, automation)


async def schedule_from_incoming_event(
    db: AsyncSession, event: IncomingGroupMessage
) -> IncomingEventResponse:
    automation = await _lock_enabled_automation(
        db, event.group_id, load_targets=True
    )
    if automation is None:
        return IncomingEventResponse(scheduled=False)

    now = datetime.now(UTC)
    sent_at = event.sent_at or now
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    context_message = await db.scalar(
        select(MentionContextMessage.id).where(
            MentionContextMessage.automation_id == automation.id,
            MentionContextMessage.message_id == event.message_id,
        )
    )
    if context_message is None:
        db.add(
            MentionContextMessage(
                automation_id=automation.id,
                message_id=event.message_id,
                message_aliases=list(dict.fromkeys([event.message_id, *event.message_aliases])),
                sender_id=event.sender_id,
                sender_display_name=event.sender_display_name,
                content=event.content,
                mentions=[mention.model_dump() for mention in event.mentions],
                sent_at=sent_at,
            )
        )
    global_settings = await get_or_create_mention_settings(db)
    active_followups = list(
        (
            await db.scalars(
                select(MentionFollowup)
                .where(
                    MentionFollowup.automation_id == automation.id,
                    MentionFollowup.status.in_(ACTIVE_FOLLOWUP_STATUSES),
                )
                .with_for_update()
            )
        ).all()
    )
    started_at_by_source = await _started_at_by_source(db, active_followups)
    acknowledged_followups = (
        _acknowledge_target(
            active_followups,
            event.sender_id,
            now=now,
            requeue_at=next_allowed_at(
                now + timedelta(minutes=automation.delay_minutes),
                automation.active_windows,
            ),
            occurred_at=sent_at,
            started_at_by_source=started_at_by_source,
        )
        if event.sender_id
        else 0
    )
    if acknowledged_followups:
        logger.info(
            "MENTION_FOLLOWUP_ACKNOWLEDGED group_id=%s target_id=%s"
            " followups=%d acknowledged_by=message",
            event.group_id,
            event.sender_id,
            acknowledged_followups,
        )

    # A coworker may have answered on the target's behalf. Even when this sender
    # is not a configured target, no previously approved send may ignore the new
    # context; the due dispatcher will wait for another AI verdict. Bounded by
    # the same time guard as the reaction path: a replayed message is not new
    # context for a loop that opened after it was sent.
    _invalidate_for_new_context(
        _followups_started_before(active_followups, sent_at, started_at_by_source)
    )

    existing = await db.scalar(
        select(MentionFollowup.id).where(
            MentionFollowup.automation_id == automation.id,
            MentionFollowup.source_message_id == event.message_id,
        )
    )
    if existing:
        await db.commit()
        return IncomingEventResponse(
            scheduled=False,
            followup_id=existing,
            acknowledged_followups=acknowledged_followups,
        )

    # Across both triggers on purpose. The bot can only send a bare "@Name", so a
    # second follow-up for somebody already waiting produces an identical tag
    # that nobody can tell apart — it just doubles the noise. They are being
    # tagged every cycle regardless, and their first reply clears both.
    active_target_ids = {
        user_id
        for followup in active_followups
        if followup.status
        in (
            MentionFollowupStatus.CLASSIFYING,
            MentionFollowupStatus.PENDING,
            MentionFollowupStatus.PROCESSING,
        )
        for user_id in followup.target_user_ids
    }
    mentioned_ids = {mention.user_id for mention in event.mentions}
    matched = [
        target
        for target in automation.targets
        if target.kind == MentionTargetKind.MENTION
        and automation.mention_tag_enabled
        and target.zalo_user_id in mentioned_ids
        and target.zalo_user_id != event.sender_id
        and target.zalo_user_id not in active_target_ids
    ]
    if not matched:
        price_targets = _price_inquiry_targets(
            automation, event, active_target_ids, global_settings
        )
        if price_targets:
            return await _create_followup(
                db,
                automation,
                event,
                price_targets,
                now,
                trigger=MentionFollowupTrigger.PRICE_INQUIRY,
                initial_status=MentionFollowupStatus.CLASSIFYING,
                acknowledged_followups=acknowledged_followups,
            )
        await db.commit()
        return IncomingEventResponse(
            scheduled=False,
            acknowledged_followups=acknowledged_followups,
        )

    target_display_names = [target.display_name for target in matched]
    bare_mention = is_bare_mention(
        event,
        target_display_names=target_display_names,
    )
    skip_by_rule = matches_skip_phrase(
        event,
        global_settings.skip_phrases,
        target_display_names=target_display_names,
    )
    if skip_by_rule:
        initial_status = MentionFollowupStatus.SKIPPED
        classification_model = "rules:v1"
        classification_result = [
            {
                "target_user_id": target.zalo_user_id,
                "classification": "ACKNOWLEDGEMENT",
                "confidence": 1.0,
                "reason_code": "CONFIGURED_SKIP_PHRASE",
                "skipped": True,
            }
            for target in matched
        ]
    elif bare_mention and global_settings.bare_mention_requires_response:
        initial_status = MentionFollowupStatus.PENDING
        classification_model = "rules:v1"
        classification_result = [
            {
                "target_user_id": target.zalo_user_id,
                "classification": "NEED_RESPONSE",
                "confidence": 1.0,
                "reason_code": "BARE_MENTION",
                "skipped": False,
            }
            for target in matched
        ]
    elif global_settings.ai_classifier_enabled:
        initial_status = MentionFollowupStatus.CLASSIFYING
        classification_model = None
        classification_result = None
    else:
        initial_status = MentionFollowupStatus.PENDING
        classification_model = "safe-fallback"
        classification_result = None

    return await _create_followup(
        db,
        automation,
        event,
        matched,
        now,
        trigger=MentionFollowupTrigger.MENTION,
        initial_status=initial_status,
        acknowledged_followups=acknowledged_followups,
        classification_model=classification_model,
        classification_result=classification_result,
    )


async def reconcile_followups(
    db: AsyncSession,
    automation_id: uuid.UUID,
    *,
    allowed: dict[MentionFollowupTrigger, set[str]],
    now: datetime,
) -> int:
    """Prune running follow-ups to the people still configured, and say how many died.

    Cancelling everything on any edit was losing real reminders: changing the
    delay, the active hours, or somebody else's name would wipe a nudge that had
    nothing to do with the change. A follow-up only ends when nobody it was
    waiting on is configured any more — the same rule as when a target replies.
    """
    followups = list(
        (
            await db.scalars(
                select(MentionFollowup).where(
                    MentionFollowup.automation_id == automation_id,
                    MentionFollowup.status.in_(
                        [
                            MentionFollowupStatus.CLASSIFYING,
                            MentionFollowupStatus.PENDING,
                            MentionFollowupStatus.PROCESSING,
                        ]
                    ),
                )
            )
        ).all()
    )
    cancelled = 0
    for followup in followups:
        keep = [
            (user_id, display_name)
            for user_id, display_name in zip(
                followup.target_user_ids, followup.target_display_names, strict=False
            )
            if user_id in allowed.get(followup.trigger, set())
        ]
        if not keep:
            followup.status = MentionFollowupStatus.CANCELLED
            followup.claimed_at = None
            followup.processed_at = now
            cancelled += 1
        elif len(keep) != len(followup.target_user_ids):
            followup.target_user_ids = [item[0] for item in keep]
            followup.target_display_names = [item[1] for item in keep]
    return cancelled


def _price_inquiry_targets(
    automation: MentionAutomation,
    event: IncomingGroupMessage,
    active_target_ids: set[str],
    global_settings,
) -> list[MentionTarget]:
    """Who to tag when a customer asks about price, or nothing at all.

    Deliberately strict: the classifier is the only check on this path, so if it
    is switched off globally there is no safe way to proceed and we stop here
    rather than tag on a keyword alone.
    """
    if not automation.price_inquiry_enabled or not global_settings.ai_classifier_enabled:
        return []
    if not event.sender_id:
        return []
    # Only the other side of the conversation triggers this. Staff discussing a
    # price among themselves should not summon each other.
    if any(target.zalo_user_id == event.sender_id for target in automation.targets):
        return []
    if not mentions_price(event):
        return []
    return [
        target
        for target in automation.targets
        if target.kind == MentionTargetKind.PRICE and target.zalo_user_id not in active_target_ids
    ]


async def _create_followup(
    db: AsyncSession,
    automation: MentionAutomation,
    event: IncomingGroupMessage,
    targets: list[MentionTarget],
    now: datetime,
    *,
    trigger: MentionFollowupTrigger,
    initial_status: MentionFollowupStatus,
    acknowledged_followups: int = 0,
    classification_model: str | None = None,
    classification_result: list[dict[str, object]] | None = None,
) -> IncomingEventResponse:
    followup = MentionFollowup(
        automation_id=automation.id,
        source_message_id=event.message_id,
        source_sender_id=event.sender_id,
        trigger=trigger,
        target_user_ids=[target.zalo_user_id for target in targets],
        target_display_names=[target.display_name for target in targets],
        due_at=next_allowed_at(
            now + timedelta(minutes=automation.delay_minutes),
            automation.active_windows,
        ),
        status=initial_status,
        processed_at=now if initial_status == MentionFollowupStatus.SKIPPED else None,
        classification_model=classification_model,
        classification_result=classification_result,
    )
    automation_id = automation.id
    group_id = automation.zalo_group_id
    # Insert behind a savepoint. A plain rollback here would also discard the
    # acknowledgements and the context message this transaction already holds —
    # exactly the work that stops a loop running forever.
    #
    # `add` has to happen INSIDE the savepoint. Adding it first puts the pending
    # insert in the enclosing transaction's flush plan, and a failure there
    # deactivates that transaction instead of just this savepoint.
    try:
        async with db.begin_nested():
            db.add(followup)
            await db.flush()
    except IntegrityError:
        # The savepoint rollback normally discards the pending insert already;
        # confirm it, so the commit below cannot retry the row that just failed.
        if followup in db:
            db.expunge(followup)
        existing = await db.scalar(
            select(MentionFollowup.id).where(
                MentionFollowup.automation_id == automation_id,
                MentionFollowup.source_message_id == event.message_id,
            )
        )
        await db.commit()
        logger.info(
            "MENTION_FOLLOWUP_DUPLICATE_SOURCE group_id=%s message_id=%s",
            event.group_id,
            event.message_id,
        )
        return IncomingEventResponse(
            scheduled=False,
            followup_id=existing,
            acknowledged_followups=acknowledged_followups,
        )
    await db.commit()
    await db.refresh(followup)
    logger.info(
        "MENTION_FOLLOWUP_CREATED followup_id=%s group_id=%s trigger=%s status=%s"
        " targets=%d due_at=%s",
        followup.id,
        group_id,
        trigger.value,
        followup.status.value,
        len(targets),
        followup.due_at.isoformat(),
    )
    return IncomingEventResponse(
        scheduled=initial_status != MentionFollowupStatus.SKIPPED,
        followup_id=followup.id,
        matched_targets=len(targets),
        acknowledged_followups=acknowledged_followups,
    )
