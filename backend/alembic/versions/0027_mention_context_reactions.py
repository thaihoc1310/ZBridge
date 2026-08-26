"""Attach heart/like context to the message that received it.

Revision ID: 0027_mention_context_reactions
Revises: 0026_debt_repeat_toggle
"""

import sqlalchemy as sa

from alembic import op

revision = "0027_mention_context_reactions"
down_revision = "0026_debt_repeat_toggle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_context_messages",
        sa.Column(
            "message_aliases",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "mention_context_messages",
        sa.Column(
            "reactions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mention_context_messages", "reactions")
    op.drop_column("mention_context_messages", "message_aliases")
