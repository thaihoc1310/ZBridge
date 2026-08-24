"""Store the Google OAuth connection used by Drive conversion.

Revision ID: 0021_google_drive_oauth
Revises: 0020_tools_and_drive_conversion
"""

import sqlalchemy as sa

from alembic import op

revision = "0021_google_drive_oauth"
down_revision = "0020_tools_and_drive_conversion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_oauth_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column(
            "connected_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_google_oauth_connection_singleton"),
    )


def downgrade() -> None:
    op.drop_table("google_oauth_connections")
