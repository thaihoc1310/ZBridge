"""Add monthly debt reminder automation.

Revision ID: 0006_debt_reminders
Revises: 0005_remove_customer_folder_name
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_debt_reminders"
down_revision = "0005_remove_customer_folder_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debt_reminder_automations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), server_default="25", nullable=False),
        sa.Column("send_time", sa.Time(), server_default="09:00:00", nullable=False),
        sa.Column("message_parts", sa.JSON(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(
        "ix_debt_reminder_automations_customer_id",
        "debt_reminder_automations",
        ["customer_id"],
        unique=True,
    )
    op.create_index(
        "ix_debt_reminder_automations_next_run_at",
        "debt_reminder_automations",
        ["next_run_at"],
    )

    op.create_table(
        "debt_reminder_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("sheet_file_id", sa.String(255)),
        sa.Column("sheet_name", sa.String(255)),
        sa.Column("sheet_url", sa.Text()),
        sa.Column("image_message_id", sa.String(128)),
        sa.Column("link_message_id", sa.String(128)),
        sa.Column("text_message_id", sa.String(128)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["debt_reminder_automations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id", "scheduled_for", name="uq_debt_reminder_run_schedule"
        ),
    )
    op.create_index(
        "ix_debt_reminder_runs_automation_id", "debt_reminder_runs", ["automation_id"]
    )
    op.create_index(
        "ix_debt_reminder_runs_due", "debt_reminder_runs", ["status", "retry_at"]
    )


def downgrade() -> None:
    op.drop_table("debt_reminder_runs")
    op.drop_table("debt_reminder_automations")
