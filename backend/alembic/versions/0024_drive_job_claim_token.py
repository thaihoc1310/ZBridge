"""Make Drive jobs single-owner and store large Drive file sizes safely.

Revision ID: 0024_drive_job_claim
Revises: 0023_mention_send_count
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_drive_job_claim"
down_revision = "0023_mention_send_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drive_conversion_jobs",
        sa.Column("claim_token", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_drive_conversion_jobs_claim_token",
        "drive_conversion_jobs",
        ["claim_token"],
        unique=False,
    )
    op.alter_column(
        "drive_conversion_items",
        "size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    # An unavailable Zalo group cannot receive either automation. Older
    # versions left its debt schedule and active jobs runnable indefinitely.
    op.execute(
        sa.text(
            """
            UPDATE debt_reminder_automations AS dra
            SET next_run_at = NULL, updated_at = NOW()
            FROM customers AS c
            JOIN zalo_groups AS zg ON zg.id = c.zalo_group_id
            WHERE dra.customer_id = c.id
              AND zg.is_available = FALSE
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE debt_reminder_runs AS drr
            SET status = 'CANCELLED', claimed_at = NULL, processed_at = NOW(),
                error_message = 'Nhóm Zalo hiện không còn khả dụng.'
            FROM debt_reminder_automations AS dra
            JOIN customers AS c ON c.id = dra.customer_id
            JOIN zalo_groups AS zg ON zg.id = c.zalo_group_id
            WHERE drr.automation_id = dra.id
              AND zg.is_available = FALSE
              AND drr.status IN ('PENDING', 'PROCESSING')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE mention_followups AS mf
            SET status = 'CANCELLED', claimed_at = NULL, processed_at = NOW(),
                error_message = 'Nhóm Zalo hiện không còn khả dụng.'
            FROM mention_automations AS ma
            JOIN zalo_groups AS zg ON zg.id = ma.zalo_group_id
            WHERE mf.automation_id = ma.id
              AND zg.is_available = FALSE
              AND mf.status IN ('CLASSIFYING', 'PENDING', 'PROCESSING')
            """
        )
    )


def downgrade() -> None:
    op.alter_column(
        "drive_conversion_items",
        "size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.drop_index(
        "ix_drive_conversion_jobs_claim_token",
        table_name="drive_conversion_jobs",
    )
    op.drop_column("drive_conversion_jobs", "claim_token")
