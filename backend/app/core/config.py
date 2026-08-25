from functools import lru_cache
from typing import Literal

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
    mention_classifier_interval_seconds: int = 5
    debt_reminder_scheduler_interval_seconds: int = 60
    # Mention classifier LLM. FPT Cloud / DeepSeek-V4-Flash is the default:
    # backend/bench measured zero wrong skips at every threshold and 48 of 51
    # worthwhile skips, against 36 of 51 and two wrong skips for gpt-5.4-nano,
    # at roughly 40% of the cost. LLM_PROVIDER=openai is the way back.
    llm_provider: Literal["fptcloud", "openai"] = "fptcloud"
    llm_base_url: str = "https://mkp-api.fptcloud.com"
    llm_model: str = "DeepSeek-V4-Flash"
    llm_timeout_seconds: float = 30.0
    # A mention is allowed to start/continue a loop only on an affirmative model
    # verdict. This intentionally fails closed: ACK/FYI/UNCERTAIN never tag,
    # regardless of their confidence.
    llm_mention_confidence: float = 0.65
    # The price trigger asks the opposite question, so this is the confidence
    # needed to TAG rather than to skip. Kept separate because the two decisions
    # are calibrated against different costs: a wrong skip loses a task, a wrong
    # price tag spams the customer's group.
    llm_price_confidence: float = 0.65
    fptai_api_key: str = ""
    openai_api_key: str = ""
    mention_context_messages: int = 15
    mention_context_retention_hours: int = 24
    mention_classification_deadline_minutes: int = 15
    google_service_account_file: str | None = None
    # Optional Workspace user used through Domain-Wide Delegation for the
    # Service Account-backed debt-sheet reader. Drive conversion uses OAuth.
    google_impersonated_user: str | None = None
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str | None = None
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
    login_rate_limit_window_seconds: int = 600
    login_rate_limit_ip_attempts: int = 30
    login_rate_limit_account_attempts: int = 20

    @property
    def llm_api_key(self) -> str:
        return self.openai_api_key if self.llm_provider == "openai" else self.fptai_api_key

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.app_url.split(",") if origin.strip()]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def google_oauth_callback_url(self) -> str:
        if self.google_oauth_redirect_uri:
            return self.google_oauth_redirect_uri
        public_url = next(iter(self.cors_origins), "http://localhost:5173")
        return f"{public_url.rstrip('/')}{self.api_prefix}/tools/google/oauth/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
