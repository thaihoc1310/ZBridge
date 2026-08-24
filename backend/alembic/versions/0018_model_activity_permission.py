"""Split delivery and model-call activity permissions.

Existing roles retain everything they could access before this split. An admin
can remove either grant independently after deployment.

Revision ID: 0018_model_activity_permission
Revises: 0017_model_call_logs
"""

from alembic import op

revision = "0018_model_activity_permission"
down_revision = "0017_model_call_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, name, category, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'model_activity:read',
            'Xem nhật ký gọi model',
            'Nhật ký',
            NOW(),
            NOW()
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, model_permission.id
        FROM role_permissions rp
        JOIN permissions current_permission ON current_permission.id = rp.permission_id
        CROSS JOIN permissions model_permission
        WHERE current_permission.code = 'activity:read'
          AND model_permission.code = 'model_activity:read'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code = 'model_activity:read'")
