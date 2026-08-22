"""Permission catalog, one code per protected API action.

This module is the single source of truth: the database mirrors it on every
boot, so a role can never grant something the API does not actually check.
"""

from dataclasses import dataclass

DASHBOARD_READ = "dashboard:read"

BOT_READ = "bot:read"
BOT_CONNECT = "bot:connect"
BOT_DISCONNECT = "bot:disconnect"

CUSTOMER_READ = "customer:read"
CUSTOMER_UPDATE = "customer:update"
CUSTOMER_SYNC = "customer:sync"

MESSAGE_SEND = "message:send"

MENTION_READ = "mention:read"
MENTION_UPDATE = "mention:update"
#: The per-customer codes above cover one group each. This one covers the policy
#: every group is judged by, so switching the classifier off or mistyping a skip
#: phrase silently changes behaviour system-wide — worth its own grant. It gates
#: reading the policy as well: the page is a settings form with nothing to show
#: somebody who cannot change it, and one code per tab is what the nav assumes.
MENTION_POLICY_MANAGE = "mention_policy:manage"
#: The staff roster and the bulk editor are separate grants again: the roster is
#: a list of names, while one bulk apply overwrites every customer at once.
STAFF_MANAGE = "staff:manage"
MENTION_BULK_APPLY = "mention_bulk:apply"

DEBT_REMINDER_READ = "debt_reminder:read"
DEBT_REMINDER_UPDATE = "debt_reminder:update"

ACTIVITY_READ = "activity:read"

USER_READ = "user:read"
USER_CREATE = "user:create"
USER_UPDATE = "user:update"
USER_DELETE = "user:delete"
ROLE_READ = "role:read"
ROLE_MANAGE = "role:manage"

CATEGORY_DASHBOARD = "Tổng quan"
CATEGORY_BOT = "Zalo Bot"
CATEGORY_CUSTOMER = "Khách hàng"
CATEGORY_MESSAGE = "Tin nhắn"
CATEGORY_MENTION = "Tag tên tự động"
CATEGORY_DEBT = "Nhắc công nợ"
CATEGORY_ACTIVITY = "Nhật ký"
CATEGORY_ADMIN = "Người dùng & phân quyền"


@dataclass(frozen=True)
class PermissionDef:
    code: str
    name: str
    category: str


PERMISSION_CATALOG: tuple[PermissionDef, ...] = (
    PermissionDef(DASHBOARD_READ, "Xem trang tổng quan", CATEGORY_DASHBOARD),
    PermissionDef(BOT_READ, "Xem trạng thái bot Zalo", CATEGORY_BOT),
    PermissionDef(BOT_CONNECT, "Kết nối bot và quét mã QR", CATEGORY_BOT),
    PermissionDef(BOT_DISCONNECT, "Đăng xuất bot khỏi Zalo", CATEGORY_BOT),
    PermissionDef(CUSTOMER_READ, "Xem khách hàng và thành viên nhóm", CATEGORY_CUSTOMER),
    PermissionDef(CUSTOMER_UPDATE, "Sửa công nợ, ghi chú, file công nợ", CATEGORY_CUSTOMER),
    PermissionDef(CUSTOMER_SYNC, "Đồng bộ danh sách khách hàng từ Zalo", CATEGORY_CUSTOMER),
    PermissionDef(MESSAGE_SEND, "Gửi tin nhắn thủ công vào nhóm", CATEGORY_MESSAGE),
    PermissionDef(MENTION_READ, "Xem cấu hình tag tên tự động", CATEGORY_MENTION),
    PermissionDef(MENTION_UPDATE, "Thay đổi cấu hình tag tên tự động", CATEGORY_MENTION),
    PermissionDef(
        MENTION_POLICY_MANAGE,
        "Xem và đổi chính sách phân loại tag toàn hệ thống",
        CATEGORY_MENTION,
    ),
    PermissionDef(STAFF_MANAGE, "Xem và sửa danh sách nhân sự được tag", CATEGORY_MENTION),
    PermissionDef(
        MENTION_BULK_APPLY,
        "Áp cấu hình tag hàng loạt, ghi đè nhiều khách hàng",
        CATEGORY_MENTION,
    ),
    PermissionDef(DEBT_REMINDER_READ, "Xem cấu hình nhắc công nợ", CATEGORY_DEBT),
    PermissionDef(DEBT_REMINDER_UPDATE, "Thay đổi cấu hình nhắc công nợ", CATEGORY_DEBT),
    PermissionDef(ACTIVITY_READ, "Xem nhật ký gửi tin", CATEGORY_ACTIVITY),
    PermissionDef(USER_READ, "Xem danh sách người dùng", CATEGORY_ADMIN),
    PermissionDef(USER_CREATE, "Tạo người dùng mới", CATEGORY_ADMIN),
    PermissionDef(USER_UPDATE, "Sửa người dùng, đổi vai trò, đặt lại mật khẩu", CATEGORY_ADMIN),
    PermissionDef(USER_DELETE, "Xóa người dùng", CATEGORY_ADMIN),
    PermissionDef(ROLE_READ, "Xem vai trò và quyền", CATEGORY_ADMIN),
    PermissionDef(ROLE_MANAGE, "Tạo, sửa, xóa vai trò", CATEGORY_ADMIN),
)

ALL_PERMISSION_CODES: frozenset[str] = frozenset(
    definition.code for definition in PERMISSION_CATALOG
)

#: Everything that lets an account administer other accounts.
USER_MANAGEMENT_PERMISSIONS: frozenset[str] = frozenset(
    {USER_READ, USER_CREATE, USER_UPDATE, USER_DELETE, ROLE_READ, ROLE_MANAGE}
)

ADMIN_ROLE_CODE = "ADMIN"


@dataclass(frozen=True)
class SystemRoleDef:
    code: str
    name: str
    description: str
    permissions: frozenset[str]


#: Reserved roles, resynced on every boot and locked against editing. Keep this
#: to the one role that must never lose a permission — everything else belongs
#: to the operator, who can shape it in the UI. A role dropped from here is not
#: deleted: `sync_rbac` hands it over as an ordinary editable role.
SYSTEM_ROLES: tuple[SystemRoleDef, ...] = (
    SystemRoleDef(
        ADMIN_ROLE_CODE,
        "Quản trị hệ thống",
        "Toàn quyền vận hành, kèm quản lý người dùng và phân quyền.",
        ALL_PERMISSION_CODES,
    ),
)

SYSTEM_ROLE_CODES: frozenset[str] = frozenset(role.code for role in SYSTEM_ROLES)
