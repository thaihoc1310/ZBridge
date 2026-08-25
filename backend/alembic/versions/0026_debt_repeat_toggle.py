"""Allow debt reminder intervals to be disabled independently.

Revision ID: 0026_debt_repeat_toggle
Revises: 0025_mention_due_rechecks
"""

import sqlalchemy as sa

from alembic import op

revision = "0026_debt_repeat_toggle"
down_revision = "0025_mention_due_rechecks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debt_reminder_automations",
        sa.Column(
            "repeat_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("debt_reminder_automations", "repeat_enabled")
