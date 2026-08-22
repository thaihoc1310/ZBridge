import asyncio
import secrets

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.alerts import Severity
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.database import get_db
from app.models import Role, User
from app.schemas.api import ChangePasswordRequest, LoginRequest, UserResponse
from app.services.alerting import report_async
from app.services.login_rate_limit import (
    clear_login_account_limit,
    login_attempt_allowed,
    record_login_failure,
)
from app.services.user_service import change_password, get_user, user_response

router = APIRouter(prefix="/auth", tags=["auth"])
DUMMY_LOGIN_HASH = hash_password(secrets.token_urlsafe(32))


def _set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        "access_token",
        create_access_token(str(user.id)),
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserResponse)
async def login(
    data: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    email = data.email.lower()
    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else "unknown")
    )[:255]
    if not await login_attempt_allowed(client_ip, email):
        raise AppError(
            "LOGIN_RATE_LIMITED",
            "Đăng nhập quá nhiều lần. Hãy thử lại sau ít phút.",
            429,
        )
    user = await db.scalar(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .where(User.email == email)
    )
    valid_password = await asyncio.to_thread(
        verify_password,
        data.password,
        user.password_hash if user else DUMMY_LOGIN_HASH,
    )
    if not user or not valid_password:
        await record_login_failure(client_ip, email)
        # A single typo is normal; repeated failures for one account are not, so the
        # alert only fires once the counter passes the threshold.
        await report_async(
            "LOGIN_REPEATEDLY_FAILED",
            f"Đăng nhập sai liên tiếp cho {email}"
            f" (từ {settings.login_failure_alert_threshold} lần trở lên).",
            severity=Severity.ERROR,
            context={"Tài khoản": email},
            dedup_key=f"backend:LOGIN_FAILED:{email}",
            notify_from=settings.login_failure_alert_threshold,
            window_seconds=settings.login_failure_window_seconds,
        )
        raise AppError("INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng.", 401)
    if not user.is_active:
        await record_login_failure(client_ip, email)
        raise AppError("ACCOUNT_DISABLED", "Tài khoản đã bị vô hiệu hóa.", 403)
    await clear_login_account_limit(email)
    _set_session_cookie(response, user)
    return user_response(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return user_response(user)


@router.post("/change-password", response_model=UserResponse)
async def change_own_password(
    data: ChangePasswordRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    await change_password(db, user, data)
    # Re-issue the cookie so this session survives the invalidation it triggered.
    _set_session_cookie(response, user)
    # Re-read: the UPDATE expired server-generated columns such as `updated_at`.
    return user_response(await get_user(db, user.id))
