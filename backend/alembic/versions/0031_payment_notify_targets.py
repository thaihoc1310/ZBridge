"""Choose who receives automatic payment notifications.

Revision ID: 0031_payment_notify_targets
Revises: 0030_debt_payment_confirmation
"""

import sqlalchemy as sa

from alembic import op

revision = "0031_payment_notify_targets"
down_revision = "0030_debt_payment_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debt_payment_settings",
        sa.Column(
            "notification_targets",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.alter_column(
        "debt_payment_settings", "notification_targets", server_default=None
    )


def downgrade() -> None:
    op.drop_column("debt_payment_settings", "notification_targets")
