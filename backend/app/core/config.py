from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "ZBridge API"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://zbridge:zbridge@localhost:5432/zbridge"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default="dev-only-change-this-secret-at-least-32-bytes", min_length=32)
    jwt_expire_minutes: int = 480
    app_url: str = "http://localhost:5173"
    cookie_secure: bool = False
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "change-this-password"
    zalo_gateway_url: str = "http://localhost:3001"
    zalo_gateway_secret: str = "dev-gateway-secret"
    zalo_event_secret: str = "dev-zalo-event-secret"
    gateway_timeout_seconds: float = 30.0
    mention_scheduler_interval_seconds: int = 15
    debt_reminder_scheduler_interval_seconds: int = 60
    google_service_account_file: str | None = None
    google_api_timeout_seconds: float = 90.0

    # Operator alerting to Telegram.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_timeout_seconds: float = 10.0
    alert_min_severity: str = "WARNING"
    alert_dedup_window_seconds: int = 900
    # Base URL used in alert links. APP_URL is often localhost, which Telegram
    # refuses to linkify, so this can point at a LAN IP or public domain.
    alert_link_base_url: str = ""
    health_check_url: str = "http://backend:8000/health"
    alert_heartbeat_interval_seconds: int = 120
    login_failure_alert_threshold: int = 5
    login_failure_window_seconds: int = 600

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.app_url.split(",") if origin.strip()]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
