"""Split the system-wide classifier policy out of mention:update.

`mention:update` guards one customer's tagging config; the policy page it also
guarded changes how every group is judged. Give the policy its own code covering
both reading and writing that page, then grant it to whoever could already reach
it so nobody loses a capability in the deploy that introduces the split.

`sync_rbac` normally creates permission rows at boot, but migrations run first
and this one has to grant the code, so it inserts the row itself. The later
sync just refreshes the label.

Revision ID: 0011_mention_policy_permission
Revises: 0010_retire_business_owner
"""

from alembic import op

revision = "0011_mention_policy_permission"
down_revision = "0010_retire_business_owner"
branch_labels = None
depends_on = None

CODE = "mention_policy:manage"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permissions (id, code, name, category, created_at, updated_at)
        VALUES (
            gen_random_uuid(), '{CODE}',
            'Xem và đổi chính sách phân loại tag toàn hệ thống', 'Tag tên tự động',
            NOW(), NOW()
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, (SELECT id FROM permissions WHERE code = '{CODE}')
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.code = 'mention:update'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
