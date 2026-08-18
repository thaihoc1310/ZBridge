"""Introduce customer records and lightweight bot delivery logs.

Revision ID: 0004_customer_driven
Revises: 0003_mention_active_windows
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_customer_driven"
down_revision = "0003_mention_active_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zalo_group_id", sa.Uuid(), nullable=False),
        sa.Column("has_debt", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_debt_paid_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.Column("folder_url", sa.Text()),
        sa.Column("folder_name", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["zalo_group_id"], ["zalo_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_group_id"),
    )
    op.create_index("ix_customers_zalo_group_id", "customers", ["zalo_group_id"], unique=True)
    op.create_index("ix_customers_has_debt", "customers", ["has_debt"])
    op.execute(
        sa.text(
            """
            INSERT INTO customers (id, zalo_group_id, has_debt, created_at, updated_at)
            SELECT id, id, false, created_at, updated_at
            FROM zalo_groups
            """
        )
    )

    op.create_table(
        "bot_delivery_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("zalo_message_id", sa.String(128)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_delivery_logs_customer_id", "bot_delivery_logs", ["customer_id"])
    op.create_index(
        "ix_bot_delivery_logs_customer_created",
        "bot_delivery_logs",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_bot_delivery_logs_status_created",
        "bot_delivery_logs",
        ["status", "created_at"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO bot_delivery_logs (
                id, customer_id, type, status, zalo_message_id,
                error_code, error_message, created_at
            )
            SELECT
                id,
                zalo_group_id,
                'MANUAL_MESSAGE',
                CASE WHEN status = 'SENT' THEN 'SENT' ELSE 'FAILED' END,
                zalo_message_id,
                CASE
                    WHEN status = 'SENDING' THEN 'LEGACY_INCOMPLETE'
                    ELSE error_code
                END,
                CASE
                    WHEN status = 'SENDING' THEN 'Lượt gửi cũ chưa có kết quả cuối cùng.'
                    ELSE error_message
                END,
                COALESCE(sent_at, created_at)
            FROM messages
            """
        )
    )
    op.drop_table("messages")


def downgrade() -> None:
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["zalo_group_id"], ["zalo_groups.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_zalo_group_id", "messages", ["zalo_group_id"])
    op.create_index("ix_messages_group_created", "messages", ["zalo_group_id", "created_at"])
    op.execute(
        sa.text(
            """
            INSERT INTO messages (
                id, zalo_group_id, type, content, status, zalo_message_id,
                error_code, error_message, created_at, sent_at
            )
            SELECT
                id, customer_id, 'TEXT', '[Không lưu nội dung]', status,
                zalo_message_id, error_code, error_message, created_at,
                CASE WHEN status = 'SENT' THEN created_at ELSE NULL END
            FROM bot_delivery_logs
            WHERE type = 'MANUAL_MESSAGE'
            """
        )
    )
    op.drop_table("bot_delivery_logs")
    op.drop_table("customers")
