"""Store only the customer folder URL.

Revision ID: 0005_remove_customer_folder_name
Revises: 0004_customer_driven
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_remove_customer_folder_name"
down_revision = "0004_customer_driven"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("customers", "folder_name")


def downgrade() -> None:
    op.add_column("customers", sa.Column("folder_name", sa.String(255)))

