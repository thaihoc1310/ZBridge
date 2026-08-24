"""Add a short-lived audit trail for mention classifier calls.

Revision ID: 0017_model_call_logs
Revises: 0016_group_sync_safety
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_model_call_logs"
down_revision = "0016_group_sync_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_call_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("followup_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("scheduled_for_send", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("zalo_message_id", sa.String(length=128), nullable=True),
        sa.Column("message_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["followup_id"], ["mention_followups.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_call_logs_created", "model_call_logs", ["created_at"])
    op.create_index(
        "ix_model_call_logs_followup_created",
        "model_call_logs",
        ["followup_id", "created_at"],
    )
    op.create_index("ix_model_call_logs_customer_id", "model_call_logs", ["customer_id"])
    op.create_index(
        "ix_model_call_logs_status_created", "model_call_logs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_call_logs_status_created", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_customer_id", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_followup_created", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_created", table_name="model_call_logs")
    op.drop_table("model_call_logs")
