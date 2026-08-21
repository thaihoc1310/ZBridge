"""Separate grants for the staff roster and the bulk tag editor.

Both lived under mention:update, which also covers editing one customer. One
bulk apply overwrites every customer at once, so it should not ride along with
the permission somebody gets to set up a single group.

Existing roles keep what they could already do: whoever held mention:update gets
both new codes, so the split takes nothing away on the deploy that introduces it.

Revision ID: 0014_staff_and_bulk_permissions
Revises: 0013_staff_members
"""

from alembic import op

revision = "0014_staff_and_bulk_permissions"
down_revision = "0013_staff_members"
branch_labels = None
depends_on = None

NEW = (
    ("staff:manage", "Xem và sửa danh sách nhân sự được tag"),
    ("mention_bulk:apply", "Áp cấu hình tag hàng loạt, ghi đè nhiều khách hàng"),
)


def upgrade() -> None:
    # Migrations run before the app boots and syncs the catalog, so insert here.
    for code, name in NEW:
        op.execute(
            f"""
            INSERT INTO permissions (id, code, name, category, created_at, updated_at)
            VALUES (gen_random_uuid(), '{code}', '{name}', 'Tag tên tự động', NOW(), NOW())
            ON CONFLICT (code) DO NOTHING
            """
        )
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT rp.role_id, (SELECT id FROM permissions WHERE code = '{code}')
            FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            WHERE p.code = 'mention:update'
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    for code, _name in NEW:
        op.execute(f"DELETE FROM permissions WHERE code = '{code}'")
