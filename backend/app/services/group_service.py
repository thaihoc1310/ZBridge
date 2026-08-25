import logging
import uuid
from datetime import UTC, datetime, time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionFollowup,
    ZaloGroup,
)
from app.models.entities import BotStatus, DebtReminderStatus, MentionFollowupStatus
from app.schemas.api import SyncResponse
from app.services.bot_service import get_or_create_account
from app.services.debt_reminder_service import next_monthly_run
from app.services.zalo_gateway_client import GatewayError, zalo_gateway

logger = logging.getLogger("zbridge.groups")
MISSING_SYNCS_BEFORE_UNAVAILABLE = 3


async def get_group(db: AsyncSession, group_id: uuid.UUID) -> ZaloGroup:
    group = await db.get(ZaloGroup, group_id)
    if not group:
        raise AppError("GROUP_NOT_FOUND", "Không tìm thấy nhóm Zalo.", 404)
    return group


async def sync_groups(db: AsyncSession) -> SyncResponse:
    logger.info("GROUP_SYNC_STARTED")
    account = await get_or_create_account(db)
    try:
        status = await zalo_gateway.get_status()
        if status.get("status") != BotStatus.CONNECTED.value:
            raise AppError("BOT_DISCONNECTED", "Bot đang ngoại tuyến. Hãy kết nối lại bot.", 409)
        remote_groups = await zalo_gateway.get_groups()
    except GatewayError as exc:
        raise AppError(exc.code, exc.message, exc.status_code) from exc

    now = datetime.now(UTC)
    existing = {
        group.zalo_group_id: group
        for group in (
            await db.scalars(
                select(ZaloGroup)
                .where(ZaloGroup.zalo_account_id == account.id)
                .with_for_update()
            )
        ).all()
    }
    if existing and not remote_groups:
        raise AppError(
            "GROUP_SYNC_INCOMPLETE",
            "Zalo trả về danh sách nhóm rỗng; hệ thống giữ nguyên dữ liệu cũ.",
            503,
        )
    seen: set[str] = set()
    inserted = updated = 0
    restored_ids: list[uuid.UUID] = []
    for remote in remote_groups:
        remote_id = str(remote["group_id"])
        seen.add(remote_id)
        group = existing.get(remote_id)
        if group is None:
            group_id = uuid.uuid4()
            db.add_all(
                [
                    ZaloGroup(
                        id=group_id,
                        zalo_account_id=account.id,
                        zalo_group_id=remote_id,
                        name=str(remote.get("name") or "Nhóm không tên"),
                        avatar_url=remote.get("avatar_url"),
                        member_count=int(remote.get("member_count") or 0),
                        is_available=True,
                        missing_sync_count=0,
                        last_synced_at=now,
                    ),
                    Customer(id=group_id, zalo_group_id=group_id),
                    DebtReminderAutomation(
                        customer_id=group_id,
                        day_of_month=25,
                        repeat_enabled=True,
                        repeat_interval_days=3,
                        send_time=time(9, 0),
                        next_run_at=None,
                    ),
                    MentionAutomation(
                        zalo_group_id=group_id,
                        enabled=False,
                        mention_tag_enabled=False,
                        price_inquiry_enabled=False,
                    ),
                ]
            )
            inserted += 1
        else:
            was_unavailable = not group.is_available
            changed = (
                group.name != str(remote.get("name") or "Nhóm không tên")
                or group.avatar_url != remote.get("avatar_url")
                or group.member_count != int(remote.get("member_count") or 0)
                or not group.is_available
            )
            group.name = str(remote.get("name") or "Nhóm không tên")
            group.avatar_url = remote.get("avatar_url")
            group.member_count = int(remote.get("member_count") or 0)
            group.is_available = True
            group.missing_sync_count = 0
            group.last_synced_at = now
            if was_unavailable:
                restored_ids.append(group.id)
            updated += int(changed)

    stale_ids: list[uuid.UUID] = []
    for remote_id, group in existing.items():
        if remote_id in seen or not group.is_available:
            continue
        group.missing_sync_count += 1
        if group.missing_sync_count >= MISSING_SYNCS_BEFORE_UNAVAILABLE:
            group.is_available = False
            stale_ids.append(group.id)
    await db.flush()

    if stale_ids:
        debt_automations = list(
            (
                await db.scalars(
                    select(DebtReminderAutomation)
                    .join(Customer)
                    .where(Customer.zalo_group_id.in_(stale_ids))
                    .with_for_update()
                )
            ).all()
        )
        debt_ids = [automation.id for automation in debt_automations]
        for automation in debt_automations:
            automation.next_run_at = None
        if debt_ids:
            await db.execute(
                update(DebtReminderRun)
                .where(
                    DebtReminderRun.automation_id.in_(debt_ids),
                    DebtReminderRun.status.in_(
                        [DebtReminderStatus.PENDING, DebtReminderStatus.PROCESSING]
                    ),
                )
                .values(
                    status=DebtReminderStatus.CANCELLED,
                    claimed_at=None,
                    processed_at=now,
                    error_message="Nhóm Zalo hiện không còn khả dụng.",
                )
            )
        mention_ids = list(
            (
                await db.scalars(
                    select(MentionAutomation.id)
                    .where(MentionAutomation.zalo_group_id.in_(stale_ids))
                    .with_for_update()
                )
            ).all()
        )
        if mention_ids:
            await db.execute(
                update(MentionFollowup)
                .where(
                    MentionFollowup.automation_id.in_(mention_ids),
                    MentionFollowup.status.in_(
                        [
                            MentionFollowupStatus.CLASSIFYING,
                            MentionFollowupStatus.PENDING,
                            MentionFollowupStatus.PROCESSING,
                        ]
                    ),
                )
                .values(
                    status=MentionFollowupStatus.CANCELLED,
                    claimed_at=None,
                    processed_at=now,
                    error_message="Nhóm Zalo hiện không còn khả dụng.",
                )
            )

    if restored_ids:
        restored_automations = list(
            (
                await db.scalars(
                    select(DebtReminderAutomation)
                    .join(Customer)
                    .where(
                        Customer.zalo_group_id.in_(restored_ids),
                        Customer.has_debt.is_(True),
                        Customer.debt_file_url.is_not(None),
                        Customer.debt_file_url != "",
                    )
                    .with_for_update()
                )
            ).all()
        )
        for automation in restored_automations:
            if automation.next_run_at is None:
                automation.next_run_at = next_monthly_run(
                    automation.day_of_month, automation.send_time, now=now
                )

    account.status = BotStatus.CONNECTED
    account.zalo_user_id = status.get("zalo_user_id") or account.zalo_user_id
    account.display_name = status.get("account_name") or account.display_name
    account.avatar_url = status.get("avatar_url") or account.avatar_url
    await db.commit()
    logger.info(
        "GROUP_SYNC_COMPLETED inserted=%d updated=%d unavailable=%d total=%d",
        inserted,
        updated,
        len(stale_ids),
        len(remote_groups),
    )
    return SyncResponse(
        inserted=inserted,
        updated=updated,
        unavailable=len(stale_ids),
        total=len(remote_groups),
        synced_at=now,
    )
