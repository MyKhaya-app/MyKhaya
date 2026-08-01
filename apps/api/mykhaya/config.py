from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_repo_version() -> str:
    here = Path(__file__).resolve()
    candidates = [Path("/app/VERSION"), Path.cwd() / "VERSION"]
    candidates.extend(parent / "VERSION" for parent in here.parents[:4])
    for path in candidates:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return "unknown"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYKHAYA_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    registration_mode: Literal["closed", "invitation_only", "open"] = "open"
    version: str = _read_repo_version()
    database_url: str = "postgresql+asyncpg://mykhaya:mykhaya@postgres:5432/mykhaya"
    redis_url: str = "redis://redis:6379/0"
    secret_key: SecretStr = Field(min_length=32)
    public_web_url: str = "http://localhost:8080"
    admin_url: str = "http://admin.localhost:8080"
    status_url: str = "http://status.localhost:8080"
    cors_origins: list[str] = ["http://localhost:8080"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "api", "api.mykhaya.app"]
    cookie_secure: bool = False
    cookie_domain: str | None = None
    session_minutes: int = Field(default=60 * 24 * 14, ge=15, le=60 * 24 * 30)
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    email_delivery_configured: bool = False
    email_from: str = "MyKhaya <hello@mykhaya.local>"
    email_verification_enabled: bool = True
    request_body_limit: int = Field(default=1_048_576, ge=1024, le=2_097_152)
    rate_limit_login: int = Field(default=10, ge=1, le=100)
    rate_limit_register: int = Field(default=5, ge=1, le=100)
    trusted_proxy_cidrs: list[str] = []
    default_timezone: str = "Europe/London"
    default_locale: str = "en-GB"
    week_start: Literal["monday", "sunday"] = "monday"
    admin_allowed_networks: list[str] = ["127.0.0.0/8", "::1/128"]
    admin_session_idle_minutes: int = Field(default=15, ge=5, le=60)
    admin_session_absolute_minutes: int = Field(default=480, ge=15, le=720)
    admin_recent_auth_minutes: int = Field(default=10, ge=1, le=30)
    admin_mfa_required: bool = True
    admin_bootstrap_enabled: bool = False
    status_public_enabled: bool = True
    commit_sha: str = "unknown"
    build_time: str = "unknown"
    build_channel: Literal["development", "stable"] = "development"

    @field_validator(
        "cors_origins",
        "trusted_hosts",
        "trusted_proxy_cidrs",
        "admin_allowed_networks",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("trusted_proxy_cidrs", "admin_allowed_networks")
    @classmethod
    def validate_networks(cls, value: list[str]) -> list[str]:
        for network in value:
            ip_network(network, strict=False)
        return value

    @field_validator("secret_key")
    @classmethod
    def reject_default_secret(cls, value: SecretStr) -> SecretStr:
        lowered = value.get_secret_value().lower()
        if any(word in lowered for word in ("changeme", "development-only", "example-secret")):
            raise ValueError("MYKHAYA_SECRET_KEY must not be a documented placeholder")
        return value

    @field_validator("cookie_secure")
    @classmethod
    def secure_cookie_in_production(cls, value: bool, info: object) -> bool:
        data = getattr(info, "data", {})
        if data.get("environment") == "production" and not value:
            raise ValueError("MYKHAYA_COOKIE_SECURE must be true in production")
        return value

    @model_validator(mode="after")
    def secure_admin_production_defaults(self) -> "Settings":
        if self.environment == "production":
            if self.cookie_domain is not None:
                raise ValueError(
                    "MYKHAYA_COOKIE_DOMAIN must be unset so cookies remain host-scoped"
                )
            if (
                "admin_allowed_networks" not in self.model_fields_set
                or not self.admin_allowed_networks
            ):
                raise ValueError("MYKHAYA_ADMIN_ALLOWED_NETWORKS is required in production")
            if not self.admin_mfa_required:
                raise ValueError("MYKHAYA_ADMIN_MFA_REQUIRED must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
