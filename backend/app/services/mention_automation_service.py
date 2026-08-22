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
    DEFAULT_MENTION_WINDOWS,
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


def _acknowledge_target(
    followups: list[MentionFollowup],
    target_user_id: str,
    *,
    now: datetime,
    requeue_at: datetime,
    occurred_at: datetime,
) -> int:
    """Remove one person from every active loop currently waiting for them."""
    acknowledged = 0
    for followup in followups:
        created_at = followup.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if created_at > occurred_at:
            # A delayed/replayed event must not acknowledge a loop that did not
            # exist when the member actually messaged or reacted.
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
            followup.status = MentionFollowupStatus.CANCELLED
            followup.claimed_at = None
            followup.processed_at = now
    return acknowledged


async def acknowledge_from_reaction(
    db: AsyncSession, event: IncomingGroupReaction
) -> IncomingEventResponse:
    """Treat a live heart/like by a waiting target exactly like their message."""
    if event.reaction not in ACKNOWLEDGING_REACTIONS:
        return IncomingEventResponse(scheduled=False)

    automation = await db.scalar(
        select(MentionAutomation)
        .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
        .where(
            ZaloGroup.zalo_group_id == event.group_id,
            ZaloGroup.is_available.is_(True),
            MentionAutomation.enabled.is_(True),
        )
    )
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
    acknowledged = _acknowledge_target(
        followups,
        event.reactor_id,
        now=now,
        requeue_at=next_allowed_at(
            now + timedelta(minutes=automation.delay_minutes),
            automation.active_windows,
        ),
        occurred_at=occurred_at,
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


async def _load_automation(db: AsyncSession, group_id: uuid.UUID) -> MentionAutomation | None:
    return await db.scalar(
        select(MentionAutomation)
        .options(selectinload(MentionAutomation.targets))
        .execution_options(populate_existing=True)
        .where(MentionAutomation.zalo_group_id == group_id)
    )


async def _to_response(
    db: AsyncSession, group_id: uuid.UUID, automation: MentionAutomation | None
) -> MentionAutomationResponse:
    if automation is None:
        return MentionAutomationResponse(
            group_id=group_id,
            enabled=False,
            mention_tag_enabled=True,
            price_inquiry_enabled=False,
            delay_minutes=120,
            active_windows=[MentionTimeWindow(**window) for window in DEFAULT_MENTION_WINDOWS],
            targets=[],
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

    automation = await _load_automation(db, group_id)
    if automation is None:
        automation = MentionAutomation(zalo_group_id=group_id)
        db.add(automation)
        await db.flush()
    else:
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
    automation = await db.scalar(
        select(MentionAutomation)
        .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
        .options(
            selectinload(MentionAutomation.targets),
            selectinload(MentionAutomation.group),
        )
        .where(
            ZaloGroup.zalo_group_id == event.group_id,
            ZaloGroup.is_available.is_(True),
            MentionAutomation.enabled.is_(True),
        )
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
        if target.kind == MentionTargetKind.PRICE
        and target.zalo_user_id not in active_target_ids
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
    db.add(followup)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(MentionFollowup.id).where(
                MentionFollowup.automation_id == automation_id,
                MentionFollowup.source_message_id == event.message_id,
            )
        )
        return IncomingEventResponse(scheduled=False, followup_id=existing)
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
    )
