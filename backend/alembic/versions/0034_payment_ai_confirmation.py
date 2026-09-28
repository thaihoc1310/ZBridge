"""Payment notices are decided by AI and no longer touch the debt state.

Revision ID: 0034_payment_ai_confirmation
Revises: 0033_mention_classifying_since
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_payment_ai_confirmation"
down_revision = "0033_mention_classifying_since"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debt_payment_confirmations",
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
    )
    op.add_column(
        "debt_payment_confirmations", sa.Column("ai_confidence", sa.Float(), nullable=True)
    )
    op.add_column("debt_payment_confirmations", sa.Column("ai_reason", sa.Text(), nullable=True))
    op.add_column(
        "debt_payment_confirmations",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE debt_payment_confirmations SET status = CASE "
        "WHEN applied_at IS NOT NULL THEN 'SENT' "
        "WHEN failed_at IS NOT NULL THEN 'FAILED' ELSE 'PENDING' END"
    )
    op.alter_column("debt_payment_confirmations", "status", server_default=None)
    op.create_index(
        "ix_debt_payment_confirmations_customer_status",
        "debt_payment_confirmations",
        ["customer_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_debt_payment_confirmations_customer_status", table_name="debt_payment_confirmations"
    )
    for column in ("classified_at", "ai_reason", "ai_confidence", "status"):
        op.drop_column("debt_payment_confirmations", column)
