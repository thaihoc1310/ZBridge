"""Track when a follow-up entered classification, for the stuck watchdog.

Revision ID: 0033_mention_classifying_since
Revises: 0032_payment_reply_state
"""

import sqlalchemy as sa

from alembic import op

revision = "0033_mention_classifying_since"
down_revision = "0032_payment_reply_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_followups",
        sa.Column("classifying_since", sa.DateTime(timezone=True), nullable=True),
    )
    # Rows classifying at deploy time get a full deadline from now rather than
    # being judged by a created_at that may predate a repoint.
    op.execute(
        "UPDATE mention_followups SET classifying_since = now() "
        "WHERE status = 'CLASSIFYING'"
    )


def downgrade() -> None:
    op.drop_column("mention_followups", "classifying_since")
