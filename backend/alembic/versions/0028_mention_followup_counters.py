"""Give the send retry and the repoint guard counters of their own.

Both used to read `attempt_count`, which the classifier resets to zero on every
verdict. Because a failed send forces a re-classification before the next
attempt, the scheduler's MAX_ATTEMPTS and the classifier's MAX_REPOINTS could
never be reached.

Revision ID: 0028_mention_followup_counters
Revises: 0027_mention_context_reactions
"""

import sqlalchemy as sa

from alembic import op

revision = "0028_mention_followup_counters"
down_revision = "0027_mention_context_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_followups",
        sa.Column(
            "send_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "mention_followups",
        sa.Column(
            "repoint_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Both new counters deliberately start at zero for live rows, including
    # CLASSIFYING ones.
    #
    # It is tempting to seed send_attempt_count from attempt_count, but the old
    # column does not hold the quantity the new one means. It counted *claims*
    # since the last reset, mixing send claims with classification claims, and
    # was cleared by acknowledgements, new context and every model verdict. A
    # CLASSIFYING row's value is classification claims — not one failed send. So
    # seeding from it over-counts, and an over-counted budget marks a real
    # reminder FAILED early: precisely the failure this migration exists to stop.
    #
    # Starting at zero errs the other way, and that direction is cheap and
    # bounded: a loop already mid-retry gets at most MAX_ATTEMPTS more sends, and
    # the idempotency key is now keyed on send_count, so every one of those
    # collapses onto the same gateway receipt rather than tagging anybody twice.


def downgrade() -> None:
    op.drop_column("mention_followups", "repoint_count")
    op.drop_column("mention_followups", "send_attempt_count")
