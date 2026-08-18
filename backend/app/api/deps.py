import uuid

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.models import User


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = access_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    subject = decode_access_token(token) if token else None
    if not subject:
        raise AppError("UNAUTHORIZED", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.", 401)
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise AppError("UNAUTHORIZED", "Phiên đăng nhập không hợp lệ.", 401) from exc
    user = await db.get(User, user_id)
    if not user:
        raise AppError("UNAUTHORIZED", "Tài khoản không còn tồn tại.", 401)
    return user


CurrentUser = Depends(get_current_user)
