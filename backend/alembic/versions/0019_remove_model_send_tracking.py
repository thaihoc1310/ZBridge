"""Keep model-call logs scoped to model calls only.

Revision ID: 0019_remove_model_send_tracking
Revises: 0018_model_activity_permission
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_remove_model_send_tracking"
down_revision = "0018_model_activity_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("model_call_logs", "message_sent_at")
    op.drop_column("model_call_logs", "zalo_message_id")
    op.drop_column("model_call_logs", "message_sent")
    op.drop_column("model_call_logs", "scheduled_for_send")


def downgrade() -> None:
    op.add_column(
        "model_call_logs",
        sa.Column("scheduled_for_send", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "model_call_logs",
        sa.Column("message_sent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "model_call_logs",
        sa.Column("zalo_message_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "model_call_logs",
        sa.Column("message_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
