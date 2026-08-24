import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.errors import AppError
from app.db.database import Base
from app.models import GoogleOAuthConnection
from app.services.google_oauth_service import (
    GOOGLE_DRIVE_SCOPE,
    build_authorization_url,
    create_oauth_state,
    decode_oauth_state,
    decrypt_refresh_token,
    encrypt_refresh_token,
    exchange_authorization_code,
    google_connection_status,
)


def test_google_refresh_token_is_encrypted_at_rest() -> None:
    raw = "refresh-token-that-must-not-be-stored-as-plain-text"
    encrypted = encrypt_refresh_token(raw)

    assert raw not in encrypted
    assert decrypt_refresh_token(encrypted) == raw


def test_google_oauth_state_is_signed_and_bound_to_user() -> None:
    user_id = uuid.uuid4()
    state = create_oauth_state(user_id)

    assert decode_oauth_state(state) == user_id


def test_google_authorization_url_requests_offline_drive_access(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        settings,
        "google_oauth_redirect_uri",
        "https://zbridge.example/api/tools/google/oauth/callback",
    )

    query = parse_qs(urlparse(build_authorization_url(uuid.uuid4())).query)

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert GOOGLE_DRIVE_SCOPE in query["scope"][0].split()
    assert query["redirect_uri"] == [
        "https://zbridge.example/api/tools/google/oauth/callback"
    ]


async def test_google_connection_status_never_returns_refresh_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(
            GoogleOAuthConnection(
                id=1,
                email="owner@example.com",
                encrypted_refresh_token=encrypt_refresh_token("very-secret-refresh-token"),
                scopes=[GOOGLE_DRIVE_SCOPE],
            )
        )
        await db.commit()
        payload = await google_connection_status(db)

    assert payload["connected"] is True
    assert payload["email"] == "owner@example.com"
    assert "token" not in payload
    await engine.dispose()


async def test_oauth_callback_exchange_stores_only_encrypted_refresh_token(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        settings,
        "google_oauth_redirect_uri",
        "https://zbridge.example/api/tools/google/oauth/callback",
    )

    async def fake_post(_self, url, **_kwargs):
        assert url.endswith("/token")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token-from-google",
                "scope": f"openid email {GOOGLE_DRIVE_SCOPE}",
                "expires_in": 3600,
            },
        )

    async def fake_get(_self, url, **_kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"email": "owner@example.com"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        connection = await exchange_authorization_code(
            db,
            code="one-time-code",
            connected_by_user_id=uuid.uuid4(),
        )

        assert connection.email == "owner@example.com"
        assert "refresh-token-from-google" not in connection.encrypted_refresh_token
        assert decrypt_refresh_token(connection.encrypted_refresh_token) == (
            "refresh-token-from-google"
        )
    await engine.dispose()


async def test_oauth_callback_rejects_connection_without_drive_scope(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")

    async def fake_post(_self, url, **_kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token-from-google",
                "scope": "openid email",
            },
        )

    async def fake_get(_self, url, **_kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"email": "owner@example.com"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        with pytest.raises(AppError, match="chưa cấp quyền Google Drive") as caught:
            await exchange_authorization_code(
                db,
                code="one-time-code",
                connected_by_user_id=uuid.uuid4(),
            )
        assert caught.value.code == "GOOGLE_DRIVE_SCOPE_MISSING"
        assert await db.get(GoogleOAuthConnection, 1) is None
    await engine.dispose()
