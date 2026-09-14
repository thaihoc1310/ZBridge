"""Mark manually triggered debt reminder runs.

Revision ID: 0029_manual_debt
Revises: 0028_mention_followup_counters
"""

import sqlalchemy as sa

from alembic import op

revision = "0029_manual_debt"
down_revision = "0028_mention_followup_counters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debt_reminder_runs",
        sa.Column(
            "is_manual",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "debt_reminder_runs",
        sa.Column(
            "triggered_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "debt_reminder_runs",
        sa.Column("triggered_by_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "debt_reminder_runs",
        sa.Column("manual_request_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_debt_reminder_runs_triggered_by_user_id",
        "debt_reminder_runs",
        ["triggered_by_user_id"],
    )
    op.drop_constraint(
        "uq_debt_reminder_run_schedule",
        "debt_reminder_runs",
        type_="unique",
    )
    op.create_index(
        "uq_debt_reminder_run_schedule",
        "debt_reminder_runs",
        ["automation_id", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("NOT is_manual"),
    )
    op.create_index(
        "uq_debt_reminder_run_manual_request",
        "debt_reminder_runs",
        ["automation_id", "triggered_by_user_id", "manual_request_id"],
        unique=True,
        postgresql_where=sa.text("is_manual AND manual_request_id IS NOT NULL"),
    )
    # Old deployments should already have at most one active run per automation,
    # but normalize defensively before adding the database-level invariant.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY automation_id
                       ORDER BY
                           CASE WHEN status = 'PROCESSING' THEN 0 ELSE 1 END,
                           retry_at,
                           created_at,
                           id
                   ) AS position
            FROM debt_reminder_runs
            WHERE status IN ('PENDING', 'PROCESSING')
        )
        UPDATE debt_reminder_runs AS run
        SET status = 'CANCELLED',
            claimed_at = NULL,
            processed_at = COALESCE(run.processed_at, NOW()),
            error_message = COALESCE(
                run.error_message,
                'Đã hủy khi áp dụng ràng buộc một lượt nhắc đang hoạt động.'
            )
        FROM ranked
        WHERE run.id = ranked.id
          AND ranked.position > 1
        """
    )
    op.create_index(
        "uq_debt_reminder_runs_active_automation",
        "debt_reminder_runs",
        ["automation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'PROCESSING')"),
    )
    op.execute(
        """
        INSERT INTO permissions (id, code, name, category, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'debt_reminder:send',
            'Gửi nhắc công nợ ngay',
            'Nhắc công nợ',
            NOW(),
            NOW()
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, send_permission.id
        FROM role_permissions rp
        JOIN permissions current_permission
          ON current_permission.id = rp.permission_id
        CROSS JOIN permissions send_permission
        WHERE current_permission.code = 'debt_reminder:update'
          AND send_permission.code = 'debt_reminder:send'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code = 'debt_reminder:send'")
    op.drop_index(
        "uq_debt_reminder_run_manual_request",
        table_name="debt_reminder_runs",
    )
    op.drop_index(
        "uq_debt_reminder_runs_active_automation",
        table_name="debt_reminder_runs",
    )
    op.drop_index(
        "uq_debt_reminder_run_schedule",
        table_name="debt_reminder_runs",
    )
    op.create_unique_constraint(
        "uq_debt_reminder_run_schedule",
        "debt_reminder_runs",
        ["automation_id", "scheduled_for"],
    )
    op.drop_index(
        "ix_debt_reminder_runs_triggered_by_user_id",
        table_name="debt_reminder_runs",
    )
    op.drop_column("debt_reminder_runs", "triggered_by_email")
    op.drop_column("debt_reminder_runs", "triggered_by_user_id")
    op.drop_column("debt_reminder_runs", "manual_request_id")
    op.drop_column("debt_reminder_runs", "is_manual")
