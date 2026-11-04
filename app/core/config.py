from functools import lru_cache

from pydantic import Field, field_validator
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

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

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
