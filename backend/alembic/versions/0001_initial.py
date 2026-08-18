"""Initial Phase 1 schema."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "zalo_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_user_id", sa.String(128)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_user_id"),
    )
    op.create_table(
        "zalo_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_account_id", sa.Uuid(), nullable=False),
        sa.Column("zalo_group_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["zalo_account_id"], ["zalo_accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_account_id", "zalo_group_id", name="uq_account_zalo_group"),
    )
    op.create_index("ix_zalo_groups_zalo_account_id", "zalo_groups", ["zalo_account_id"])
    op.create_index("ix_zalo_groups_zalo_group_id", "zalo_groups", ["zalo_group_id"])
    op.create_index("ix_zalo_groups_is_available", "zalo_groups", ["is_available"])
    op.create_index("ix_zalo_groups_available_name", "zalo_groups", ["is_available", "name"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_group_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("zalo_message_id", sa.String(128)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["zalo_group_id"], ["zalo_groups.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_zalo_group_id", "messages", ["zalo_group_id"])
    op.create_index("ix_messages_group_created", "messages", ["zalo_group_id", "created_at"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("zalo_groups")
    op.drop_table("zalo_accounts")
    op.drop_table("users")
