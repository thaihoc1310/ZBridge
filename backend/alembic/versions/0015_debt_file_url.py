"""Point a customer at one debt spreadsheet instead of a folder.

Picking "the first Google Sheet in this folder" was a guess that changed
whenever somebody added a file. The column now holds the sheet itself, checked
against the Sheets API when it is saved.

Old folder links cannot be converted without calling Google, so they are
cleared: a wrong link that looks fine is worse than an empty field, and the
reminder refuses to run without one anyway.

Revision ID: 0015_debt_file_url
Revises: 0014_staff_and_bulk_permissions
"""

from alembic import op

revision = "0015_debt_file_url"
down_revision = "0014_staff_and_bulk_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("customers", "folder_url", new_column_name="debt_file_url")
    op.execute(
        "UPDATE customers SET debt_file_url = NULL"
        " WHERE debt_file_url NOT LIKE '%docs.google.com/spreadsheets/%'"
    )


def downgrade() -> None:
    op.alter_column("customers", "debt_file_url", new_column_name="folder_url")
