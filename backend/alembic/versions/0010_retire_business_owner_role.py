"""Stop reserving the Chủ doanh nghiệp role.

ADMIN is now the only role the catalog reserves. 0008 seeded BUSINESS_OWNER
alongside it, so drop that row where nobody is assigned to it, and hand it over
as an ordinary editable role where somebody is — deleting it there would strand
a real account behind the RESTRICT foreign key.

Revision ID: 0010_retire_business_owner
Revises: 0009_mention_classifier
"""

from alembic import op

revision = "0010_retire_business_owner"
down_revision = "0009_mention_classifier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # role_permissions cascades on the role, so the grants go with it.
    op.execute(
        """
        DELETE FROM roles
        WHERE code = 'BUSINESS_OWNER'
          AND NOT EXISTS (SELECT 1 FROM users WHERE users.role_id = roles.id)
        """
    )
    op.execute("UPDATE roles SET is_system = false WHERE code = 'BUSINESS_OWNER'")


def downgrade() -> None:
    # The row cannot be recreated with its grants; only the reservation returns.
    op.execute("UPDATE roles SET is_system = true WHERE code = 'BUSINESS_OWNER'")
