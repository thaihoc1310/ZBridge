from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import ZaloAccount, ZaloGroup
from app.services import group_service


async def test_group_sync_rejects_empty_snapshot_and_requires_three_misses(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def connected():
        return {"status": "CONNECTED", "zalo_user_id": "bot-1"}

    snapshots: list[list[dict[str, object]]] = [[]]

    async def groups():
        return snapshots.pop(0)

    monkeypatch.setattr(group_service.zalo_gateway, "get_status", connected)
    monkeypatch.setattr(group_service.zalo_gateway, "get_groups", groups)

    async with session_factory() as db:
        account = ZaloAccount(zalo_user_id="bot-1")
        db.add(account)
        await db.flush()
        kept = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="kept",
            name="Nhóm còn lại",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        missing = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="missing",
            name="Nhóm tạm thiếu",
            member_count=2,
            is_available=True,
            last_synced_at=datetime.now(UTC),
        )
        db.add_all([kept, missing])
        await db.commit()

        with pytest.raises(AppError) as empty:
            await group_service.sync_groups(db)
        assert empty.value.code == "GROUP_SYNC_INCOMPLETE"
        await db.refresh(missing)
        assert missing.is_available is True
        assert missing.missing_sync_count == 0

        visible = [
            {
                "group_id": "kept",
                "name": "Nhóm còn lại",
                "member_count": 2,
                "avatar_url": None,
            }
        ]
        snapshots.extend([visible, visible, visible])
        for expected_count in (1, 2):
            result = await group_service.sync_groups(db)
            assert result.unavailable == 0
            await db.refresh(missing)
            assert missing.is_available is True
            assert missing.missing_sync_count == expected_count

        result = await group_service.sync_groups(db)
        assert result.unavailable == 1
        await db.refresh(missing)
        assert missing.is_available is False

    await engine.dispose()
