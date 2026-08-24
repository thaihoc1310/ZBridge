"""Track successful sends across a repeating mention follow-up.

Revision ID: 0023_mention_send_count
Revises: 0022_automation_invariants
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_mention_send_count"
down_revision = "0022_automation_invariants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_followups",
        sa.Column("send_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(
        sa.text(
            """
            UPDATE mention_followups
            SET send_count = 1
            WHERE sent_message_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("mention_followups", "send_count")
