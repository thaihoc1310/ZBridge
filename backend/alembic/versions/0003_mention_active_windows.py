"""Add active time windows to mention automation.

Revision ID: 0003_mention_active_windows
Revises: 0002_mention_automation
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_mention_active_windows"
down_revision = "0002_mention_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_automations",
        sa.Column(
            "active_windows",
            sa.JSON(),
            server_default=sa.text(
                "'[ {\"start\": \"08:00\", \"end\": \"12:00\"}, "
                "{\"start\": \"14:00\", \"end\": \"18:00\"} ]'::json"
            ),
            nullable=False,
        ),
    )
    op.alter_column("mention_automations", "active_windows", server_default=None)


def downgrade() -> None:
    op.drop_column("mention_automations", "active_windows")
