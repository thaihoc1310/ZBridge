"""Automatically mark customers paid from trusted Zalo messages.

Revision ID: 0030_debt_payment_confirmation
Revises: 0029_manual_debt
"""

import sqlalchemy as sa

from alembic import op

revision = "0030_debt_payment_confirmation"
down_revision = "0029_manual_debt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debt_payment_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tracked_members", sa.JSON(), nullable=False),
        sa.Column("phrases", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "debt_payment_confirmations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_message_id", sa.String(length=128), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("sender_display_name", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("matched_phrase", sa.String(length=100), nullable=False),
        sa.Column("message_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "customer_id",
            "source_message_id",
            name="uq_debt_payment_confirmation_message",
        ),
    )
    op.create_index(
        "ix_debt_payment_confirmations_customer_id",
        "debt_payment_confirmations",
        ["customer_id"],
    )
    op.create_index(
        "ix_debt_payment_confirmations_created",
        "debt_payment_confirmations",
        ["created_at"],
    )
    op.execute(
        """
        INSERT INTO debt_payment_settings (id, tracked_members, phrases)
        VALUES (1, '[]', '["đã thanh toán", "đã tt", "da thanh toan"]')
        """
    )
    op.execute(
        """
        INSERT INTO permissions (id, code, name, category, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'debt_payment_confirmation:manage',
            'Cấu hình tự động ghi nhận thanh toán',
            'Nhắc công nợ',
            NOW(),
            NOW()
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, new_permission.id
        FROM role_permissions rp
        JOIN permissions current_permission
          ON current_permission.id = rp.permission_id
        CROSS JOIN permissions new_permission
        WHERE current_permission.code = 'debt_reminder:update'
          AND new_permission.code = 'debt_payment_confirmation:manage'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code = 'debt_payment_confirmation:manage'")
    op.drop_index(
        "ix_debt_payment_confirmations_created",
        table_name="debt_payment_confirmations",
    )
    op.drop_index(
        "ix_debt_payment_confirmations_customer_id",
        table_name="debt_payment_confirmations",
    )
    op.drop_table("debt_payment_confirmations")
    op.drop_table("debt_payment_settings")
