from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class TokenPayload:
    subject: str
    issued_at: datetime


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(subject: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenPayload | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return TokenPayload(
            subject=str(payload["sub"]),
            issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def decode_access_token(token: str) -> str | None:
    payload = decode_token(token)
    return payload.subject if payload else None
