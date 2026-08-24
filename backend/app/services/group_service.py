import logging
import uuid
from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Customer, DebtReminderAutomation, MentionAutomation, ZaloGroup
from app.models.entities import BotStatus
from app.schemas.api import SyncResponse
from app.services.bot_service import get_or_create_account
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
            await db.scalars(select(ZaloGroup).where(ZaloGroup.zalo_account_id == account.id))
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
