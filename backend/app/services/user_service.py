import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.permissions import USER_UPDATE
from app.core.security import hash_password, verify_password
from app.models import Permission, Role, RolePermission, User
from app.schemas.api import (
    ChangePasswordRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.rbac_service import (
    get_role,
    lock_user_management_invariant,
    role_response,
)

logger = logging.getLogger("zbridge.users")


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role=role_response(user.role),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .execution_options(populate_existing=True)
        .where(User.id == user_id)
    )
    if user is None:
        raise AppError("USER_NOT_FOUND", "Không tìm thấy người dùng.", 404)
    return user


async def list_users(db: AsyncSession) -> list[UserResponse]:
    users = (
        await db.scalars(
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .order_by(User.email)
        )
    ).all()
    return [user_response(user) for user in users]


async def _role_grants_user_management(db: AsyncSession, role_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(func.count())
            .select_from(RolePermission)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id == role_id, Permission.code == USER_UPDATE)
        )
    )


async def _other_user_managers(db: AsyncSession, exclude_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(Role, Role.id == User.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                User.is_active.is_(True),
                User.id != exclude_id,
                Permission.code == USER_UPDATE,
            )
        )
        or 0
    )


async def _ensure_user_management_survives(db: AsyncSession, user: User) -> None:
    """Refuse a change that would leave nobody able to administer accounts."""
    await db.flush()
    if user.is_active and await _role_grants_user_management(db, user.role_id):
        return
    if await _other_user_managers(db, exclude_id=user.id) == 0:
        await db.rollback()
        raise AppError(
            "LAST_USER_MANAGER",
            "Phải còn ít nhất một tài khoản đang hoạt động có quyền quản lý người dùng.",
            422,
        )


async def create_user(db: AsyncSession, data: UserCreate) -> UserResponse:
    role = await get_role(db, data.role_id)
    email = data.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise AppError("EMAIL_ALREADY_USED", "Email này đã được sử dụng.", 409)
    user = User(
        email=email,
        full_name=(data.full_name or "").strip() or None,
        password_hash=hash_password(data.password),
        password_changed_at=datetime.now(UTC),
        is_active=data.is_active,
        role_id=role.id,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("EMAIL_ALREADY_USED", "Email này đã được sử dụng.", 409) from exc
    logger.info("USER_CREATED user_id=%s role=%s", user.id, role.code)
    return user_response(await get_user(db, user.id))


async def update_user(
    db: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate
) -> UserResponse:
    await lock_user_management_invariant(db)
    user = await get_user(db, user_id)
    fields = data.model_fields_set
    is_self = user.id == actor.id

    if "full_name" in fields:
        user.full_name = (data.full_name or "").strip() or None

    if "is_active" in fields and data.is_active is not None and data.is_active != user.is_active:
        if is_self:
            raise AppError(
                "CANNOT_MODIFY_SELF", "Không thể tự vô hiệu hóa tài khoản của mình.", 422
            )
        user.is_active = data.is_active

    if "role_id" in fields and data.role_id is not None and data.role_id != user.role_id:
        if is_self:
            raise AppError(
                "CANNOT_MODIFY_SELF", "Không thể tự thay đổi vai trò của mình.", 422
            )
        user.role_id = (await get_role(db, data.role_id)).id

    if "password" in fields and data.password:
        # Invalidates every session that account still holds.
        user.password_hash = hash_password(data.password)
        user.password_changed_at = datetime.now(UTC)

    await _ensure_user_management_survives(db, user)
    await db.commit()
    logger.info("USER_UPDATED user_id=%s by=%s", user.id, actor.id)
    return user_response(await get_user(db, user.id))


async def delete_user(db: AsyncSession, actor: User, user_id: uuid.UUID) -> None:
    await lock_user_management_invariant(db)
    user = await get_user(db, user_id)
    if user.id == actor.id:
        raise AppError("CANNOT_MODIFY_SELF", "Không thể tự xóa tài khoản của mình.", 422)
    if await _other_user_managers(db, exclude_id=user.id) == 0:
        raise AppError(
            "LAST_USER_MANAGER",
            "Phải còn ít nhất một tài khoản đang hoạt động có quyền quản lý người dùng.",
            422,
        )
    await db.delete(user)
    await db.commit()
    logger.info("USER_DELETED user_id=%s by=%s", user_id, actor.id)


async def change_password(
    db: AsyncSession, user: User, data: ChangePasswordRequest
) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Mật khẩu hiện tại không đúng.", 400)
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.now(UTC)
    await db.commit()
    logger.info("PASSWORD_CHANGED user_id=%s", user.id)
