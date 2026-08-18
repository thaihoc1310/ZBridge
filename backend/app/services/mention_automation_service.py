import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import MentionAutomation, MentionFollowup, MentionTarget, ZaloGroup
from app.models.entities import MentionFollowupStatus
from app.schemas.api import (
    GroupMemberResponse,
    IncomingEventResponse,
    IncomingGroupMessage,
    MentionAutomationResponse,
    MentionAutomationUpdate,
    MentionTargetResponse,
    MentionTimeWindow,
)
from app.services.group_service import get_group
from app.services.mention_time_windows import (
    DEFAULT_MENTION_WINDOWS,
    next_allowed_at,
    normalize_time_windows,
)
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.mention_automation")


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
                    [MentionFollowupStatus.PENDING, MentionFollowupStatus.PROCESSING]
                ),
            )
        )
        or 0
    )
    return MentionAutomationResponse(
        id=automation.id,
        group_id=group_id,
        enabled=automation.enabled,
        delay_minutes=automation.delay_minutes,
        active_windows=[MentionTimeWindow(**window) for window in automation.active_windows],
        targets=[
            MentionTargetResponse(
                user_id=target.zalo_user_id,
                display_name=target.display_name,
                avatar_url=target.avatar_url,
            )
            for target in automation.targets
        ],
        pending_followups=pending,
        updated_at=automation.updated_at,
    )


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
    if len(unique_targets) != len(data.targets):
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
        configuration_changed = (
            automation.enabled != data.enabled
            or automation.delay_minutes != data.delay_minutes
            or automation.active_windows != active_windows
            or {target.zalo_user_id for target in automation.targets} != set(unique_targets)
        )
        await db.execute(delete(MentionTarget).where(MentionTarget.automation_id == automation.id))
        if configuration_changed:
            await db.execute(
                update(MentionFollowup)
                .where(
                    MentionFollowup.automation_id == automation.id,
                    MentionFollowup.status.in_(
                        [MentionFollowupStatus.PENDING, MentionFollowupStatus.PROCESSING]
                    ),
                )
                .values(
                    status=MentionFollowupStatus.CANCELLED,
                    claimed_at=None,
                    processed_at=datetime.now(UTC),
                )
            )
    automation.enabled = data.enabled
    automation.delay_minutes = data.delay_minutes
    automation.active_windows = active_windows
    for target in data.targets:
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id=target.user_id,
                display_name=target.display_name,
                avatar_url=target.avatar_url,
            )
        )
    await db.commit()
    automation = await _load_automation(db, group_id)
    logger.info(
        "MENTION_AUTOMATION_SAVED group_id=%s enabled=%s targets=%d delay_minutes=%d windows=%d",
        group_id,
        data.enabled,
        len(data.targets),
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
    active_followups = list(
        (
            await db.scalars(
                select(MentionFollowup)
                .where(
                    MentionFollowup.automation_id == automation.id,
                    MentionFollowup.status.in_(
                        [MentionFollowupStatus.PENDING, MentionFollowupStatus.PROCESSING]
                    ),
                )
                .with_for_update()
            )
        ).all()
    )
    acknowledged_followups = 0
    if event.sender_id:
        for followup in active_followups:
            remaining_targets = [
                (user_id, display_name)
                for user_id, display_name in zip(
                    followup.target_user_ids,
                    followup.target_display_names,
                    strict=False,
                )
                if user_id != event.sender_id
            ]
            if len(remaining_targets) == len(followup.target_user_ids):
                continue
            acknowledged_followups += 1
            if remaining_targets:
                followup.target_user_ids = [target[0] for target in remaining_targets]
                followup.target_display_names = [target[1] for target in remaining_targets]
            else:
                followup.status = MentionFollowupStatus.CANCELLED
                followup.claimed_at = None
                followup.processed_at = now

    existing = await db.scalar(
        select(MentionFollowup.id).where(
            MentionFollowup.automation_id == automation.id,
            MentionFollowup.source_message_id == event.message_id,
        )
    )
    if existing:
        if acknowledged_followups:
            await db.commit()
        return IncomingEventResponse(scheduled=False, followup_id=existing)

    active_target_ids = {
        user_id
        for followup in active_followups
        if followup.status in (MentionFollowupStatus.PENDING, MentionFollowupStatus.PROCESSING)
        for user_id in followup.target_user_ids
    }
    mentioned_ids = {mention.user_id for mention in event.mentions}
    matched = [
        target
        for target in automation.targets
        if target.zalo_user_id in mentioned_ids
        and target.zalo_user_id != event.sender_id
        and target.zalo_user_id not in active_target_ids
    ]
    if not matched:
        if acknowledged_followups:
            await db.commit()
            logger.info(
                "MENTION_FOLLOWUP_ACKNOWLEDGED group_id=%s sender_id=%s followups=%d",
                event.group_id,
                event.sender_id,
                acknowledged_followups,
            )
        return IncomingEventResponse(scheduled=False)

    followup = MentionFollowup(
        automation_id=automation.id,
        source_message_id=event.message_id,
        source_sender_id=event.sender_id,
        target_user_ids=[target.zalo_user_id for target in matched],
        target_display_names=[target.display_name for target in matched],
        due_at=next_allowed_at(
            now + timedelta(minutes=automation.delay_minutes),
            automation.active_windows,
        ),
        status=MentionFollowupStatus.PENDING,
    )
    automation_id = automation.id
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
        "MENTION_FOLLOWUP_SCHEDULED followup_id=%s group_id=%s targets=%d due_at=%s",
        followup.id,
        automation.zalo_group_id,
        len(matched),
        followup.due_at.isoformat(),
    )
    return IncomingEventResponse(
        scheduled=True,
        followup_id=followup.id,
        matched_targets=len(matched),
    )
