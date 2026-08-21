"""A company-wide roster of the people who get tagged.

Targets have only ever existed per automation, so picking somebody meant asking
Zalo for one group's members first. The bulk editor needs a list it can offer
without a round trip, and needs it to be the same list everywhere.

Revision ID: 0013_staff_members
Revises: 0012_price_inquiry_trigger
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_staff_members"
down_revision = "0012_price_inquiry_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_user_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("note", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_user_id", name="uq_staff_member_user"),
    )
    # Seed from whoever is already configured, so an existing deployment opens the
    # new page with its real roster rather than an empty list.
    op.execute(
        """
        INSERT INTO staff_members
            (id, zalo_user_id, display_name, avatar_url, created_at, updated_at)
        SELECT gen_random_uuid(), t.zalo_user_id, min(t.display_name),
               min(t.avatar_url), NOW(), NOW()
        FROM mention_targets t
        GROUP BY t.zalo_user_id
        """
    )


def downgrade() -> None:
    op.drop_table("staff_members")
