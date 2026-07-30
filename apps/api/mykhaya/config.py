from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYKHAYA_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://mykhaya:mykhaya@postgres:5432/mykhaya"
    redis_url: str = "redis://redis:6379/0"
    secret_key: SecretStr = Field(min_length=32)
    public_web_url: str = "http://localhost:8080"
    cors_origins: list[str] = ["http://localhost:8080"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "api", "api.mykhaya.app"]
    cookie_secure: bool = False
    cookie_domain: str | None = None
    session_minutes: int = Field(default=60 * 24 * 14, ge=15, le=60 * 24 * 30)
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    email_from: str = "MyKhaya <hello@mykhaya.local>"
    request_body_limit: int = Field(default=1_048_576, ge=1024, le=2_097_152)

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("secret_key")
    @classmethod
    def reject_default_secret(cls, value: SecretStr) -> SecretStr:
        lowered = value.get_secret_value().lower()
        if any(word in lowered for word in ("changeme", "development-only", "example-secret")):
            raise ValueError("MYKHAYA_SECRET_KEY must not be a documented placeholder")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

