"""Add durable group mention automation.

Revision ID: 0002_mention_automation
Revises: 0001_initial
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_mention_automation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mention_automations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_group_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["zalo_group_id"], ["zalo_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_group_id"),
    )
    op.create_index(
        "ix_mention_automations_zalo_group_id",
        "mention_automations",
        ["zalo_group_id"],
        unique=True,
    )
    op.create_table(
        "mention_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("zalo_user_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["mention_automations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "zalo_user_id", name="uq_mention_target_user"),
    )
    op.create_index("ix_mention_targets_automation_id", "mention_targets", ["automation_id"])
    op.create_table(
        "mention_followups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.String(128), nullable=False),
        sa.Column("source_sender_id", sa.String(128)),
        sa.Column("target_user_ids", sa.JSON(), nullable=False),
        sa.Column("target_display_names", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_message_id", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["mention_automations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id", "source_message_id", name="uq_mention_followup_source"
        ),
    )
    op.create_index("ix_mention_followups_automation_id", "mention_followups", ["automation_id"])
    op.create_index("ix_mention_followups_due", "mention_followups", ["status", "due_at"])


def downgrade() -> None:
    op.drop_table("mention_followups")
    op.drop_table("mention_targets")
    op.drop_table("mention_automations")
