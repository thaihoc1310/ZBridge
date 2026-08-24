import asyncio
import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.db.database import SessionLocal
from app.models import GoogleOAuthConnection

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_OAUTH_SCOPES = ("openid", "email", GOOGLE_DRIVE_SCOPE)
STATE_AUDIENCE = "zbridge-google-oauth"
STATE_TTL_MINUTES = 10


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_refresh_token(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_refresh_token(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise AppError(
            "GOOGLE_OAUTH_TOKEN_INVALID",
            "Không giải mã được kết nối Google. Hãy kết nối lại tài khoản.",
            409,
        ) from exc


def create_oauth_state(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": STATE_AUDIENCE,
            "purpose": "google-drive-connect",
            "nonce": secrets.token_urlsafe(18),
            "iat": now,
            "exp": now + timedelta(minutes=STATE_TTL_MINUTES),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_oauth_state(value: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            value,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=STATE_AUDIENCE,
        )
        if payload.get("purpose") != "google-drive-connect":
            raise ValueError("wrong purpose")
        return uuid.UUID(str(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise AppError(
            "GOOGLE_OAUTH_STATE_INVALID",
            "Yêu cầu kết nối Google không hợp lệ hoặc đã hết hạn.",
            400,
        ) from exc


def _require_oauth_configured() -> None:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise AppError(
            "GOOGLE_OAUTH_NOT_CONFIGURED",
            "Chưa cấu hình Google OAuth Client ID và Client Secret.",
            409,
        )


def build_authorization_url(user_id: uuid.UUID) -> str:
    _require_oauth_configured()
    return f"{GOOGLE_AUTH_URL}?{urlencode({
        'client_id': settings.google_oauth_client_id,
        'redirect_uri': settings.google_oauth_callback_url,
        'response_type': 'code',
        'scope': ' '.join(GOOGLE_OAUTH_SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
        'state': create_oauth_state(user_id),
    })}"


def _oauth_error(response: httpx.Response, fallback: str) -> AppError:
    try:
        payload = response.json()
        code = str(payload.get("error") or "")
    except (ValueError, AttributeError):
        code = ""
    if code == "invalid_grant":
        return AppError(
            "GOOGLE_OAUTH_REVOKED",
            "Quyền Google đã hết hạn hoặc bị thu hồi. Hãy kết nối lại.",
            409,
        )
    return AppError("GOOGLE_OAUTH_FAILED", fallback, 502)


async def exchange_authorization_code(
    db: AsyncSession,
    *,
    code: str,
    connected_by_user_id: uuid.UUID,
) -> GoogleOAuthConnection:
    _require_oauth_configured()
    timeout = httpx.Timeout(settings.google_api_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_callback_url,
                "grant_type": "authorization_code",
            },
        )
        if response.is_error:
            raise _oauth_error(response, "Google không đổi được mã đăng nhập.")
        payload = response.json()
        access_token = str(payload.get("access_token") or "")
        refresh_token = str(payload.get("refresh_token") or "")
        if not access_token or not refresh_token:
            raise AppError(
                "GOOGLE_OAUTH_REFRESH_TOKEN_MISSING",
                "Google không cấp refresh token. Hãy thu hồi quyền ZBridge rồi kết nối lại.",
                409,
            )
        userinfo = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo.is_error:
            raise _oauth_error(userinfo, "Không đọc được tài khoản Google vừa kết nối.")
        email = str(userinfo.json().get("email") or "").strip().lower()
        if not email:
            raise AppError(
                "GOOGLE_OAUTH_EMAIL_MISSING", "Google không trả về email tài khoản.", 502
            )

    scopes = str(payload.get("scope") or " ".join(GOOGLE_OAUTH_SCOPES)).split()
    if GOOGLE_DRIVE_SCOPE not in scopes:
        raise AppError(
            "GOOGLE_DRIVE_SCOPE_MISSING",
            "Tài khoản chưa cấp quyền Google Drive. Hãy kết nối lại và cho phép quyền Drive.",
            409,
        )
    connection = await db.get(GoogleOAuthConnection, 1, with_for_update=True)
    now = datetime.now(UTC)
    if connection is None:
        connection = GoogleOAuthConnection(
            id=1,
            email=email,
            encrypted_refresh_token=encrypt_refresh_token(refresh_token),
            scopes=scopes,
            connected_by_user_id=connected_by_user_id,
            connected_at=now,
            last_verified_at=now,
        )
        db.add(connection)
    else:
        connection.email = email
        connection.encrypted_refresh_token = encrypt_refresh_token(refresh_token)
        connection.scopes = scopes
        connection.connected_by_user_id = connected_by_user_id
        connection.connected_at = now
        connection.last_verified_at = now
        connection.last_error = None
    await db.commit()
    await db.refresh(connection)
    return connection


async def disconnect_google(db: AsyncSession) -> None:
    connection = await db.get(GoogleOAuthConnection, 1)
    if connection is not None:
        try:
            refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token)
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(GOOGLE_REVOKE_URL, params={"token": refresh_token})
        except (AppError, httpx.HTTPError):
            # Local disconnect must still succeed when Google is temporarily
            # unavailable or an already-revoked token cannot be decrypted.
            pass
    await db.execute(delete(GoogleOAuthConnection).where(GoogleOAuthConnection.id == 1))
    await db.commit()


class GoogleOAuthTokenProvider:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._expires_at: datetime | None = None
        self._connection_updated_at: datetime | None = None

    async def access_token(self) -> str:
        _require_oauth_configured()
        async with self._lock:
            async with SessionLocal() as db:
                connection = await db.get(GoogleOAuthConnection, 1)
                if connection is None:
                    raise AppError(
                        "GOOGLE_OAUTH_NOT_CONNECTED",
                        "Chưa kết nối tài khoản Google cho công cụ chuyển đổi.",
                        409,
                    )
                now = datetime.now(UTC)
                updated_at = connection.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=UTC)
                if (
                    self._access_token
                    and self._expires_at
                    and self._expires_at > now + timedelta(minutes=2)
                    and self._connection_updated_at == updated_at
                ):
                    return self._access_token
                refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token)
                timeout = httpx.Timeout(settings.google_api_timeout_seconds, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        GOOGLE_TOKEN_URL,
                        data={
                            "client_id": settings.google_oauth_client_id,
                            "client_secret": settings.google_oauth_client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                if response.is_error:
                    error = _oauth_error(response, "Không làm mới được quyền truy cập Google.")
                    connection.last_error = error.message
                    await db.commit()
                    raise error
                payload = response.json()
                access_token = str(payload.get("access_token") or "")
                if not access_token:
                    raise AppError(
                        "GOOGLE_OAUTH_RESPONSE_INVALID",
                        "Google không trả về access token hợp lệ.",
                        502,
                    )
                rotated_refresh_token = str(payload.get("refresh_token") or "")
                if rotated_refresh_token:
                    connection.encrypted_refresh_token = encrypt_refresh_token(
                        rotated_refresh_token
                    )
                connection.last_verified_at = now
                connection.last_error = None
                await db.commit()
                await db.refresh(connection)
                refreshed_updated_at = connection.updated_at
                if refreshed_updated_at.tzinfo is None:
                    refreshed_updated_at = refreshed_updated_at.replace(tzinfo=UTC)
                self._access_token = access_token
                self._expires_at = now + timedelta(
                    seconds=max(60, int(payload.get("expires_in") or 3600))
                )
                self._connection_updated_at = refreshed_updated_at
                return access_token


google_oauth_tokens = GoogleOAuthTokenProvider()


async def google_connection_status(db: AsyncSession) -> dict[str, object]:
    connection = await db.scalar(select(GoogleOAuthConnection).where(GoogleOAuthConnection.id == 1))
    return {
        "configured": bool(
            settings.google_oauth_client_id and settings.google_oauth_client_secret
        ),
        "connected": connection is not None,
        "email": connection.email if connection else None,
        "connected_at": connection.connected_at if connection else None,
        "last_verified_at": connection.last_verified_at if connection else None,
        "last_error": connection.last_error if connection else None,
        "redirect_uri": settings.google_oauth_callback_url,
    }
