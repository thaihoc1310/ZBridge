"""Fill a development database with data that exercises the mention features.

Shaped around the case the bulk editor exists for: a handful of staff — an
accountant, two engineers, a sales lead — spread across most groups, so adding,
swapping or removing one of them is a change worth making in one go.

    docker compose exec -T backend python -m scripts.seed_dev
    docker compose exec -T backend python -m scripts.seed_dev --reset
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.config import settings
from app.db.database import SessionLocal
from app.models import (
    Customer,
    DebtReminderAutomation,
    MentionAutomation,
    MentionContextMessage,
    MentionFollowup,
    MentionTarget,
    MentionTargetKind,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import BotStatus, MentionFollowupStatus, MentionFollowupTrigger

STAFF = {
    "ketoan": ("u-ketoan", "Ngọc Anh (Kế toán)"),
    "engineer1": ("u-eng-1", "Tuấn Anh (Kỹ thuật)"),
    "engineer2": ("u-eng-2", "Bảo Long (Kỹ thuật)"),
    "sales": ("u-sales", "Thu Hà (Sales)"),
    "sales2": ("u-sales-2", "Minh Quân (Sales)"),
}

#: (tên nhóm, số thành viên, còn nợ, ghi chú, người tag nhắc việc, người báo giá)
GROUPS: list[tuple[str, int, bool, str | None, list[str], list[str]]] = [
    ("Cty Minh Long - Dự án A", 12, True, "Thanh toán chậm 2 kỳ.",
     ["ketoan", "engineer1"], ["sales"]),
    ("Cty Hoà Phát - Vật tư", 24, False, None,
     ["ketoan", "engineer1", "engineer2"], ["sales", "sales2"]),
    ("Xưởng Bắc Ninh - Bảo trì", 8, False, "Chỉ liên hệ trong giờ hành chính.",
     ["engineer2"], []),
    ("Cty Đại Việt - Đơn hàng 2026", 17, True, None,
     ["ketoan", "engineer2"], ["sales2"]),
    ("Nhà thầu Sông Đà - Thi công", 31, False, None,
     ["engineer1", "engineer2"], ["sales"]),
    ("Cty An Phát - Báo giá mới", 6, False, "Khách mới, đang chờ báo giá.",
     [], ["sales", "sales2"]),
    ("Kho Long Biên - Điều phối", 9, False, None,
     ["ketoan"], []),
    ("Cty Tân Á - Hết hợp đồng", 5, False, "Nhóm cũ, đã ngừng hợp tác.",
     ["ketoan"], []),
]

WINDOWS = [{"start": "08:00", "end": "12:00"}, {"start": "13:30", "end": "18:00"}]


async def reset(db) -> None:
    for model in (
        MentionFollowup,
        MentionContextMessage,
        MentionTarget,
        MentionAutomation,
        Customer,
        ZaloGroup,
    ):
        await db.execute(delete(model))
    await db.flush()


async def seed(reset_first: bool) -> None:
    if settings.environment == "production":
        sys.exit("Từ chối chạy: ENVIRONMENT=production.")

    now = datetime.now(UTC)
    async with SessionLocal() as db:
        if reset_first:
            await reset(db)

        account = await db.scalar(select(ZaloAccount))
        if account is None:
            account = ZaloAccount(
                zalo_user_id="u-bot", display_name="ZBridge Bot", status=BotStatus.CONNECTED
            )
            db.add(account)
            await db.flush()

        created = 0
        for index, (name, members, has_debt, note, tag_staff, price_staff) in enumerate(
            GROUPS
        ):
            zalo_group_id = f"seed-group-{index + 1}"
            group = await db.scalar(
                select(ZaloGroup).where(ZaloGroup.zalo_group_id == zalo_group_id)
            )
            if group is not None:
                continue
            unavailable = name.endswith("Hết hợp đồng")
            group = ZaloGroup(
                zalo_account_id=account.id,
                zalo_group_id=zalo_group_id,
                name=name,
                member_count=members,
                is_available=not unavailable,
                last_synced_at=now - timedelta(minutes=index * 7),
            )
            db.add(group)
            await db.flush()
            db.add(
                Customer(
                    id=group.id,
                    zalo_group_id=group.id,
                    has_debt=has_debt,
                    note=note,
                    last_debt_paid_at=None if has_debt else now - timedelta(days=index + 3),
                )
            )
            db.add(DebtReminderAutomation(customer_id=group.id, next_run_at=None))
            if not tag_staff and not price_staff:
                db.add(
                    MentionAutomation(
                        zalo_group_id=group.id,
                        enabled=False,
                        mention_tag_enabled=False,
                        price_inquiry_enabled=False,
                    )
                )
                created += 1
                continue

            automation = MentionAutomation(
                zalo_group_id=group.id,
                enabled=True,
                mention_tag_enabled=bool(tag_staff),
                price_inquiry_enabled=bool(price_staff),
                delay_minutes=120 if index % 2 else 30,
                active_windows=WINDOWS,
            )
            db.add(automation)
            await db.flush()
            for kind, keys in (
                (MentionTargetKind.MENTION, tag_staff),
                (MentionTargetKind.PRICE, price_staff),
            ):
                for key in keys:
                    user_id, display_name = STAFF[key]
                    db.add(
                        MentionTarget(
                            automation_id=automation.id,
                            zalo_user_id=user_id,
                            display_name=display_name,
                            kind=kind,
                        )
                    )
            created += 1

        await db.commit()

    async with SessionLocal() as db:
        await _seed_history(db, now)
        await db.commit()

    print(f"Đã tạo {created} nhóm mới. Nhân sự dùng chung nhiều nhóm:")
    async with SessionLocal() as db:
        for _key, (user_id, display_name) in STAFF.items():
            rows = list(
                (
                    await db.scalars(
                        select(MentionTarget).where(MentionTarget.zalo_user_id == user_id)
                    )
                ).all()
            )
            tag = sum(1 for r in rows if r.kind == MentionTargetKind.MENTION)
            price = sum(1 for r in rows if r.kind == MentionTargetKind.PRICE)
            print(f"  {display_name:26s} tag nhắc việc: {tag} nhóm | báo giá: {price} nhóm")


async def _seed_history(db, now: datetime) -> None:
    """A couple of follow-ups so the list and the status badges are not empty."""
    automation = await db.scalar(
        select(MentionAutomation).join(ZaloGroup).order_by(ZaloGroup.name).limit(1)
    )
    if automation is None:
        return
    if await db.scalar(select(MentionFollowup.id).limit(1)):
        return
    samples = [
        ("seed-msg-1", "u-sales", "Thu Hà (Sales)", MentionFollowupTrigger.PRICE_INQUIRY,
         MentionFollowupStatus.SENT, "Báo giá cho anh lô hàng tháng 9 với"),
        ("seed-msg-2", "u-ketoan", "Ngọc Anh (Kế toán)", MentionFollowupTrigger.MENTION,
         MentionFollowupStatus.PENDING, "<MENTION:T1> đối chiếu công nợ giúp anh nhé"),
        ("seed-msg-3", "u-eng-1", "Tuấn Anh (Kỹ thuật)", MentionFollowupTrigger.MENTION,
         MentionFollowupStatus.SKIPPED, "<MENTION:T1> ok em, cảm ơn nhé"),
    ]
    for offset, (message_id, user_id, display_name, trigger, status, text) in enumerate(
        samples
    ):
        sent_at = now - timedelta(hours=offset + 1)
        db.add(
            MentionContextMessage(
                automation_id=automation.id,
                message_id=message_id,
                sender_id="u-khach",
                sender_display_name="Anh Dũng (Khách)",
                content=text,
                mentions=[],
                sent_at=sent_at,
            )
        )
        db.add(
            MentionFollowup(
                automation_id=automation.id,
                source_message_id=message_id,
                source_sender_id="u-khach",
                trigger=trigger,
                target_user_ids=[user_id],
                target_display_names=[display_name],
                due_at=now + timedelta(minutes=30),
                status=status,
                processed_at=now if status != MentionFollowupStatus.PENDING else None,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Xoá dữ liệu mẫu cũ trước")
    asyncio.run(seed(parser.parse_args().reset))
