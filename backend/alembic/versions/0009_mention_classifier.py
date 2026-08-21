"""Add global mention classification policy and short-lived context.

Revision ID: 0009_mention_classifier
Revises: 0008_rbac
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0009_mention_classifier"
down_revision = "0008_rbac"
branch_labels = None
depends_on = None

DEFAULT_SKIP_PHRASES = [
    "ok",
    "oke",
    "okay",
    "cảm ơn",
    "cảm ơn nhé",
    "thanks",
    "thank you",
    "rõ rồi",
    "đã rõ",
    "nhận được",
    "nhận được rồi",
]


def upgrade() -> None:
    op.create_table(
        "mention_classifier_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "ai_classifier_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "bare_mention_requires_response",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("skip_phrases", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    skip_phrases_json = json.dumps(DEFAULT_SKIP_PHRASES, ensure_ascii=False).replace("'", "''")
    op.execute(
        sa.text(
            "INSERT INTO mention_classifier_settings "
            "(id, ai_classifier_enabled, bare_mention_requires_response, skip_phrases) "
            f"VALUES (1, true, true, '{skip_phrases_json}')"
        )
    )

    op.create_table(
        "mention_context_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("sender_id", sa.String(128)),
        sa.Column("sender_display_name", sa.String(255)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["mention_automations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id", "message_id", name="uq_mention_context_message"
        ),
    )
    op.create_index(
        "ix_mention_context_messages_automation_id",
        "mention_context_messages",
        ["automation_id"],
    )
    op.create_index(
        "ix_mention_context_messages_sent_at", "mention_context_messages", ["sent_at"]
    )
    op.create_index(
        "ix_mention_context_group_sent",
        "mention_context_messages",
        ["automation_id", "sent_at"],
    )

    op.add_column("mention_followups", sa.Column("classification_model", sa.String(128)))
    op.add_column("mention_followups", sa.Column("classification_result", sa.JSON()))
    op.add_column("mention_followups", sa.Column("classification_error", sa.Text()))
    op.add_column("mention_followups", sa.Column("classification_input_tokens", sa.Integer()))
    op.add_column("mention_followups", sa.Column("classification_output_tokens", sa.Integer()))
    op.add_column("mention_followups", sa.Column("classification_latency_ms", sa.Integer()))


def downgrade() -> None:
    op.drop_column("mention_followups", "classification_latency_ms")
    op.drop_column("mention_followups", "classification_output_tokens")
    op.drop_column("mention_followups", "classification_input_tokens")
    op.drop_column("mention_followups", "classification_error")
    op.drop_column("mention_followups", "classification_result")
    op.drop_column("mention_followups", "classification_model")
    op.drop_table("mention_context_messages")
    op.drop_table("mention_classifier_settings")
