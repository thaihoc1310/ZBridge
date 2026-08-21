"""Tag the sales side when a customer asks about price.

Splits the single target list in two, since the people who chase an unanswered
mention are not necessarily the ones who quote, and records on each follow-up
which trigger created it — the classifier fails open for one and closed for the
other, so it has to be able to tell them apart.

Existing rows keep their behaviour: every target becomes a MENTION target, every
follow-up a MENTION follow-up, and the new price feature starts switched off.

Revision ID: 0012_price_inquiry_trigger
Revises: 0011_mention_policy_permission
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_price_inquiry_trigger"
down_revision = "0011_mention_policy_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mention_automations",
        sa.Column(
            "mention_tag_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "mention_automations",
        sa.Column(
            "price_inquiry_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    # An automation that was switched off must not come back as a live mention
    # automation just because the new flag defaults to true.
    op.execute("UPDATE mention_automations SET mention_tag_enabled = enabled")

    op.add_column(
        "mention_targets",
        sa.Column(
            "kind", sa.String(16), server_default="MENTION", nullable=False
        ),
    )
    # One person may now sit in both lists, so the identity of a row includes kind.
    op.drop_constraint("uq_mention_target_user", "mention_targets", type_="unique")
    op.create_unique_constraint(
        "uq_mention_target_user", "mention_targets", ["automation_id", "zalo_user_id", "kind"]
    )

    op.add_column(
        "mention_followups",
        sa.Column("trigger", sa.String(20), server_default="MENTION", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("mention_followups", "trigger")
    op.drop_constraint("uq_mention_target_user", "mention_targets", type_="unique")
    # Price targets would collide with mention targets under the old constraint.
    op.execute("DELETE FROM mention_targets WHERE kind = 'PRICE'")
    op.create_unique_constraint(
        "uq_mention_target_user", "mention_targets", ["automation_id", "zalo_user_id"]
    )
    op.drop_column("mention_targets", "kind")
    op.drop_column("mention_automations", "price_inquiry_enabled")
    op.drop_column("mention_automations", "mention_tag_enabled")
