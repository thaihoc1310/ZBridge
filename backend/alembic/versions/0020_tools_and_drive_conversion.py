"""Add tools permissions and Drive conversion jobs.

Revision ID: 0020_tools_and_drive_conversion
Revises: 0019_remove_model_send_tracking
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "0020_tools_and_drive_conversion"
down_revision = "0019_remove_model_send_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_conversion_folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("folder_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("drive_id", sa.String(255)),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("folder_id"),
    )
    op.create_index(
        "ix_drive_conversion_folders_folder_id", "drive_conversion_folders", ["folder_id"]
    )
    op.create_table(
        "drive_conversion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "folder_id",
            sa.Uuid(),
            sa.ForeignKey("drive_conversion_folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("delete_originals", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("converted_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_drive_conversion_jobs_folder_id", "drive_conversion_jobs", ["folder_id"])
    op.create_index(
        "ix_drive_conversion_jobs_folder_created",
        "drive_conversion_jobs",
        ["folder_id", "created_at"],
    )
    op.create_index(
        "ix_drive_conversion_jobs_status_created", "drive_conversion_jobs", ["status", "created_at"]
    )
    op.create_table(
        "drive_conversion_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("drive_conversion_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_file_id", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(500), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("parent_folder_id", sa.String(255), nullable=False),
        sa.Column("parent_folder_name", sa.String(500), nullable=False),
        sa.Column("parent_folder_url", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("can_download", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_trash", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("destination_file_id", sa.String(255)),
        sa.Column("destination_url", sa.Text()),
        sa.Column("original_trashed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("job_id", "source_file_id", name="uq_drive_conversion_job_source"),
    )
    op.create_index("ix_drive_conversion_items_job_id", "drive_conversion_items", ["job_id"])
    op.create_index(
        "ix_drive_conversion_items_job_status", "drive_conversion_items", ["job_id", "status"]
    )

    bind = op.get_bind()
    permission_rows = [
        ("tools:read", "Truy cập trang Công cụ", "Công cụ"),
        ("mention_followup:read", "Xem các vòng tag đang hoạt động", "Tag tên tự động"),
        ("mention_followup:cancel", "Dừng vòng tag đang hoạt động", "Tag tên tự động"),
        ("debt_reminder_bulk:apply", "Áp lịch nhắc công nợ hàng loạt", "Nhắc công nợ"),
        ("debt_reminder_history:read", "Xem lịch sử lượt nhắc công nợ", "Nhắc công nợ"),
        ("drive_conversion:manage", "Quản lý chuyển Excel sang Google Sheets", "Công cụ"),
    ]
    for code, name, category in permission_rows:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, category) "
                "VALUES (:id, :code, :name, :category) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "name": name, "category": category},
        )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
            "WHERE roles.code = 'ADMIN' AND permissions.code IN :codes "
            "ON CONFLICT DO NOTHING"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": [row[0] for row in permission_rows]},
    )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT DISTINCT rp.role_id, p_tools.id FROM role_permissions rp "
            "JOIN permissions p_old ON p_old.id = rp.permission_id "
            "CROSS JOIN permissions p_tools WHERE p_old.code IN :old_codes "
            "AND p_tools.code = 'tools:read' ON CONFLICT DO NOTHING"
        ).bindparams(sa.bindparam("old_codes", expanding=True)),
        {"old_codes": ["mention_policy:manage", "staff:manage", "mention_bulk:apply"]},
    )


def downgrade() -> None:
    codes = [
        "tools:read",
        "mention_followup:read",
        "mention_followup:cancel",
        "debt_reminder_bulk:apply",
        "debt_reminder_history:read",
        "drive_conversion:manage",
    ]
    op.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes")
        .bindparams(sa.bindparam("codes", expanding=True))
        .params(codes=codes)
    )
    op.drop_table("drive_conversion_items")
    op.drop_table("drive_conversion_jobs")
    op.drop_table("drive_conversion_folders")
