"""Require repeated misses before a Zalo group becomes unavailable.

Revision ID: 0016_group_sync_safety
Revises: 0015_debt_file_url
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_group_sync_safety"
down_revision = "0015_debt_file_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "zalo_groups",
        sa.Column("missing_sync_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("zalo_groups", "missing_sync_count")
