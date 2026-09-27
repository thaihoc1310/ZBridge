"""Switch a customer to paid only after the payment notice reached Zalo.

Revision ID: 0032_payment_reply_state
Revises: 0031_payment_notify_targets
"""

import sqlalchemy as sa

from alembic import op

revision = "0032_payment_reply_state"
down_revision = "0031_payment_notify_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("reply_message_id", "link_message_id"):
        op.add_column(
            "debt_payment_confirmations",
            sa.Column(column, sa.String(length=128), nullable=True),
        )
    for column in ("applied_at", "failed_at"):
        op.add_column(
            "debt_payment_confirmations",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
    # Every earlier row already switched its customer to paid when it was written.
    op.execute("UPDATE debt_payment_confirmations SET applied_at = created_at")


def downgrade() -> None:
    for column in ("failed_at", "applied_at", "link_message_id", "reply_message_id"):
        op.drop_column("debt_payment_confirmations", column)
