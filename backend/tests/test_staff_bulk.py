from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import (
    Customer,
    MentionAutomation,
    MentionFollowup,
    MentionTarget,
    MentionTargetKind,
    StaffMember,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import MentionFollowupStatus
from app.schemas.api import (
    BulkMentionUpdate,
    MentionTargetInput,
    MentionTimeWindow,
    StaffMemberInput,
    StaffRosterUpdate,
)
from app.services import staff_service

KETOAN = MentionTargetInput(user_id="u-ketoan", display_name="Ngọc Anh")
SALES = MentionTargetInput(user_id="u-sales", display_name="Thu Hà")

#: "kho" deliberately has no sales person, to exercise the drop path.
MEMBERS = {
    "g-hoaphat": [{"user_id": "u-ketoan"}, {"user_id": "u-sales"}, {"user_id": "u-khach"}],
    "g-kho": [{"user_id": "u-ketoan"}, {"user_id": "u-khach"}],
}


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        specs = [
            ("g-hoaphat", "Cty Hoà Phát", True, True),
            ("g-kho", "Kho Long Biên", True, False),
            ("g-cu", "Cty Tân Á", False, False),
        ]
        for zalo_group_id, name, available, with_automation in specs:
            group = ZaloGroup(
                zalo_account_id=account.id,
                zalo_group_id=zalo_group_id,
                name=name,
                member_count=5,
                is_available=available,
                last_synced_at=datetime.now(UTC),
            )
            db.add(group)
            await db.flush()
            db.add(Customer(zalo_group_id=group.id))
            automation = MentionAutomation(
                zalo_group_id=group.id,
                enabled=with_automation,
                mention_tag_enabled=with_automation,
                price_inquiry_enabled=False,
                delay_minutes=45,
                active_windows=[{"start": "09:00", "end": "17:00"}],
            )
            db.add(automation)
            await db.flush()
            if not with_automation:
                continue
            db.add(
                MentionTarget(
                    automation_id=automation.id,
                    zalo_user_id="u-cu",
                    display_name="Người cũ",
                    kind=MentionTargetKind.MENTION,
                )
            )
            db.add(
                MentionFollowup(
                    automation_id=automation.id,
                    source_message_id="m-dang-cho",
                    target_user_ids=["u-cu"],
                    target_display_names=["Người cũ"],
                    due_at=datetime.now(UTC),
                    status=MentionFollowupStatus.PENDING,
                )
            )
        await db.commit()
    return engine, sessions


def _stub_gateway(monkeypatch, members=None, fail: bool = False):
    async def batch(group_ids):
        if fail:
            from app.services.zalo_gateway_client import GatewayError

            raise GatewayError("GATEWAY_DOWN", "Bot chưa kết nối.", 503)
        source = MEMBERS if members is None else members
        return {gid: source[gid] for gid in group_ids if gid in source}

    monkeypatch.setattr(staff_service.zalo_gateway, "get_group_members_batch", batch)


def _payload(customer_ids, **overrides) -> BulkMentionUpdate:
    body = {
        "mention_tag_enabled": True,
        "price_inquiry_enabled": True,
        "delay_minutes": 120,
        "active_windows": [MentionTimeWindow(start="08:00", end="18:00")],
        "targets": [KETOAN],
        "price_targets": [SALES],
        "customer_ids": list(customer_ids),
    }
    body.update(overrides)
    return BulkMentionUpdate(**body)


async def _customer_ids(db) -> dict[str, object]:
    rows = (
        await db.execute(
            select(ZaloGroup.zalo_group_id, Customer.id).join(
                Customer, Customer.zalo_group_id == ZaloGroup.id
            )
        )
    ).all()
    return {zalo_group_id: customer_id for zalo_group_id, customer_id in rows}


async def test_roster_reports_how_many_customers_use_each_person(monkeypatch) -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        await staff_service.save_staff(
            db,
            StaffRosterUpdate(
                members=[
                    StaffMemberInput(user_id="u-ketoan", display_name="Ngọc Anh"),
                    StaffMemberInput(user_id="u-sales", display_name="Thu Hà"),
                ]
            ),
        )
        _stub_gateway(monkeypatch)
        ids = await _customer_ids(db)
        await staff_service.apply_bulk_mention(
            db, _payload([ids["g-hoaphat"], ids["g-kho"]])
        )
        roster = {member.user_id: member for member in await staff_service.list_staff(db)}
        # Ngọc Anh is in both groups; Thu Hà only in Hoà Phát.
        assert roster["u-ketoan"].mention_customer_count == 2
        assert roster["u-sales"].price_customer_count == 1
    await engine.dispose()


async def test_preview_reports_what_apply_would_disturb(monkeypatch) -> None:
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        preview = await staff_service.preview_bulk_mention(db, _payload(list(ids.values())))
        rows = {row.name: row for row in preview.rows}
        assert preview.gateway_error is None
        hoaphat = rows["Cty Hoà Phát"]
        assert hoaphat.current_target_count == 1
        assert hoaphat.active_followups == 1
        assert hoaphat.missing_members == []
        # Thu Hà is not in the warehouse group, and the UI must say so up front.
        assert rows["Kho Long Biên"].missing_members == ["Thu Hà"]
        assert rows["Kho Long Biên"].current_target_count == 0
        assert rows["Cty Tân Á"].is_available is False
    await engine.dispose()


async def test_apply_overwrites_creates_and_drops_non_members(monkeypatch) -> None:
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(db, _payload(list(ids.values())))

        assert result.updated == 2 and result.created == 0
        assert result.skipped == ["Cty Tân Á"]
        assert result.cancelled_followups == 1
        assert result.dropped_members == {"Thu Hà": 1}

    async with sessions() as db:
        automations = {
            group.zalo_group_id: automation
            for automation, group in (
                await db.execute(
                    select(MentionAutomation, ZaloGroup).join(
                        ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id
                    )
                )
            ).all()
        }
        hoaphat = automations["g-hoaphat"]
        targets = (
            await db.scalars(
                select(MentionTarget).where(MentionTarget.automation_id == hoaphat.id)
            )
        ).all()
        # Overwrite: the previous target is gone rather than merged with.
        assert sorted(t.zalo_user_id for t in targets) == ["u-ketoan", "u-sales"]
        assert hoaphat.delay_minutes == 120
        assert hoaphat.price_inquiry_enabled is True

        kho = automations["g-kho"]
        kho_targets = (
            await db.scalars(
                select(MentionTarget).where(MentionTarget.automation_id == kho.id)
            )
        ).all()
        assert [t.zalo_user_id for t in kho_targets] == ["u-ketoan"]
        # Nobody left to quote with here, so that half stays off.
        assert kho.price_inquiry_enabled is False
        assert kho.mention_tag_enabled is True

        followup = await db.scalar(select(MentionFollowup))
        assert followup.status == MentionFollowupStatus.CANCELLED

        assert automations["g-cu"].enabled is False
    await engine.dispose()


async def test_apply_refuses_when_membership_cannot_be_read(monkeypatch) -> None:
    """Dropping non-members is the promise; without the member list we cannot keep it."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch, fail=True)
    async with sessions() as db:
        ids = await _customer_ids(db)
        with pytest.raises(AppError) as error:
            await staff_service.apply_bulk_mention(db, _payload([ids["g-hoaphat"]]))
        assert error.value.code == "GATEWAY_DOWN"
    await engine.dispose()


async def test_a_group_missing_from_the_batch_is_left_untouched(monkeypatch) -> None:
    """A partial Zalo response must not write targets we could not verify."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch, members={"g-kho": MEMBERS["g-kho"]})
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(
            db, _payload([ids["g-hoaphat"], ids["g-kho"]])
        )
        assert result.dropped_members == {"Thu Hà": 1}
        assert result.skipped == ["Cty Hoà Phát"]

    async with sessions() as db:
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        targets = (
            await db.scalars(
                select(MentionTarget).where(MentionTarget.automation_id == automation.id)
            )
        ).all()
        assert sorted(t.zalo_user_id for t in targets) == ["u-cu"]
    await engine.dispose()


async def test_apply_needs_at_least_one_customer() -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        with pytest.raises(AppError) as error:
            await staff_service.apply_bulk_mention(db, _payload([]))
        assert error.value.code == "NO_CUSTOMER_SELECTED"
    await engine.dispose()


async def test_roster_rejects_duplicates() -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        with pytest.raises(AppError) as error:
            await staff_service.save_staff(
                db,
                StaffRosterUpdate(
                    members=[
                        StaffMemberInput(user_id="u-a", display_name="A"),
                        StaffMemberInput(user_id="u-a", display_name="A lần hai"),
                    ]
                ),
            )
        assert error.value.code == "DUPLICATE_STAFF"
        assert await db.scalar(select(StaffMember)) is None
    await engine.dispose()


async def test_one_absent_person_counts_once_per_customer(monkeypatch) -> None:
    """Somebody listed for both features is one missing person, not two.

    The report said "không có trong 2 nhóm" for a single group, because the
    counter sat inside the loop over the two target lists.
    """
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(
            db,
            _payload(
                [ids["g-kho"]],
                targets=[KETOAN, SALES],
                price_targets=[SALES],
            ),
        )
        # Thu Hà is absent from the one warehouse group, on both lists.
        assert result.dropped_members == {"Thu Hà": 1}
        assert result.updated == 1 and result.created == 0
    await engine.dispose()


async def test_a_skipped_customer_does_not_count_as_a_drop(monkeypatch) -> None:
    """Nothing was written there, so nothing was dropped from it."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(
            db,
            _payload(
                [ids["g-kho"]],
                mention_tag_enabled=True,
                price_inquiry_enabled=False,
                targets=[SALES],
                price_targets=[],
            ),
        )
        # Only Thu Hà was listed and she is not in that group, so it is skipped
        # whole and must not also be reported as a place she was dropped from.
        assert result.skipped == ["Kho Long Biên"]
        assert result.updated == 0 and result.created == 0
        assert result.dropped_members == {}
    await engine.dispose()


async def test_turning_both_features_off_is_written_not_skipped(monkeypatch) -> None:
    """Switching tagging off everywhere is an instruction, not an empty change."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(
            db,
            _payload(
                [ids["g-hoaphat"]],
                mention_tag_enabled=False,
                price_inquiry_enabled=False,
                targets=[],
                price_targets=[],
            ),
        )
        assert result.updated == 1 and result.skipped == []

    async with sessions() as db:
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        assert automation.mention_tag_enabled is False
        assert automation.price_inquiry_enabled is False
        # The scheduler and classifier still read this one field.
        assert automation.enabled is False
        assert (
            await db.scalar(
                select(MentionTarget).where(MentionTarget.automation_id == automation.id)
            )
        ) is None
    await engine.dispose()


async def test_turning_tagging_off_works_while_the_bot_is_down(monkeypatch) -> None:
    """No targets means no membership to verify, so a dead gateway must not block it."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch, fail=True)
    async with sessions() as db:
        ids = await _customer_ids(db)
        result = await staff_service.apply_bulk_mention(
            db,
            _payload(
                [ids["g-hoaphat"]],
                mention_tag_enabled=False,
                price_inquiry_enabled=False,
                targets=[],
                price_targets=[],
            ),
        )
        assert result.updated == 1

    async with sessions() as db:
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        assert automation.enabled is False
    await engine.dispose()


async def test_reapplying_the_same_config_keeps_running_reminders(monkeypatch) -> None:
    """An engineer mid-reminder must not lose it to an identical bulk apply.

    The per-customer form has always compared before cancelling. The bulk one
    rewrote unconditionally, so pushing the same setup to every customer wiped
    every reminder in flight.
    """
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        payload = _payload([ids["g-hoaphat"]])
        first = await staff_service.apply_bulk_mention(db, payload)
        assert first.updated == 1 and first.cancelled_followups == 1

    # A reminder starts running under the configuration that was just written.
    async with sessions() as db:
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        db.add(
            MentionFollowup(
                automation_id=automation.id,
                source_message_id="m-engineer",
                target_user_ids=["u-ketoan"],
                target_display_names=["Ngọc Anh"],
                due_at=datetime.now(UTC),
                status=MentionFollowupStatus.PENDING,
            )
        )
        await db.commit()

    async with sessions() as db:
        ids = await _customer_ids(db)
        preview = await staff_service.preview_bulk_mention(
            db, _payload([ids["g-hoaphat"]])
        )
        row = next(r for r in preview.rows if r.name == "Cty Hoà Phát")
        assert row.will_change is False
        assert row.active_followups == 0, "không đổi gì thì không huỷ vòng nhắc nào"

        again = await staff_service.apply_bulk_mention(db, _payload([ids["g-hoaphat"]]))
        assert again.unchanged == 1
        assert again.updated == 0 and again.cancelled_followups == 0

    async with sessions() as db:
        followup = await db.scalar(
            select(MentionFollowup).where(
                MentionFollowup.source_message_id == "m-engineer"
            )
        )
        assert followup.status == MentionFollowupStatus.PENDING
    await engine.dispose()


@pytest.mark.parametrize(
    ("label", "override", "survives"),
    [
        ("không đổi gì", {}, True),
        ("xoá một người khác", {"targets": [KETOAN]}, True),
        (
            "thêm người khác vào báo giá",
            {"price_inquiry_enabled": True, "price_targets": [SALES]},
            True,
        ),
        ("đổi thời gian chờ", {"delay_minutes": 60}, True),
        (
            "đổi khung giờ",
            {"active_windows": [MentionTimeWindow(start="08:00", end="17:00")]},
            True,
        ),
        ("xoá chính người đó", {"targets": [SALES]}, False),
        (
            "tắt hết",
            {
                "mention_tag_enabled": False,
                "price_inquiry_enabled": False,
                "targets": [],
                "price_targets": [],
            },
            False,
        ),
    ],
)
async def test_bulk_apply_ends_only_the_reminders_it_should(
    monkeypatch, label: str, override: dict, survives: bool
) -> None:
    """The bulk path must prune reminders exactly like the per-customer form."""
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        ids = await _customer_ids(db)
        await staff_service.apply_bulk_mention(
            db, _payload([ids["g-hoaphat"]], targets=[KETOAN, SALES], price_targets=[])
        )
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        await db.execute(delete(MentionFollowup))
        db.add(
            MentionFollowup(
                automation_id=automation.id,
                source_message_id="m-running",
                target_user_ids=["u-ketoan"],
                target_display_names=["Ngọc Anh"],
                due_at=datetime.now(UTC),
                status=MentionFollowupStatus.PENDING,
            )
        )
        await db.commit()

        base = {"targets": [KETOAN, SALES], "price_targets": []}
        await staff_service.apply_bulk_mention(
            db, _payload([ids["g-hoaphat"]], **{**base, **override})
        )
        followup = await db.scalar(
            select(MentionFollowup).where(
                MentionFollowup.source_message_id == "m-running"
            )
        )
        expected = (
            MentionFollowupStatus.PENDING if survives else MentionFollowupStatus.CANCELLED
        )
        assert followup.status == expected, label
    await engine.dispose()


async def test_roster_counts_only_where_tagging_is_actually_on(monkeypatch) -> None:
    """A name left behind in a switched-off customer is tagging nobody.

    The roster read "Nhắc việc: 1 khách hàng" for somebody whose only customer
    had the feature turned off, which describes a reminder that never happens.
    """
    engine, sessions = await _database()
    _stub_gateway(monkeypatch)
    async with sessions() as db:
        await staff_service.save_staff(
            db,
            StaffRosterUpdate(
                members=[StaffMemberInput(user_id="u-ketoan", display_name="Ngọc Anh")]
            ),
        )
        ids = await _customer_ids(db)
        await staff_service.apply_bulk_mention(
            db, _payload([ids["g-hoaphat"]], targets=[KETOAN], price_targets=[])
        )
        roster = {member.user_id: member for member in await staff_service.list_staff(db)}
        assert roster["u-ketoan"].mention_customer_count == 1

        # Switch the feature off; the target row stays but nothing is tagged.
        automation = await db.scalar(
            select(MentionAutomation)
            .join(ZaloGroup, ZaloGroup.id == MentionAutomation.zalo_group_id)
            .where(ZaloGroup.zalo_group_id == "g-hoaphat")
        )
        automation.mention_tag_enabled = False
        automation.enabled = False
        await db.commit()

        roster = {member.user_id: member for member in await staff_service.list_staff(db)}
        assert roster["u-ketoan"].mention_customer_count == 0
        assert (
            await db.scalar(
                select(func.count())
                .select_from(MentionTarget)
                .where(MentionTarget.automation_id == automation.id)
            )
        ) == 1, "hàng target vẫn còn, chỉ là không được tính"
    await engine.dispose()
