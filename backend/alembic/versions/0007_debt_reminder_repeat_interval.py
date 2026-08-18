"""Add repeat interval to debt reminders.

Revision ID: 0007_debt_repeat
Revises: 0006_debt_reminders
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_debt_repeat"
down_revision = "0006_debt_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debt_reminder_automations",
        sa.Column(
            "repeat_interval_days",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE debt_reminder_automations AS automation
        SET next_run_at = LEAST(
            automation.next_run_at,
            (
                SELECT MAX(run.scheduled_for)
                FROM debt_reminder_runs AS run
                WHERE run.automation_id = automation.id
                  AND run.status = 'SENT'
            )
                + automation.repeat_interval_days * INTERVAL '1 day'
        )
        FROM customers AS customer
        WHERE customer.id = automation.customer_id
          AND customer.has_debt IS TRUE
          AND automation.enabled IS TRUE
          AND automation.next_run_at IS NOT NULL
          AND (
              SELECT MAX(run.scheduled_for)
              FROM debt_reminder_runs AS run
              WHERE run.automation_id = automation.id
                AND run.status = 'SENT'
          ) + automation.repeat_interval_days * INTERVAL '1 day' > NOW()
          AND EXISTS (
              SELECT 1
              FROM debt_reminder_runs AS run
              WHERE run.automation_id = automation.id
                AND run.status = 'SENT'
          )
        """
    )


def downgrade() -> None:
    op.drop_column("debt_reminder_automations", "repeat_interval_days")
