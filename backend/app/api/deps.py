import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.security import decode_token
from app.db.database import get_db
from app.models import Role, User

#: `iat` is truncated to whole seconds, so a token minted in the same second as
#: a password change must still be accepted.
PASSWORD_CHANGE_LEEWAY = timedelta(seconds=1)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = access_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token) if token else None
    if payload is None:
        raise AppError("UNAUTHORIZED", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.", 401)
    try:
        user_id = uuid.UUID(payload.subject)
    except ValueError as exc:
        raise AppError("UNAUTHORIZED", "Phiên đăng nhập không hợp lệ.", 401) from exc
    user = await db.scalar(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    if user is None:
        raise AppError("UNAUTHORIZED", "Tài khoản không còn tồn tại.", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "Tài khoản đã bị vô hiệu hóa.", 403)
    if payload.issued_at + PASSWORD_CHANGE_LEEWAY < _as_utc(user.password_changed_at):
        raise AppError("PASSWORD_CHANGED", "Mật khẩu đã được thay đổi. Hãy đăng nhập lại.", 401)
    return user


def require_permission(*codes: str) -> Callable[..., Awaitable[User]]:
    """Build a dependency that requires every listed permission code."""
    required = frozenset(codes)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if required - user.permission_codes:
            raise AppError("FORBIDDEN", "Bạn không có quyền thực hiện thao tác này.", 403)
        return user

    return dependency
