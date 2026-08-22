import logging
import re
import unicodedata
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.permissions import (
    ADMIN_ROLE_CODE,
    PERMISSION_CATALOG,
    SYSTEM_ROLES,
    USER_UPDATE,
    PermissionDef,
)
from app.models import Permission, Role, User
from app.schemas.api import PermissionResponse, RoleCreate, RoleResponse, RoleUpdate

logger = logging.getLogger("zbridge.rbac")


def role_response(role: Role, user_count: int = 0) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=[permission.code for permission in role.permissions],
        user_count=user_count,
    )


def permission_catalog() -> list[PermissionResponse]:
    return [
        PermissionResponse(code=item.code, name=item.name, category=item.category)
        for item in PERMISSION_CATALOG
    ]


async def sync_rbac(db: AsyncSession) -> None:
    """Mirror the code-defined catalog into the database.

    System roles are re-synced on every boot so a newly shipped permission is
    granted without a manual step. Custom roles are never touched here, and a
    role that leaves the catalog is demoted into one rather than deleted.
    """
    stored = {
        permission.code: permission
        for permission in (await db.scalars(select(Permission))).all()
    }
    for definition in PERMISSION_CATALOG:
        existing = stored.get(definition.code)
        if existing is None:
            stored[definition.code] = _new_permission(db, definition)
        else:
            existing.name = definition.name
            existing.category = definition.category
    await db.flush()

    known = {definition.code for definition in PERMISSION_CATALOG}
    retired = sorted(code for code in stored if code not in known)
    if retired:
        await db.execute(delete(Permission).where(Permission.code.in_(retired)))
        for code in retired:
            stored.pop(code, None)
        logger.info("RBAC_PERMISSIONS_RETIRED codes=%s", ",".join(retired))

    roles = {
        role.code: role
        for role in (
            await db.scalars(select(Role).options(selectinload(Role.permissions)))
        ).all()
    }
    for definition in SYSTEM_ROLES:
        role = roles.get(definition.code)
        granted = [stored[code] for code in sorted(definition.permissions)]
        if role is None:
            role = Role(
                code=definition.code,
                name=definition.name,
                description=definition.description,
                is_system=True,
            )
            # Assign while still transient: on a flushed instance this would
            # lazy-load the existing collection, which async sessions forbid.
            role.permissions = granted
            db.add(role)
        else:
            role.name = definition.name
            role.description = definition.description
            role.is_system = True
            role.permissions = granted

    reserved = {definition.code for definition in SYSTEM_ROLES}
    demoted = [
        role for code, role in roles.items() if role.is_system and code not in reserved
    ]
    for role in demoted:
        # Dropped from the catalog: keep its grants and the people assigned to
        # it, but stop reserving it so an admin can edit or remove it by hand.
        role.is_system = False
    if demoted:
        logger.info(
            "RBAC_ROLES_DEMOTED codes=%s",
            ",".join(sorted(role.code for role in demoted)),
        )
    await db.commit()
    logger.info(
        "RBAC_SYNCED permissions=%d system_roles=%d", len(stored), len(SYSTEM_ROLES)
    )


def _new_permission(db: AsyncSession, definition: PermissionDef) -> Permission:
    permission = Permission(
        code=definition.code, name=definition.name, category=definition.category
    )
    db.add(permission)
    return permission


async def _user_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = (await db.execute(select(User.role_id, func.count()).group_by(User.role_id))).all()
    return {role_id: int(count) for role_id, count in rows}


async def list_roles(db: AsyncSession) -> list[RoleResponse]:
    roles = (
        await db.scalars(
            select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
        )
    ).all()
    counts = await _user_counts(db)
    return [role_response(role, counts.get(role.id, 0)) for role in roles]


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.scalar(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    )
    if role is None:
        raise AppError("ROLE_NOT_FOUND", "Không tìm thấy vai trò.", 404)
    return role


async def lock_user_management_invariant(db: AsyncSession) -> None:
    """Use the immutable ADMIN role row as a transaction-wide mutex.

    User and role mutations can otherwise both observe "one other manager" and
    commit concurrently, leaving nobody able to administer accounts.
    """
    await db.scalar(
        select(Role.id).where(Role.code == ADMIN_ROLE_CODE).with_for_update()
    )


async def _active_user_manager_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(Role, Role.id == User.role_id)
            .join(Role.permissions)
            .where(User.is_active.is_(True), Permission.code == USER_UPDATE)
        )
        or 0
    )


async def _resolve_permissions(db: AsyncSession, codes: list[str]) -> list[Permission]:
    unique = sorted(set(codes))
    permissions = list(
        (await db.scalars(select(Permission).where(Permission.code.in_(unique)))).all()
    )
    if len(permissions) != len(unique):
        found = {permission.code for permission in permissions}
        raise AppError(
            "UNKNOWN_PERMISSION",
            f"Quyền không hợp lệ: {', '.join(sorted(set(unique) - found))}.",
            422,
        )
    return permissions


async def _unique_code(db: AsyncSession, name: str) -> str:
    base = _slug(name)
    candidate = base
    suffix = 2
    while await db.scalar(select(Role.id).where(Role.code == candidate)):
        candidate = f"{base}_{suffix}"[:64]
        suffix += 1
    return candidate


def _slug(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name)
    ascii_only = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_").upper()
    return slug[:48] or "ROLE"


async def create_role(db: AsyncSession, data: RoleCreate) -> RoleResponse:
    permissions = await _resolve_permissions(db, data.permissions)
    role = Role(
        code=await _unique_code(db, data.name),
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        is_system=False,
    )
    role.permissions = permissions
    db.add(role)
    await db.commit()
    logger.info("ROLE_CREATED role_id=%s code=%s", role.id, role.code)
    return role_response(await get_role(db, role.id))


async def update_role(
    db: AsyncSession, role_id: uuid.UUID, data: RoleUpdate
) -> RoleResponse:
    role = await get_role(db, role_id)
    await lock_user_management_invariant(db)
    if role.is_system:
        raise AppError(
            "SYSTEM_ROLE_READ_ONLY",
            "Vai trò hệ thống không thể sửa. Hãy tạo một vai trò riêng.",
            422,
        )
    fields = data.model_fields_set
    if "name" in fields and data.name:
        role.name = data.name.strip()
    if "description" in fields:
        role.description = (data.description or "").strip() or None
    if "permissions" in fields and data.permissions is not None:
        if not data.permissions:
            raise AppError("EMPTY_ROLE", "Vai trò phải có ít nhất một quyền.", 422)
        role.permissions = await _resolve_permissions(db, data.permissions)
    await db.flush()
    if await _active_user_manager_count(db) == 0:
        await db.rollback()
        raise AppError(
            "LAST_USER_MANAGER",
            "Phải còn ít nhất một tài khoản đang hoạt động có quyền quản lý người dùng.",
            422,
        )
    await db.commit()
    logger.info("ROLE_UPDATED role_id=%s", role.id)
    return role_response(await get_role(db, role.id))


async def delete_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    role = await get_role(db, role_id)
    if role.is_system:
        raise AppError("SYSTEM_ROLE_READ_ONLY", "Không thể xóa vai trò hệ thống.", 422)
    assigned = int(
        await db.scalar(
            select(func.count()).select_from(User).where(User.role_id == role.id)
        )
        or 0
    )
    if assigned:
        raise AppError(
            "ROLE_IN_USE",
            f"Vai trò đang được gán cho {assigned} người dùng. "
            "Hãy chuyển họ sang vai trò khác trước.",
            422,
        )
    await db.delete(role)
    await db.commit()
    logger.info("ROLE_DELETED role_id=%s code=%s", role_id, role.code)
