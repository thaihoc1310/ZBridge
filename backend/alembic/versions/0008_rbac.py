"""Add roles, permissions and user account fields.

Permission rows and their role assignments are filled in by the API's RBAC sync
on startup, so the catalog stays defined in exactly one place (app.core.permissions).

Revision ID: 0008_rbac
Revises: 0007_debt_repeat
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_rbac"
down_revision = "0007_debt_repeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    op.execute(
        """
        INSERT INTO roles (id, code, name, description, is_system, created_at, updated_at)
        VALUES
            (
                gen_random_uuid(), 'ADMIN', 'Quản trị hệ thống',
                'Toàn quyền vận hành, kèm quản lý người dùng và phân quyền.',
                true, NOW(), NOW()
            ),
            (
                gen_random_uuid(), 'BUSINESS_OWNER', 'Chủ doanh nghiệp',
                'Toàn quyền vận hành khách hàng và tự động hóa, không quản lý người dùng.',
                true, NOW(), NOW()
            )
        """
    )

    op.add_column("users", sa.Column("full_name", sa.String(255)))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("role_id", sa.Uuid(), nullable=True))
    # Everyone who could already sign in was an unrestricted operator.
    op.execute("UPDATE users SET role_id = (SELECT id FROM roles WHERE code = 'ADMIN')")
    op.alter_column("users", "role_id", nullable=False)
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.create_foreign_key(
        "fk_users_role_id", "users", "roles", ["role_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_column("users", "role_id")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "full_name")
    op.drop_table("role_permissions")
    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")
