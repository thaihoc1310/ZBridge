"""Require a fresh model verdict before every mention send.

Revision ID: 0025_mention_due_rechecks
Revises: 0024_drive_job_claim
"""

import sqlalchemy as sa

from alembic import op

revision = "0025_mention_due_rechecks"
down_revision = "0024_drive_job_claim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_followups",
        sa.Column("evaluated_due_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mention_followups", "evaluated_due_at")
