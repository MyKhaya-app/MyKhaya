import os
from email.utils import parseaddr
from functools import lru_cache
from importlib import metadata as importlib_metadata
from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DISTRIBUTION_NAME = "mykhaya-api"


def _read_repo_version_file() -> str | None:
    here = Path(__file__).resolve()
    candidates = [Path("/app/VERSION"), Path.cwd() / "VERSION"]
    candidates.extend(parent / "VERSION" for parent in here.parents[:4])
    for path in candidates:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def resolve_app_version() -> str:
    """The single source of truth for the running application's version.

    Precedence: an explicit MYKHAYA_VERSION override > installed package
    metadata (infrastructure/scripts/validate_version.py already enforces
    apps/api/pyproject.toml's version stays equal to the repository VERSION
    file, so this is never stale) > the repository VERSION file when running
    from source > a safe non-empty fallback.

    "unknown" is deliberately not treated as a meaningful override even
    though it's present as a literal env var value in several places
    (compose.yml's `${MYKHAYA_VERSION:-unknown}` substitution, the
    Dockerfiles' `ARG MYKHAYA_VERSION=unknown`) — those exist so a build/run
    never fails for lacking the var, not to assert "the version really is
    unknown" over a better source that's actually available.
    """
    override = os.environ.get("MYKHAYA_VERSION", "").strip()
    if override and override != "unknown":
        return override
    try:
        return importlib_metadata.version(_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        pass
    return _read_repo_version_file() or "unknown"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYKHAYA_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    registration_mode: Literal["closed", "invitation_only", "open"] = "open"
    version: str = Field(default_factory=resolve_app_version)
    database_url: str = "postgresql+asyncpg://mykhaya:mykhaya@postgres:5432/mykhaya"
    redis_url: str = "redis://redis:6379/0"
    secret_key: SecretStr = Field(min_length=32)
    public_web_url: str = "http://localhost:8080"
    admin_url: str = "http://admin.localhost:8080"
    status_url: str = "http://status.localhost:8080"
    # The direct-to-API origin for native/bearer clients (ADR 0010) — never
    # proxied through the Next.js web app the way public_web_url/admin_url
    # are. Its host must be listed in trusted_hosts (validated below) but,
    # unlike admin_url, does not need to be in cors_origins: a native client
    # sends no Origin header and isn't subject to CORS at all.
    native_api_url: str = "http://api.localhost:8080"
    cors_origins: list[str] = ["http://localhost:8080"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "api", "api.mykhaya.app"]
    cookie_secure: bool = False
    cookie_domain: str | None = None
    session_minutes: int = Field(default=60 * 24 * 14, ge=15, le=60 * 24 * 30)
    trusted_device_days: int = Field(default=90, ge=7, le=365)
    trusted_device_activity_update_hours: int = Field(default=24, ge=1, le=168)
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # Mirrors PlatformSmtpSettings.connection_security's values (mykhaya.models) exactly
    # — same three options as the Platform-Admin-managed SMTP path, including implicit
    # TLS (typically port 465), not just STARTTLS. Kept as a plain Literal rather than
    # importing that enum: mykhaya.models imports mykhaya.db, which imports
    # mykhaya.config, so importing mykhaya.models here would be circular.
    smtp_connection_security: Literal["none", "starttls", "tls"] = "none"
    # How long to wait on the SMTP connection/handshake before giving up — the worker
    # already retries with backoff on failure, so this only bounds a single attempt.
    smtp_timeout_seconds: int = Field(default=10, ge=1, le=60)
    # Distinct from email_from's address so a bounce/reply mailbox can differ from the
    # sending identity without a Home/Reply-To workaround at the notify() call sites.
    smtp_reply_to: str | None = None
    email_delivery_configured: bool = False
    email_from: str = "MyKhaya <hello@mykhaya.local>"
    email_verification_enabled: bool = True
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None
    push_delivery_configured: bool = False
    # Stripe billing (Phase 3) — deliberately environment-only, unlike SMTP/push,
    # which also support a Platform-Admin-managed DB override. A payment
    # provider's credentials are rotated through infrastructure, not typed into
    # an admin text field, and Stripe secrets never touch the database — see
    # docs/architecture/commercial-entitlements.md#stripe-provider-boundary.
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_publishable_key: str | None = None
    # Price IDs, never monetary amounts — the actual sellable price is always
    # read from Stripe at request time (mykhaya.billing.pricing), so a price
    # change is "update these two IDs", never a code or migration change.
    stripe_family_monthly_price_id: str | None = None
    stripe_family_annual_price_id: str | None = None
    stripe_billing_configured: bool = False
    # Phase 7's deliberate go-live gate — deployment configuration, not a
    # Platform Control Centre toggle (see "Do not implement a remote live
    # toggle casually" in docs/architecture/commercial-entitlements.md). A
    # conscious operator action, separate from Stripe merely being
    # configured: existing Stripe-backed Homes, webhooks, renewals,
    # cancellations, the Customer Portal and reconciliation all keep working
    # regardless of this flag — it only gates *new* Checkout Session
    # creation. Defaults false everywhere, including production, so
    # deploying code never itself enables paid acquisition.
    stripe_billing_acquisition_enabled: bool = False
    request_body_limit: int = Field(default=1_048_576, ge=1024, le=2_097_152)
    avatar_storage_dir: str = "/data/avatars"
    avatar_max_upload_bytes: int = Field(default=5_242_880, ge=1024, le=10_485_760)
    # The `le` ceiling here is a schema safety bound, not a production recommendation
    # — it exists so test/CI environments (which register far more accounts per
    # window than a real deployment ever would) and unusual self-hosted deployments
    # can raise the value if genuinely needed. The defaults above (10/5) are the
    # actual production-appropriate values and are deliberately low; nothing about
    # this field implies 1000 is a sane production setting.
    rate_limit_login: int = Field(default=10, ge=1, le=1000)
    rate_limit_register: int = Field(default=5, ge=1, le=1000)
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
    # How often infrastructure/scripts/backup.sh is expected to run — purely for
    # the Control Centre's "is the latest backup overdue" health signal, not a
    # scheduling mechanism (the application never triggers backups itself).
    backup_expected_interval_hours: int = Field(default=26, ge=1, le=24 * 30)
    status_public_enabled: bool = True
    commit_sha: str = "unknown"
    build_time: str = "unknown"
    build_channel: Literal["development", "stable"] = "development"

    @field_validator("version", mode="before")
    @classmethod
    def resolve_blank_version(cls, value: object) -> object:
        """.env.example ships MYKHAYA_VERSION= (blank) with the comment
        "leave blank to use the repository VERSION file" — but a
        present-but-empty env var is still a value as far as pydantic-settings
        is concerned, so without this it silently overrides the default_factory
        with "", and FastAPI(version="") fails its own non-empty assertion at
        startup. Blank is treated as unset, not as an explicit empty override.
        """
        if isinstance(value, str) and not value.strip():
            return resolve_app_version()
        return value

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

    @model_validator(mode="after")
    def reject_placeholder_production_email_configuration(self) -> "Settings":
        """Only fires once email is actually turned on
        (MYKHAYA_EMAIL_DELIVERY_CONFIGURED=true) — an unconfigured production
        deployment isn't lying about its mail setup, it just hasn't set one up
        yet. Once configured, catches exactly the values this repo ships as
        development-only defaults (Mailpit's service name, the .local
        placeholder domain) so a production deployment can't silently inherit
        them by omission — a real SMTP relay's own hostname/domain will never
        collide with these."""
        if self.environment != "production" or not self.email_delivery_configured:
            return self
        host = self.smtp_host.strip().lower()
        if host in {"mailpit", "localhost", "127.0.0.1", ""} or host.endswith(".local"):
            raise ValueError(
                f"MYKHAYA_SMTP_HOST ({self.smtp_host!r}) looks like a development-only "
                "value and must not be used in production."
            )
        from_email = parseaddr(self.email_from)[1].lower()
        if not from_email or from_email.endswith("@mykhaya.local"):
            raise ValueError(
                f"MYKHAYA_EMAIL_FROM ({self.email_from!r}) must be a real, deliverable "
                "MyKhaya-owned address in production, not the mykhaya.local placeholder."
            )
        return self

    @model_validator(mode="after")
    def validate_stripe_configuration(self) -> "Settings":
        """MYKHAYA_STRIPE_BILLING_CONFIGURED=true is an explicit assertion that
        every piece Stripe billing needs is present — a half-configured
        deployment (flag on, one Price ID missing) fails startup loudly here
        rather than silently misbehaving the first time a Home tries to check
        out. Unconfigured (the default) is a fully supported, valid state:
        Free and Complimentary Homes work with no Stripe setup at all.
        """
        if not self.stripe_billing_configured:
            if self.stripe_billing_acquisition_enabled:
                raise ValueError(
                    "MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED is true but "
                    "MYKHAYA_STRIPE_BILLING_CONFIGURED is false — billing must be fully "
                    "configured before new paid acquisition can be enabled."
                )
            return self
        missing = [
            name
            for name, value in (
                ("MYKHAYA_STRIPE_SECRET_KEY", self.stripe_secret_key),
                ("MYKHAYA_STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret),
                ("MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID", self.stripe_family_monthly_price_id),
                ("MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID", self.stripe_family_annual_price_id),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "MYKHAYA_STRIPE_BILLING_CONFIGURED is true but required settings are "
                f"missing: {', '.join(missing)}."
            )
        secret_value = self.stripe_secret_key.get_secret_value() if self.stripe_secret_key else ""
        is_live_key = secret_value.startswith("sk_live_")
        is_test_key = secret_value.startswith("sk_test_")
        if not is_live_key and not is_test_key:
            raise ValueError(
                "MYKHAYA_STRIPE_SECRET_KEY does not look like a Stripe secret key "
                "(expected it to start with sk_test_ or sk_live_)."
            )
        # Phase 3 is test-mode only (see docs/operations/dev-deployment.md#stripe-sandbox) —
        # a live key anywhere outside production is almost certainly a mistake, and a test
        # key in production would silently take no real payments. Both directions are
        # rejected rather than just the production one, since "wrong environment" is the
        # actual risk, not "which specific environment".
        if self.environment == "production" and is_test_key:
            raise ValueError(
                "MYKHAYA_STRIPE_SECRET_KEY is a test-mode key (sk_test_...) but "
                "MYKHAYA_ENVIRONMENT is production. Live billing is out of scope for this "
                "phase — see docs/operations/dev-deployment.md#stripe-sandbox."
            )
        if self.environment != "production" and is_live_key:
            raise ValueError(
                "MYKHAYA_STRIPE_SECRET_KEY is a live-mode key (sk_live_...) but "
                f"MYKHAYA_ENVIRONMENT is {self.environment!r}. Live Stripe keys must never "
                "be used outside production."
            )
        return self

    @model_validator(mode="after")
    def validate_admin_and_status_url_configuration(self) -> "Settings":
        """Catches exactly the class of bug found during Control Centre MFA
        verification: MYKHAYA_ADMIN_URL/MYKHAYA_STATUS_URL silently drifting
        out of sync with MYKHAYA_TRUSTED_HOSTS/MYKHAYA_CORS_ORIGINS (or just
        being malformed), which doesn't break startup at all — it just makes
        every admin request fail with an opaque 400/403 at request time. This
        fails at startup instead, with a message that names the actual
        mismatch, rather than a browser network tab.

        Skipped in the `test` environment: the isolated test pipeline uses its
        own minimal, deliberately narrow settings and doesn't exercise the
        admin/status subdomains through this config-driven path.
        """
        if self.environment == "test":
            return self

        for field_name, url in (
            ("admin_url", self.admin_url),
            ("status_url", self.status_url),
            ("public_web_url", self.public_web_url),
            ("native_api_url", self.native_api_url),
        ):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError(
                    f"MYKHAYA_{field_name.upper()} ({url!r}) is not a valid http(s) URL."
                )
            if self.environment == "production" and parts.scheme != "https":
                raise ValueError(
                    f"MYKHAYA_{field_name.upper()} must use https in production "
                    f"(got {url!r}) — WebAuthn and secure cookies both depend on it."
                )
            hostname = parts.hostname.casefold()
            if not any(hostname == host.casefold() for host in self.trusted_hosts):
                raise ValueError(
                    f"MYKHAYA_{field_name.upper()}'s host ({parts.hostname!r}) is not listed in "
                    f"MYKHAYA_TRUSTED_HOSTS {self.trusted_hosts!r} — every request to it would "
                    "be rejected by TrustedHostMiddleware. Add it to MYKHAYA_TRUSTED_HOSTS."
                )

        admin_origin = self.admin_webauthn_origin
        if not any(admin_origin.casefold() == origin.casefold() for origin in self.cors_origins):
            raise ValueError(
                f"MYKHAYA_ADMIN_URL's origin ({admin_origin!r}) is not listed in "
                f"MYKHAYA_CORS_ORIGINS {self.cors_origins!r} — every mutating Control Centre "
                "request would be rejected as a disallowed origin. Add it to MYKHAYA_CORS_ORIGINS."
            )
        return self

    @property
    def admin_webauthn_rp_id(self) -> str:
        """WebAuthn Relying Party ID — the registrable domain passkeys are bound
        to. Derived from admin_url (the Control Centre's own origin), never
        hardcoded, so a self-hosted deployment's actual domain is always used."""
        return urlsplit(self.admin_url).hostname or "localhost"

    @property
    def admin_webauthn_origin(self) -> str:
        """WebAuthn expects the exact scheme+host+port the browser used — unlike
        the RP ID, this is the full origin, not just the hostname."""
        parts = urlsplit(self.admin_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def family_webauthn_rp_id(self) -> str:
        """The family app's RP ID, derived from the public web origin."""
        return urlsplit(self.public_web_url).hostname or "localhost"

    @property
    def family_webauthn_origin(self) -> str:
        """Exact browser origin used by the family web/PWA ceremony."""
        parts = urlsplit(self.public_web_url)
        return f"{parts.scheme}://{parts.netloc}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
