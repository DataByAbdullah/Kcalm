from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_JWT_SECRET = "change-this-development-secret-at-least-32-bytes"


class Settings(BaseSettings):
    app_name: str = "Kcalm API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: [
        "https://kcalm-app.vercel.app",
        "http://localhost:3000",
    ])
    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5433/kcalm"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    password_reset_token_expire_minutes: int = 30
    frontend_password_reset_url: str = "http://localhost:3000/reset-password"

    rate_limit_register_requests: int = Field(default=5, ge=1)
    rate_limit_register_window_seconds: int = Field(default=60, ge=1)
    rate_limit_login_requests: int = Field(default=10, ge=1)
    rate_limit_login_window_seconds: int = Field(default=60, ge=1)
    rate_limit_forgot_password_requests: int = Field(default=5, ge=1)
    rate_limit_forgot_password_window_seconds: int = Field(default=300, ge=1)
    rate_limit_ai_requests: int = Field(default=30, ge=1)
    rate_limit_ai_window_seconds: int = Field(default=60, ge=1)
    rate_limit_usda_import_requests: int = Field(default=20, ge=1)
    rate_limit_usda_import_window_seconds: int = Field(default=60, ge=1)
    rate_limit_avatar_requests: int = Field(default=10, ge=1)
    rate_limit_avatar_window_seconds: int = Field(default=60, ge=1)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    email_provider: Literal["smtp", "resend"] = "smtp"
    resend_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    resend_from_email: str = Field(default="", repr=False)
    email_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    email_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    email_delivery_deadline_seconds: float = Field(default=20.0, gt=0, le=120)
    password_reset_dispatcher_enabled: bool = True
    password_reset_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    password_reset_max_concurrent_deliveries: int = Field(default=2, ge=1, le=8)
    password_reset_max_pending_jobs: int = Field(default=500, ge=1, le=10000)
    password_reset_max_attempts: int = Field(default=3, ge=1, le=5)
    password_reset_retry_seconds: int = Field(default=30, ge=1, le=300)
    rate_limit_password_reset_recipient_requests: int = Field(default=1, ge=1, le=1)
    rate_limit_password_reset_recipient_window_seconds: int = Field(default=60, ge=1)
    rate_limit_password_reset_provider_requests: int = Field(default=30, ge=1)
    rate_limit_password_reset_provider_window_seconds: int = Field(default=60, ge=1)

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    
    usda_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = 10.0
    openai_image_model: str = "gpt-image-2.6-flare"
    openai_image_size: str = "1024x1024"
    openai_image_quality: str = "medium"
    openai_image_complexity: str = "low"
    openai_image_timeout_seconds: float = Field(default=180.0, gt=0)
    image_storage_bucket: str = ""
    image_storage_region: str = "us-east-1"
    image_storage_endpoint_url: str = ""
    image_storage_public_base_url: str = ""
    image_storage_access_key_id: str = ""
    image_storage_secret_access_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("cors_origins")
    @classmethod
    def require_explicit_cors_origins(cls, origins: list[str]) -> list[str]:
        if "*" in origins:
            raise ValueError("CORS origins must be explicitly listed; wildcard origins are forbidden.")
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
