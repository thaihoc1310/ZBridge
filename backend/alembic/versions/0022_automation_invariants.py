"""Create automation invariants and remove the debt enable switch.

Revision ID: 0022_automation_invariants
Revises: 0021_google_drive_oauth
"""

import calendar
import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision = "0022_automation_invariants"
down_revision = "0021_google_drive_oauth"
branch_labels = None
depends_on = None

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_MESSAGE_PARTS = [
    {"type": "text", "text": "Vui lòng thanh toán công nợ giúp mình nhé."}
]
DEFAULT_WINDOWS = [
    {"start": "08:00", "end": "12:00"},
    {"start": "14:00", "end": "18:00"},
]


def _next_monthly_run(day_of_month: int, send_time: time, now: datetime) -> datetime:
    local_now = now.astimezone(LOCAL_TIMEZONE)
    year, month = local_now.year, local_now.month
    for _ in range(2):
        candidate = datetime.combine(
            date(
                year,
                month,
                min(day_of_month, calendar.monthrange(year, month)[1]),
            ),
            send_time,
            tzinfo=LOCAL_TIMEZONE,
        )
        if candidate > local_now:
            return candidate.astimezone(UTC)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    raise RuntimeError("Could not calculate debt reminder backfill schedule")


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)

    missing_customer_groups = bind.execute(
        sa.text(
            """
            SELECT zg.id
            FROM zalo_groups AS zg
            LEFT JOIN customers AS c ON c.zalo_group_id = zg.id
            WHERE c.id IS NULL
            """
        )
    ).scalars()
    for group_id in missing_customer_groups:
        bind.execute(
            sa.text(
                """
                INSERT INTO customers
                    (id, zalo_group_id, has_debt, created_at, updated_at)
                VALUES
                    (:id, :group_id, false, :now, :now)
                """
            ),
            {"id": group_id, "group_id": group_id, "now": now},
        )

    missing_debt_customers = bind.execute(
        sa.text(
            """
            SELECT c.id, c.has_debt, c.debt_file_url
            FROM customers AS c
            LEFT JOIN debt_reminder_automations AS dra ON dra.customer_id = c.id
            WHERE dra.id IS NULL
            """
        )
    ).mappings()
    for customer in missing_debt_customers:
        runnable = bool(customer["has_debt"] and customer["debt_file_url"])
        insert_debt = sa.text(
            """
            INSERT INTO debt_reminder_automations
                (id, customer_id, enabled, day_of_month, repeat_interval_days,
                 send_time, message_parts, next_run_at, created_at, updated_at)
            VALUES
                (:id, :customer_id, true, 25, 3, :send_time,
                 :message_parts, :next_run_at, :now, :now)
            """
        ).bindparams(sa.bindparam("message_parts", type_=sa.JSON()))
        bind.execute(
            insert_debt,
            {
                "id": uuid.uuid4(),
                "customer_id": customer["id"],
                "send_time": time(9, 0),
                "message_parts": DEFAULT_MESSAGE_PARTS,
                "next_run_at": (
                    _next_monthly_run(25, time(9, 0), now) if runnable else None
                ),
                "now": now,
            },
        )

    missing_mention_groups = bind.execute(
        sa.text(
            """
            SELECT zg.id
            FROM zalo_groups AS zg
            LEFT JOIN mention_automations AS ma ON ma.zalo_group_id = zg.id
            WHERE ma.id IS NULL
            """
        )
    ).scalars()
    for group_id in missing_mention_groups:
        insert_mention = sa.text(
            """
            INSERT INTO mention_automations
                (id, zalo_group_id, enabled, mention_tag_enabled,
                 price_inquiry_enabled, delay_minutes, active_windows,
                 created_at, updated_at)
            VALUES
                (:id, :group_id, false, false, false, 120,
                 :active_windows, :now, :now)
            """
        ).bindparams(sa.bindparam("active_windows", type_=sa.JSON()))
        bind.execute(
            insert_mention,
            {
                "id": uuid.uuid4(),
                "group_id": group_id,
                "active_windows": DEFAULT_WINDOWS,
                "now": now,
            },
        )

    # From this revision onward the scheduler only schedules work. Repair all
    # legacy rows once here so no existing customer is left dependent on the
    # removed runtime self-healing path.
    debt_states = bind.execute(
        sa.text(
            """
            SELECT dra.id, dra.day_of_month, dra.send_time, dra.next_run_at,
                   c.has_debt, c.debt_file_url
            FROM debt_reminder_automations AS dra
            JOIN customers AS c ON c.id = dra.customer_id
            """
        )
    ).mappings()
    inactive_automation_ids: list[uuid.UUID] = []
    for state in debt_states:
        runnable = bool(state["has_debt"] and state["debt_file_url"])
        if runnable and state["next_run_at"] is None:
            bind.execute(
                sa.text(
                    """
                    UPDATE debt_reminder_automations
                    SET next_run_at = :next_run_at, updated_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "id": state["id"],
                    "next_run_at": _next_monthly_run(
                        int(state["day_of_month"]), state["send_time"], now
                    ),
                    "now": now,
                },
            )
        elif not runnable:
            inactive_automation_ids.append(state["id"])
            if state["next_run_at"] is not None:
                bind.execute(
                    sa.text(
                        """
                        UPDATE debt_reminder_automations
                        SET next_run_at = NULL, updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {"id": state["id"], "now": now},
                )

    if inactive_automation_ids:
        bind.execute(
            sa.text(
                """
                UPDATE debt_reminder_runs
                SET status = 'CANCELLED', claimed_at = NULL,
                    processed_at = :now, updated_at = :now,
                    error_message = :reason
                WHERE automation_id IN :automation_ids
                  AND status IN ('PENDING', 'PROCESSING')
                """
            ).bindparams(
                sa.bindparam("automation_ids", expanding=True),
            ),
            {
                "automation_ids": inactive_automation_ids,
                "now": now,
                "reason": "Nhắc công nợ tạm dừng theo trạng thái khách hàng.",
            },
        )

    # `enabled` is a persisted optimization used by existing classifier and
    # scheduler code, so keep it derived from the two actual feature switches.
    bind.execute(
        sa.text(
            """
            UPDATE mention_automations
            SET enabled = (mention_tag_enabled OR price_inquiry_enabled),
                updated_at = :now
            WHERE enabled IS DISTINCT FROM
                  (mention_tag_enabled OR price_inquiry_enabled)
            """
        ),
        {"now": now},
    )

    op.drop_column("debt_reminder_automations", "enabled")


def downgrade() -> None:
    op.add_column(
        "debt_reminder_automations",
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
