import hashlib
import logging

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger("zbridge.login_rate_limit")

_RECORD_FAILURE = """
local ip_value = redis.call('INCR', KEYS[1])
if ip_value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local account_value = redis.call('INCR', KEYS[2])
if account_value == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
return {ip_value, account_value}
"""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _keys(ip: str, email: str) -> tuple[str, str]:
    return (
        f"zbridge:login:ip:{_digest(ip)}",
        f"zbridge:login:account:{_digest(email)}",
    )


async def login_attempt_allowed(ip: str, email: str) -> bool:
    """Check limits before doing expensive password verification.

    Only failed logins are recorded, so successful users behind a shared NAT do
    not consume the IP budget.
    """
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        decode_responses=True,
    )
    ip_key, account_key = _keys(ip, email)
    try:
        ip_count, account_count = await client.mget(ip_key, account_key)
        return (
            int(ip_count or 0) < settings.login_rate_limit_ip_attempts
            and int(account_count or 0) < settings.login_rate_limit_account_attempts
        )
    except Exception:
        # Losing Redis must not lock every operator out.
        logger.warning("LOGIN_RATE_LIMIT_UNAVAILABLE")
        return True
    finally:
        await client.aclose()


async def record_login_failure(ip: str, email: str) -> None:
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        decode_responses=True,
    )
    ip_key, account_key = _keys(ip, email)
    try:
        await client.eval(
            _RECORD_FAILURE,
            2,
            ip_key,
            account_key,
            settings.login_rate_limit_window_seconds,
        )
    except Exception:
        logger.warning("LOGIN_RATE_LIMIT_RECORD_FAILED")
    finally:
        await client.aclose()


async def clear_login_account_limit(email: str) -> None:
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        decode_responses=True,
    )
    try:
        await client.delete(f"zbridge:login:account:{_digest(email)}")
    except Exception:
        logger.warning("LOGIN_RATE_LIMIT_CLEAR_FAILED")
    finally:
        await client.aclose()
