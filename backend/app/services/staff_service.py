"""Company-wide roster of taggable people, and the bulk editor built on it."""

import logging
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    Customer,
    MentionAutomation,
    MentionFollowup,
    MentionTarget,
    MentionTargetKind,
    StaffMember,
    ZaloGroup,
)
from app.models.entities import MentionFollowupStatus, MentionFollowupTrigger
from app.schemas.api import (
    BulkMentionApplyResult,
    BulkMentionPreview,
    BulkMentionPreviewRow,
    BulkMentionUpdate,
    GroupMemberResponse,
    StaffMemberResponse,
    StaffRosterUpdate,
)
from app.services.mention_automation_service import reconcile_followups
from app.services.mention_time_windows import normalize_time_windows
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.staff")


async def _usage_counts(db: AsyncSession) -> dict[str, tuple[int, int]]:
    """Where each person is actually being tagged, not merely listed.

    A name left in a customer whose feature is switched off, or whose group the
    bot has lost, tags nobody — counting those read as "reminding 1 customer"
    when nothing was happening.
    """
    rows = (
        await db.execute(
            select(MentionTarget.zalo_user_id, MentionTarget.kind, func.count())
            .join(MentionAutomation, MentionAutomation.id == MentionTarget.automation_id)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(
                ZaloGroup.is_available.is_(True),
                MentionAutomation.enabled.is_(True),
                or_(
                    and_(
                        MentionTarget.kind == MentionTargetKind.MENTION,
                        MentionAutomation.mention_tag_enabled.is_(True),
                    ),
                    and_(
                        MentionTarget.kind == MentionTargetKind.PRICE,
                        MentionAutomation.price_inquiry_enabled.is_(True),
                    ),
                ),
            )
            .group_by(MentionTarget.zalo_user_id, MentionTarget.kind)
        )
    ).all()
    counts: dict[str, tuple[int, int]] = {}
    for user_id, kind, total in rows:
        mention, price = counts.get(user_id, (0, 0))
        if kind == MentionTargetKind.PRICE:
            price = int(total)
        else:
            mention = int(total)
        counts[user_id] = (mention, price)
    return counts


async def list_staff(db: AsyncSession) -> list[StaffMemberResponse]:
    members = (
        await db.scalars(select(StaffMember).order_by(StaffMember.display_name))
    ).all()
    counts = await _usage_counts(db)
    return [
        StaffMemberResponse(
            user_id=member.zalo_user_id,
            display_name=member.display_name,
            avatar_url=member.avatar_url,
            note=member.note,
            mention_customer_count=counts.get(member.zalo_user_id, (0, 0))[0],
            price_customer_count=counts.get(member.zalo_user_id, (0, 0))[1],
        )
        for member in members
    ]


async def save_staff(db: AsyncSession, data: StaffRosterUpdate) -> list[StaffMemberResponse]:
    seen = {member.user_id for member in data.members}
    if len(seen) != len(data.members):
        raise AppError("DUPLICATE_STAFF", "Danh sách nhân sự bị trùng.", 422)
    await db.execute(delete(StaffMember))
    for member in data.members:
        db.add(
            StaffMember(
                zalo_user_id=member.user_id,
                display_name=member.display_name,
                avatar_url=member.avatar_url,
                note=member.note,
            )
        )
    await db.commit()
    logger.info("STAFF_ROSTER_SAVED members=%d", len(data.members))
    return await list_staff(db)


async def list_staff_candidates(db: AsyncSession) -> list[GroupMemberResponse]:
    """Everyone who appears in any available customer group, de-duplicated.

    One gateway call covers every group, so this stays usable as the customer
    list grows.
    """
    groups = (
        await db.scalars(select(ZaloGroup).where(ZaloGroup.is_available.is_(True)))
    ).all()
    if not groups:
        return []
    try:
        by_group = await zalo_gateway.get_group_members_batch(
            [group.zalo_group_id for group in groups]
        )
    except GatewayError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc

    merged: dict[str, GroupMemberResponse] = {}
    for members in by_group.values():
        for member in members:
            user_id = str(member.get("user_id") or "")
            if not user_id or user_id in merged:
                continue
            merged[user_id] = GroupMemberResponse.model_validate(member)
    return sorted(merged.values(), key=lambda member: member.display_name)


async def _selectable_customers(db: AsyncSession) -> list[tuple[Customer, ZaloGroup]]:
    rows = (
        await db.execute(
            select(Customer, ZaloGroup)
            .join(ZaloGroup, ZaloGroup.id == Customer.zalo_group_id)
            .order_by(ZaloGroup.name)
        )
    ).all()
    return [(customer, group) for customer, group in rows]


async def preview_bulk_mention(
    db: AsyncSession, data: BulkMentionUpdate
) -> BulkMentionPreview:
    """Say exactly what applying would do, before anything is written."""
    pairs = await _selectable_customers(db)
    try:
        windows = normalize_time_windows(
            [window.model_dump() for window in data.active_windows]
        )
    except ValueError as exc:
        raise AppError("INVALID_TIME_WINDOWS", str(exc), 422) from exc
    wanted = {target.user_id for target in [*data.targets, *data.price_targets]}
    available_groups = [group for _, group in pairs if group.is_available]
    membership: dict[str, set[str]] = {}
    gateway_error: str | None = None
    if wanted and available_groups:
        try:
            by_group = await zalo_gateway.get_group_members_batch(
                [group.zalo_group_id for group in available_groups]
            )
            membership = {
                group_id: {str(member.get("user_id") or "") for member in members}
                for group_id, members in by_group.items()
            }
            omitted = [
                group.name
                for group in available_groups
                if group.zalo_group_id not in membership
            ]
            if omitted:
                gateway_error = (
                    f"Zalo không trả về thành viên của {len(omitted)} nhóm; "
                    "các nhóm đó sẽ được bỏ qua khi áp"
                )
        except GatewayError as exc:
            # Without membership we cannot say who would be dropped, so say that
            # rather than quietly presenting an empty warning column.
            gateway_error = exc.message

    active = dict(
        (
            await db.execute(
                select(MentionFollowup.automation_id, func.count())
                .where(
                    MentionFollowup.status.in_(
                        [
                            MentionFollowupStatus.CLASSIFYING,
                            MentionFollowupStatus.PENDING,
                            MentionFollowupStatus.PROCESSING,
                        ]
                    )
                )
                .group_by(MentionFollowup.automation_id)
            )
        ).all()
    )
    automations = {
        automation.zalo_group_id: automation
        for automation in (
            await db.scalars(
                select(MentionAutomation).options(selectinload(MentionAutomation.targets))
            )
        ).all()
    }

    rows: list[BulkMentionPreviewRow] = []
    for customer, group in pairs:
        automation = automations.get(group.id)
        members = membership.get(group.zalo_group_id)
        missing = (
            sorted(
                target.display_name
                for target in [*data.targets, *data.price_targets]
                if target.user_id not in members
            )
            if members is not None
            else []
        )
        kept = {
            MentionTargetKind.MENTION: [
                target
                for target in data.targets
                if members is None or target.user_id in members
            ],
            MentionTargetKind.PRICE: [
                target
                for target in data.price_targets
                if members is None or target.user_id in members
            ],
        }
        mention_on = data.mention_tag_enabled and bool(kept[MentionTargetKind.MENTION])
        price_on = data.price_inquiry_enabled and bool(kept[MentionTargetKind.PRICE])
        if automation is None:
            raise AppError(
                "MENTION_AUTOMATION_CONFIG_MISSING",
                f"Nhóm {group.name} thiếu cấu hình tag tên tự động.",
                500,
            )
        will_change = _differs(
            automation, mention_on, price_on, data.delay_minutes, windows, kept
        )
        rows.append(
            BulkMentionPreviewRow(
                customer_id=customer.id,
                name=group.name,
                is_available=group.is_available,
                current_target_count=len(automation.targets),
                active_followups=(
                    int(active.get(automation.id, 0))
                    if will_change
                    else 0
                ),
                will_change=will_change,
                missing_members=sorted(set(missing)),
            )
        )
    return BulkMentionPreview(rows=rows, gateway_error=gateway_error)


async def apply_bulk_mention(
    db: AsyncSession, data: BulkMentionUpdate
) -> BulkMentionApplyResult:
    """Overwrite the mention config of the chosen customers.

    Overwrite is the point: this company runs the same tag setup nearly
    everywhere, and the per-customer escape hatch is unticking a row rather than
    a merge rule nobody would remember. Anyone who is not in a given group is
    dropped from that customer only — writing them in would just make the tag
    fail at send time.
    """
    if not data.customer_ids:
        raise AppError("NO_CUSTOMER_SELECTED", "Hãy chọn ít nhất một khách hàng.", 422)
    try:
        active_windows = normalize_time_windows(
            [window.model_dump() for window in data.active_windows]
        )
    except ValueError as exc:
        raise AppError("INVALID_TIME_WINDOWS", str(exc), 422) from exc

    selected = set(data.customer_ids)
    pairs = [
        (customer, group)
        for customer, group in await _selectable_customers(db)
        if customer.id in selected
    ]
    if not pairs:
        raise AppError("NO_CUSTOMER_SELECTED", "Không tìm thấy khách hàng đã chọn.", 422)

    membership: dict[str, set[str]] = {}
    available = [group for _, group in pairs if group.is_available]
    membership_required = bool(data.targets or data.price_targets)
    # Nobody to place means nothing to check. Asking the gateway anyway would
    # make switching tagging off impossible while the bot is disconnected, which
    # is exactly when somebody wants to switch it off.
    if available and (data.targets or data.price_targets):
        try:
            by_group = await zalo_gateway.get_group_members_batch(
                [group.zalo_group_id for group in available]
            )
            membership = {
                group_id: {str(member.get("user_id") or "") for member in members}
                for group_id, members in by_group.items()
            }
        except GatewayError as exc:
            raise AppError(exc.code, exc.message, exc.status_code) from exc

    now = datetime.now(UTC)
    automations = {
        automation.zalo_group_id: automation
        for automation in (
            await db.scalars(
                select(MentionAutomation)
                .options(selectinload(MentionAutomation.targets))
                .where(
                    MentionAutomation.zalo_group_id.in_([group.id for _, group in pairs])
                )
                .with_for_update()
            )
        ).all()
    }

    updated = cancelled = unchanged = 0
    skipped: list[str] = []
    dropped: dict[str, int] = {}
    for _customer, group in pairs:
        if not group.is_available:
            skipped.append(group.name)
            continue
        members = membership.get(group.zalo_group_id)
        if membership_required and members is None:
            # A locally available group can still be omitted by Zalo's batch
            # response. Writing unverified users there creates a configuration
            # that later fails every send, so leave that group untouched.
            skipped.append(group.name)
            continue
        kept: dict[MentionTargetKind, list] = {}
        # Per customer, and by name: somebody listed for both features who is
        # absent from this group is one missing person here, not two.
        missing_here: set[str] = set()
        for kind, entries in (
            (MentionTargetKind.MENTION, data.targets),
            (MentionTargetKind.PRICE, data.price_targets),
        ):
            usable = []
            for target in entries:
                if members is None or target.user_id in members:
                    usable.append(target)
                else:
                    missing_here.add(target.display_name)
            kept[kind] = usable

        mention_on = data.mention_tag_enabled and bool(kept[MentionTargetKind.MENTION])
        price_on = data.price_inquiry_enabled and bool(kept[MentionTargetKind.PRICE])
        # Asking for both features off is a request to disable tagging, so write
        # it. Skipping is only for a customer where the chosen people cannot be
        # tagged at all, which would leave an automation that can never fire.
        turning_off = not data.mention_tag_enabled and not data.price_inquiry_enabled
        if not mention_on and not price_on and not turning_off:
            # Nothing left to tag with here; leave the customer untouched rather
            # than writing an automation that can never fire. Its dropped names
            # are not counted either — nothing was written to drop them from.
            skipped.append(group.name)
            continue
        for name in missing_here:
            dropped[name] = dropped.get(name, 0) + 1

        automation = automations.get(group.id)
        if automation is None:
            raise AppError(
                "MENTION_AUTOMATION_CONFIG_MISSING",
                f"Nhóm {group.name} thiếu cấu hình tag tên tự động.",
                500,
            )
        if not _differs(
            automation, mention_on, price_on, data.delay_minutes, active_windows, kept
        ):
            # Rewriting an identical configuration would cancel every reminder
            # already running in this group for nothing. The per-customer form
            # has always guarded this; the bulk one has to as well.
            unchanged += 1
            continue

        await db.execute(
            delete(MentionTarget).where(MentionTarget.automation_id == automation.id)
        )
        cancelled += await reconcile_followups(
            db,
            automation.id,
            allowed={
                MentionFollowupTrigger.MENTION: (
                    {t.user_id for t in kept[MentionTargetKind.MENTION]}
                    if mention_on
                    else set()
                ),
                MentionFollowupTrigger.PRICE_INQUIRY: (
                    {t.user_id for t in kept[MentionTargetKind.PRICE]}
                    if price_on
                    else set()
                ),
            },
            now=now,
        )
        updated += 1

        automation.mention_tag_enabled = mention_on
        automation.price_inquiry_enabled = price_on
        automation.enabled = mention_on or price_on
        automation.delay_minutes = data.delay_minutes
        automation.active_windows = active_windows
        for kind, entries in kept.items():
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
    logger.info(
        "MENTION_BULK_APPLIED updated=%d created=%d unchanged=%d skipped=%d"
        " cancelled_followups=%d",
        updated,
        0,
        unchanged,
        len(skipped),
        cancelled,
    )
    return BulkMentionApplyResult(
        updated=updated,
        created=0,
        unchanged=unchanged,
        skipped=sorted(skipped),
        cancelled_followups=cancelled,
        dropped_members={name: count for name, count in sorted(dropped.items())},
    )


def _differs(
    automation: MentionAutomation,
    mention_on: bool,
    price_on: bool,
    delay_minutes: int,
    active_windows: list[dict[str, str]],
    kept: dict[MentionTargetKind, list],
) -> bool:
    """Whether writing this configuration would actually change anything."""
    if (
        automation.mention_tag_enabled != mention_on
        or automation.price_inquiry_enabled != price_on
        or automation.delay_minutes != delay_minutes
        or automation.active_windows != active_windows
    ):
        return True
    for kind, entries in kept.items():
        current = {
            target.zalo_user_id for target in automation.targets if target.kind == kind
        }
        if current != {target.user_id for target in entries}:
            return True
    return False
