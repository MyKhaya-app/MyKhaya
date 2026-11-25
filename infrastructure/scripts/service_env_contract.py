#!/usr/bin/env python3
"""Service-specific configuration contract and static validator (F-03).

This module is the single machine-readable source for which variables each
backend service may receive from the DEV configuration root
(``MYKHAYA_DEV_CONFIG_ROOT``, normally ``/etc/mykhaya/dev``) and, with
``--profile prod``, from the PROD root (``/etc/mykhaya/prod``). The allow-lists
are derived from what the code actually reads (see
docs/operations/service-configuration-contracts.md), not from convenience.

The validator never prints, hashes or logs a value. Values are only compared
with each other in memory (for example, that the application database password
in api.env matches the one PostgreSQL was initialised with) and reported by
variable name.

Usage:
    service_env_contract.py [--profile dev|prod] --root ROOT --probe-image IMAGE
                            [--repo-root PATH] [--skip-permissions]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

P = "MYKHAYA_"

# --- Values compose.dev.yml/compose.yml already pin ---------------------------
# Environment entries beat env_file entries, so a pinned name placed in a
# service file would silently have no effect. They are rejected in service
# files; host-specific pinned values are interpolated from compose.env.
PINNED_BY_COMPOSE = frozenset(
    P + name
    for name in (
        "ENVIRONMENT", "BUILD_CHANNEL", "REGISTRATION_MODE", "COOKIE_SECURE",
        "PUBLIC_WEB_URL", "ADMIN_URL", "STATUS_URL", "NATIVE_API_URL", "CORS_ORIGINS",
        "TRUSTED_HOSTS", "TRUSTED_PROXY_CIDRS", "ADMIN_ALLOWED_NETWORKS",
        "ADMIN_MFA_REQUIRED", "DEFAULT_TIMEZONE", "DEFAULT_LOCALE", "WEEK_START",
        "VERSION", "COMMIT_SHA", "BUILD_TIME", "SYSLOG_DEBUG",
    )
)

# --- Variable groups ----------------------------------------------------------
CORE = {P + "DATABASE_URL", P + "REDIS_URL", P + "SECRET_KEY"}
FIELD_KEY_ENV_FALLBACK = {P + "FIELD_ENCRYPTION_KEYS", P + "BLIND_INDEX_KEYS"}
SMTP = {P + n for n in (
    "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_CONNECTION_SECURITY",
    "SMTP_TIMEOUT_SECONDS", "SMTP_REPLY_TO", "EMAIL_DELIVERY_CONFIGURED", "EMAIL_FROM",
)}
VAPID = {P + n for n in (
    "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT", "PUSH_DELIVERY_CONFIGURED",
)}
APNS = {P + n for n in (
    "APNS_DELIVERY_CONFIGURED", "APNS_TEAM_ID", "APNS_KEY_ID", "APNS_BUNDLE_ID",
    "APNS_PRIVATE_KEY",
)}
FCM = {P + n for n in (
    "FCM_DELIVERY_CONFIGURED", "FCM_PROJECT_ID", "FCM_CLIENT_EMAIL", "FCM_PRIVATE_KEY",
)}
APPLE = {P + n for n in (
    "APPLE_SIGN_IN_ENABLED", "APPLE_CLIENT_ID", "APPLE_NATIVE_CLIENT_ID", "APPLE_SERVICE_ID",
    "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY", "APPLE_PRIVATE_KEY_FILE",
    "APPLE_REDIRECT_URI", "NATIVE_APPLE_RETURN_URI", "APPLE_AUTHORIZE_URL",
    "APPLE_TOKEN_URL", "APPLE_JWKS_URL",
)}
GOOGLE = {P + n for n in (
    "GOOGLE_SIGN_IN_ENABLED", "GOOGLE_CLIENT_ID", "GOOGLE_NATIVE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "NATIVE_GOOGLE_RETURN_URI",
    "GOOGLE_AUTHORIZE_URL", "GOOGLE_TOKEN_URL", "GOOGLE_JWKS_URL",
)}
STRIPE_MONITORING = {P + n for n in (
    "STRIPE_BILLING_CONFIGURED", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "STRIPE_FAMILY_MONTHLY_PRICE_ID", "STRIPE_FAMILY_ANNUAL_PRICE_ID",
)}
STRIPE = STRIPE_MONITORING | {P + n for n in (
    "STRIPE_PUBLISHABLE_KEY", "STRIPE_ULTIMATE_MONTHLY_PRICE_ID",
    "STRIPE_ULTIMATE_ANNUAL_PRICE_ID", "STRIPE_BILLING_ACQUISITION_ENABLED",
    "STRIPE_ULTIMATE_ACQUISITION_ENABLED",
)}
DVLA_MONITORING = {P + n for n in (
    "DVLA_ENVIRONMENT", "DVLA_UAT_ENDPOINT", "DVLA_UAT_API_KEY",
    "DVLA_PRODUCTION_ENDPOINT", "DVLA_PRODUCTION_API_KEY",
)}
DVLA_SELECTED = {
    "uat": {P + "DVLA_UAT_ENDPOINT", P + "DVLA_UAT_API_KEY"},
    "production": {P + "DVLA_PRODUCTION_ENDPOINT", P + "DVLA_PRODUCTION_API_KEY"},
}
DVLA = DVLA_MONITORING | {P + n for n in (
    "DRIVEWAY_LOOKUP_RATE_LIMIT", "DVLA_REQUEST_BUDGET_PER_SECOND",
    "DVLA_REFRESH_COOLDOWN_SECONDS", "DVLA_REFRESH_FAILURE_BACKOFF_SECONDS",
    "DVLA_REFRESH_LOCK_SECONDS",
)}
# Exactly what monitoring/checks.py reads: dvsa_enabled, dvsa_configured
# (token URL, client ID, client secret, API key) and the two probed hostnames.
DVSA_MONITORING = {P + n for n in (
    "DVSA_ENABLED", "DVSA_API_BASE_URL", "DVSA_TOKEN_URL",
    "DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET", "DVSA_API_KEY",
)}
DVSA = DVSA_MONITORING | {P + n for n in (
    "DVSA_ENVIRONMENT", "DVSA_SCOPE",
    "DVSA_TIMEOUT_SECONDS", "DVSA_REFRESH_HOURS", "DVSA_REFRESH_RATE_LIMIT",
    "DVSA_ARBITRARY_LOOKUP_ENABLED", "DVSA_ARBITRARY_LOOKUP_RATE_LIMIT",
)}
MONITORING_TARGETS = {P + "MONITORING_WEB_URL", P + "MONITORING_API_URL",
                      P + "MONITORING_WATCHDOG_FAIL_SUFFIX"}
API_ONLY = {P + n for n in (
    "SESSION_MINUTES", "BROWSER_MFA_HANDOFF_ENABLED", "TRUSTED_DEVICE_DAYS",
    "TRUSTED_DEVICE_ACTIVITY_UPDATE_HOURS", "COOKIE_DOMAIN", "SUPPORT_NOTIFICATION_EMAIL",
    "VEHICLE_PHOTO_STORAGE_DIR", "VEHICLE_PHOTO_MAX_UPLOAD_BYTES", "REQUEST_BODY_LIMIT",
    "AVATAR_STORAGE_DIR", "AVATAR_MAX_UPLOAD_BYTES", "SUPPORT_ATTACHMENT_STORAGE_DIR",
    "SUPPORT_ATTACHMENT_MAX_UPLOAD_BYTES", "MEAL_IMAGE_STORAGE_DIR",
    "MEAL_IMAGE_MAX_UPLOAD_BYTES", "HOME_MIGRATION_STORAGE_DIR", "LEGAL_EVIDENCE_STORAGE_DIR",
    "VEHICLE_REPORT_MAX_PDF_BYTES", "VEHICLE_REPORT_EMAIL_ENABLED",
    "VEHICLE_REPORT_ASSETS_DIR", "HOME_MIGRATION_PACKAGE_TTL_HOURS", "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_REGISTER", "BETA_WAITLIST_DAILY_CAP", "ADMIN_SESSION_IDLE_MINUTES",
    "ADMIN_SESSION_ABSOLUTE_MINUTES", "ADMIN_RECENT_AUTH_MINUTES", "ADMIN_BOOTSTRAP_ENABLED",
    "BACKUP_EXPECTED_INTERVAL_HOURS", "STATUS_PUBLIC_ENABLED", "EMAIL_VERIFICATION_ENABLED",
    "DOCS_SYNC_SOURCE_DIR", "DOCS_SYNC_BRANCH", "LEGAL_TEST_MODE_PRODUCTION_ALLOWED",
)}
BOOTSTRAP_PASSWORDS = {P + "POSTGRES_ADMIN_PASSWORD", P + "MIGRATION_DB_PASSWORD",
                       P + "DB_PASSWORD", "POSTGRES_PASSWORD"}

# --- Per-file contracts -------------------------------------------------------


@dataclass(frozen=True)
class FileContract:
    name: str
    allowed: frozenset[str]
    required: frozenset[str] = frozenset()
    # Forbidden names get a specific "must not receive" message; anything else
    # outside `allowed` is still rejected as "not in this file's contract".
    forbidden: frozenset[str] = frozenset()
    secret_bearing: bool = True
    consumers: tuple[str, ...] = ()


COMMON = FileContract(
    "common.env",
    allowed=frozenset({P + "SENSITIVE_FIELD_KEYS_REQUIRED", P + "FIELD_ENCRYPTION_KEYS_FILE",
                       P + "BLIND_INDEX_KEYS_FILE", P + "DRIVEWAY_FIELD_ENCRYPTION_WRITE",
                       P + "DRIVEWAY_FIELD_ENCRYPTION_READ", P + "MONITORING_ENABLED"}),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | CORE | SMTP | VAPID | APNS | FCM | APPLE | GOOGLE
                        | STRIPE | DVLA | DVSA | FIELD_KEY_ENV_FALLBACK
                        | {P + "MONITORING_WATCHDOG_URL"}),
    secret_bearing=False,
    consumers=("api", "worker", "scheduler"),
)
API = FileContract(
    "api.env",
    allowed=frozenset(CORE | FIELD_KEY_ENV_FALLBACK | SMTP | VAPID | FCM | APPLE | GOOGLE
                      | STRIPE | DVLA | DVSA | MONITORING_TARGETS | API_ONLY),
    required=frozenset(CORE),
    # APNs is delivered by the worker only (compose.yml blanks it for api);
    # the external dead-man's switch is pinged by the scheduler's full cycle only.
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | APNS | {P + "MONITORING_WATCHDOG_URL"}),
    consumers=("api",),
)
WORKER = FileContract(
    "worker.env",
    allowed=frozenset(CORE | FIELD_KEY_ENV_FALLBACK | SMTP | VAPID | APNS | FCM
                      | {P + "LEGAL_EVIDENCE_STORAGE_DIR", P + "EMAIL_VERIFICATION_ENABLED"}),
    required=frozenset(CORE),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | STRIPE | APPLE | GOOGLE | DVLA | DVSA
                        | {P + "MONITORING_WATCHDOG_URL"}),
    consumers=("worker",),
)
# The scheduler's service-monitoring runner authenticates to SMTP and Stripe and
# decides DVLA/DVSA applicability from credential presence (monitoring/checks.py),
# so those groups are permitted when the matching provider is configured through
# the environment rather than the Platform Control Centre.
SCHEDULER = FileContract(
    "scheduler.env",
    allowed=frozenset(CORE | FIELD_KEY_ENV_FALLBACK | SMTP | STRIPE_MONITORING
                      | DVLA_MONITORING | DVSA_MONITORING | MONITORING_TARGETS
                      | {P + "MONITORING_WATCHDOG_URL", P + "DOCS_SYNC_SOURCE_DIR",
                         P + "DOCS_SYNC_BRANCH", P + "HOME_MIGRATION_PACKAGE_TTL_HOURS",
                         P + "APPLE_SIGN_IN_ENABLED", P + "APPLE_JWKS_URL",
                         P + "GOOGLE_SIGN_IN_ENABLED", P + "GOOGLE_JWKS_URL",
                         # Storage the scheduler's demo-Home expiry and package
                         # purge touch (matches its volume mounts).
                         P + "AVATAR_STORAGE_DIR", P + "MEAL_IMAGE_STORAGE_DIR",
                         P + "VEHICLE_PHOTO_STORAGE_DIR", P + "HOME_MIGRATION_STORAGE_DIR"}),
    required=frozenset(CORE),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | APNS | {
        P + "FCM_PRIVATE_KEY", P + "VAPID_PRIVATE_KEY", P + "APPLE_PRIVATE_KEY",
        P + "APPLE_PRIVATE_KEY_FILE", P + "GOOGLE_CLIENT_SECRET",
        P + "STRIPE_PUBLISHABLE_KEY", P + "STRIPE_BILLING_ACQUISITION_ENABLED",
    }),
    consumers=("scheduler",),
)
# MYKHAYA_SECRET_KEY is required only because Alembic constructs the complete
# Settings model at import time; narrowing it needs a separate, approved
# settings change.
MIGRATE = FileContract(
    "migrate.env",
    allowed=frozenset({P + "DATABASE_URL", P + "SECRET_KEY"}),
    required=frozenset({P + "DATABASE_URL", P + "SECRET_KEY"}),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | SMTP | VAPID | APNS | FCM | APPLE | GOOGLE | STRIPE
                        | DVLA | DVSA | FIELD_KEY_ENV_FALLBACK | {P + "REDIS_URL"}),
    consumers=("migrate",),
)
POSTGRES = FileContract(
    "postgres.env",
    allowed=frozenset({"POSTGRES_PASSWORD", P + "MIGRATION_DB_PASSWORD", P + "DB_PASSWORD"}),
    required=frozenset({"POSTGRES_PASSWORD", P + "MIGRATION_DB_PASSWORD", P + "DB_PASSWORD"}),
    consumers=("postgres",),
)
# compose.env is Compose's interpolation file (passed with --env-file). It holds
# host-specific, non-secret values only; it replaces the root .env as the
# interpolation source and is never loaded into a container.
COMPOSE = FileContract(
    "compose.env",
    allowed=frozenset({P + n for n in (
        "DEV_BIND_ADDRESS", "DEV_HOST_PORT", "DEV_MAILPIT_PORT", "DEV_PROXY_TRUSTED_CIDRS",
        "TRUSTED_PROXY_CIDRS", "ADMIN_ALLOWED_NETWORKS", "DEFAULT_TIMEZONE",
        "DEFAULT_LOCALE", "WEEK_START", "FIELD_KEYS_HOST_DIR", "APPLE_KEY_HOST_DIR",
        "SYSLOG_DEBUG", "EMAIL_DELIVERY_CONFIGURED",
        # Read by the backup scripts on the host, never by a container.
        "BACKUP_DIR", "BACKUP_AGE_RECIPIENTS_FILE",
    )}),
    required=frozenset({P + "ADMIN_ALLOWED_NETWORKS", P + "FIELD_KEYS_HOST_DIR",
                        P + "APPLE_KEY_HOST_DIR"}),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | CORE | SMTP | VAPID | APNS | FCM | APPLE | GOOGLE
                        | STRIPE | DVLA | DVSA | FIELD_KEY_ENV_FALLBACK
                        | {P + "MONITORING_WATCHDOG_URL"}),
    secret_bearing=False,
)
CONTRACTS = (COMMON, API, WORKER, SCHEDULER, MIGRATE, POSTGRES, COMPOSE)

# Env files each container service loads in compose.dev.service-env.yml.
SERVICE_ENV_FILES = {
    "api": ("common.env", "api.env"),
    "worker": ("common.env", "worker.env"),
    "scheduler": ("common.env", "scheduler.env"),
    "migrate": ("migrate.env",),
    "postgres": ("postgres.env",),
}
SYNTHETIC_TEST_ENV_FILE = ".env.dev.test.example"
JSON_LIST_NAMES = {P + "TRUSTED_PROXY_CIDRS", P + "ADMIN_ALLOWED_NETWORKS"}
PLACEHOLDER_MARKERS = ("CHANGE_ME", "__SET_IN_", "replace-with", "changeme", "example-secret")
PRODUCTION_MARKERS = ("/etc/mykhaya/prod", "/etc/mykhaya/production")
PRODUCTION_APNS_BUNDLE_ID = "app.mykhaya.mobile.prod"
PRODUCTION_FCM_PROJECT_ID = "mykhaya-prod"
# DEV identities the PROD profile rejects (docs/mobile, .env.dev.example).
DEVELOPMENT_MARKERS = ("/etc/mykhaya/dev", "/etc/mykhaya/development")
DEVELOPMENT_APNS_BUNDLE_ID = "app.mykhaya.mobile"
DEVELOPMENT_FCM_PROJECT_ID = "mykhaya-dev-faf55"
DEVELOPMENT_HOST = "dev.mykhaya.app"
DEVELOPMENT_NATIVE_SCHEME = "app.mykhaya.mobile://"
APP_DB_USER = "mykhaya_app"
MIGRATION_DB_USER = "mykhaya_migrator"
SECRET_FILES = ("api.env", "worker.env", "scheduler.env", "migrate.env", "postgres.env")


# --- Parsing --------------------------------------------------------------------


# Docker Compose dotenv semantics, verified on Compose 2.33 and 5.1.4:
#   "double" may span lines; \n \t \r \\ \" \$ are decoded, any other
#            backslash sequence is kept literally; $$ -> $; $NAME interpolates.
#   'single' may span lines; only \' is decoded; everything else is literal.
#   unquoted is one line; surrounding whitespace and a " #" comment are removed;
#            backslashes are literal; $$ -> $; $NAME interpolates.
# Compose silently drops a non-assignment line and text after a closing quote.
# This parser refuses those, unterminated quotes and unescaped interpolation
# instead, so a value is never silently truncated or altered.
DOUBLE_QUOTE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "$": "$"}
# Upper-case names only (every MyKhaya setting is). A stray line of base64 key
# material that ends in "=" padding must never be mistaken for an assignment,
# because names, unlike values, appear in reports.
ENV_KEY = re.compile(r"[A-Z_][A-Z0-9_]*")
PEM_BEGIN, PEM_END = "-----BEGIN", "-----END"


def _resolve_dollars(text: str) -> str | None:
    """Apply Compose's `$$` -> `$`; None if a bare `$` would interpolate."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "$":
            if text[i + 1:i + 2] == "$":
                out.append("$")
                i += 2
                continue
            return None
        out.append(text[i])
        i += 1
    return "".join(out)


def parse_env_text(text: str, name: str) -> tuple[dict[str, str], list[str]]:
    """Parse dotenv text exactly as Compose env_file does, or report why not.

    Returns (values, problems). Problems name the file, line and key only,
    never any part of a value.
    """
    values: dict[str, str] = {}
    problems: list[str] = []
    text = text.removeprefix("\ufeff")
    position, line_number, length = 0, 1, len(text)

    def end_of_line(start: int) -> int:
        end = text.find("\n", start)
        return length if end < 0 else end

    while position < length:
        eol = end_of_line(position)
        line = text[position:eol]
        start_line = line_number
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            position, line_number = eol + 1, line_number + 1
            continue
        body = line.lstrip()
        if body.startswith(("export ", "export\t")):
            body = body[len("export"):].lstrip()
        match = ENV_KEY.match(body)
        if not match or not body[match.end():].lstrip(" \t").startswith("="):
            problems.append(f"{name} line {start_line}: not a KEY=VALUE assignment "
                            "(and not inside a quoted value)")
            position, line_number = eol + 1, line_number + 1
            continue
        key = match.group(0)
        after_key = body[match.end():].lstrip(" \t")[1:]
        value_start = eol - len(after_key)  # index of the value text in `text`
        while value_start < eol and text[value_start] in " \t":
            value_start += 1
        quote = text[value_start] if value_start < eol else ""
        if quote in ("\"", "'"):
            index, chars = value_start + 1, []
            while index < length:
                char = text[index]
                if char == "\\" and index + 1 < length:
                    following = text[index + 1]
                    if quote == "\"" and following in DOUBLE_QUOTE_ESCAPES:
                        chars.append("\x00" if following == "$" else DOUBLE_QUOTE_ESCAPES[following])
                        index += 2
                        continue
                    if quote == "'" and following == "'":
                        chars.append("'")
                        index += 2
                        continue
                    chars.append(char)
                    index += 1
                    continue
                if char == quote:
                    break
                chars.append(char)
                index += 1
            line_number += text.count("\n", value_start, min(index, length))
            if index >= length:
                problems.append(f"{name} line {start_line}: {key} has an unterminated "
                                f"{'double' if quote == chr(34) else 'single'}-quoted value")
                break  # nothing after an unterminated quote can be trusted
            rest_end = end_of_line(index)
            rest = text[index + 1:rest_end].rstrip("\r").strip()
            if rest and not rest.startswith("#"):
                problems.append(f"{name} line {line_number}: {key} has text after its closing quote")
            value: str | None = "".join(chars)
            if quote == "\"":
                # \$ was decoded to a placeholder so it is never interpolated.
                value = _resolve_dollars(value)
                if value is not None:
                    value = value.replace("\x00", "$")
            position, line_number = rest_end + 1, line_number + 1
        else:
            raw = text[value_start:eol].rstrip("\r")
            comment = re.search(r"\s#", raw)
            if comment:
                raw = raw[:comment.start()]
            value = _resolve_dollars(raw.strip())
            position, line_number = eol + 1, line_number + 1
            if value is not None and value.startswith(PEM_BEGIN) and PEM_END not in value:
                # An unquoted multiline PEM: Compose keeps only this first line
                # and drops the rest. Consume the block up to its END line
                # without parsing it, so no key material is read as a name.
                while position < length:
                    block_eol = end_of_line(position)
                    ended = PEM_END in text[position:block_eol]
                    position, line_number = block_eol + 1, line_number + 1
                    if ended:
                        break
                problems.append(f"{name} lines {start_line}-{line_number - 1}: {key} is an "
                                "unquoted multiline value (Compose keeps only its first line); "
                                "enclose the whole value in double quotes")
                continue
        if value is None:
            problems.append(f"{name} line {start_line}: {key} contains '$' that Compose would "
                            "interpolate; write a literal dollar as '$$' or single-quote the value")
            continue
        if key in values:
            problems.append(f"{name} line {start_line}: {key} is assigned more than once")
        values[key] = value
    return values, problems


def parse_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse a dotenv file with Compose env_file semantics (see parse_env_text)."""
    return parse_env_text(path.read_bytes().decode("utf-8"), path.name)


def format_env_value(value: str) -> str:
    """Serialise a value so Compose env_file reads back exactly `value`."""
    simple = (
        value == value.strip()
        and "\n" not in value and "\r" not in value
        and not value.startswith(("\"", "'"))
        and re.search(r"\s#", value) is None
    )
    if simple:
        return value.replace("$", "$$")
    escaped = (value.replace("\\", "\\\\").replace("\"", "\\\"")
               .replace("$", "$$").replace("\r", "\\r"))
    return f"\"{escaped}\""


# --- Results ---------------------------------------------------------------------


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _is_production_path(text: str) -> bool:
    lowered = text.replace("\\", "/").lower().rstrip("/")
    return any(lowered == m or lowered.startswith(m + "/") for m in PRODUCTION_MARKERS) or any(
        part in {"prod", "production"} for part in PurePosixPath(lowered).parts
    )


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_development_path(text: str) -> bool:
    """The mirror of _is_production_path, used by the PROD profile."""
    lowered = text.replace("\\", "/").lower().rstrip("/")
    return any(lowered == m or lowered.startswith(m + "/") for m in DEVELOPMENT_MARKERS) or any(
        part in {"dev", "development"} for part in PurePosixPath(lowered).parts
    )


def check_root_location(root: Path, repo_root: Path | None, report: Report,
                        profile: Profile | None = None) -> None:
    profile = profile or DEV
    text = str(root)
    kind = profile.foreign_kind
    if not (root.is_absolute() or text.startswith("/")):
        report.error("configuration root must be an absolute path")
    if profile.foreign_path(text):
        report.error(f"configuration root points at a {kind} path; {profile.label} must use "
                     "its own root")
    if not root.is_dir():
        report.error("configuration root does not exist or is not a directory")
        return
    resolved = root.resolve()
    if profile.foreign_path(str(resolved)):
        report.error(f"configuration root resolves (via a link) to a {kind} path")
    if repo_root is not None and _inside(resolved, repo_root.resolve()):
        report.error("configuration root is inside the repository working tree; "
                     "secrets there could be committed to the public repository")


def check_permissions(path: Path, *, secret: bool, is_dir: bool, report: Report,
                      label: str | None = None) -> None:
    """POSIX mode checks. Secrets: no access for others, no group write."""
    label = label or path.name
    try:
        info = path.lstat()
    except OSError:
        report.error(f"{label}: cannot be inspected")
        return
    if stat.S_ISLNK(info.st_mode):
        report.error(f"{label}: must not be a symbolic link")
        return
    mode = stat.S_IMODE(info.st_mode)
    if mode & stat.S_IWOTH:
        report.error(f"{label}: is writable by other users")
    if mode & stat.S_IWGRP:
        report.error(f"{label}: is writable by its group")
    if secret and mode & (stat.S_IROTH | stat.S_IXOTH):
        report.error(f"{label}: is readable by other users (expected mode 0600/0640"
                     f"{' or 0700/0750 for directories' if is_dir else ''})")
    if hasattr(os, "geteuid"):
        if info.st_uid not in {0, os.geteuid()}:
            report.error(f"{label}: is not owned by root or the deployment account")


def _db_parts(url: str) -> tuple[str, str, str, str, str] | None:
    try:
        parts = urlsplit(url)
        return (parts.scheme, unquote(parts.username or ""), unquote(parts.password or ""),
                parts.hostname or "", parts.path.lstrip("/"))
    except ValueError:
        return None


def check_contract(contract: FileContract, values: dict[str, str], report: Report,
                   profile: Profile | None = None) -> None:
    profile = profile or DEV
    names = set(values)
    # compose.env is the interpolation source that feeds the pinned values.
    pinned = frozenset() if contract is profile.compose_contract else profile.pinned
    forbidden = contract.forbidden - contract.allowed
    for name in sorted(names & pinned):
        report.error(f"{contract.name}: {name} is pinned by {profile.pinned_source}; "
                     "remove it (put host-specific values in compose.env)")
    for name in sorted((names & forbidden) - pinned):
        report.error(f"{contract.name}: {name} must not be supplied to this service")
    for name in sorted(names - contract.allowed - forbidden - pinned):
        report.error(f"{contract.name}: {name} is not part of this file's contract")
    for name in sorted(contract.required - names):
        report.error(f"{contract.name}: required variable {name} is missing")
    for name in sorted(contract.required & names):
        if not values[name]:
            report.error(f"{contract.name}: required variable {name} is empty")
    for name, value in sorted(values.items()):
        if any(marker.lower() in value.lower() for marker in PLACEHOLDER_MARKERS):
            report.error(f"{contract.name}: {name} still contains a documented placeholder")
    for name in sorted(names & profile.json_lists):
        try:
            parsed = json.loads(values[name])
            if not isinstance(parsed, list) or not all(isinstance(i, str) for i in parsed):
                raise ValueError
        except ValueError:
            report.error(f"{contract.name}: {name} must be a JSON array of strings")


def check_cross_file(files: dict[str, dict[str, str]], report: Report,
                     profile: Profile | None = None) -> None:
    profile = profile or DEV
    api, worker, scheduler =files.get("api.env", {}), files.get("worker.env", {}), \
        files.get("scheduler.env", {})
    migrate, postgres = files.get("migrate.env", {}), files.get("postgres.env", {})
    compose = files.get("compose.env", {})

    secret_holders = {n: v for n, v in (("api.env", api), ("worker.env", worker),
                      ("scheduler.env", scheduler), ("migrate.env", migrate))
                      if P + "SECRET_KEY" in v}
    if len({v[P + "SECRET_KEY"] for v in secret_holders.values()}) > 1:
        report.error("MYKHAYA_SECRET_KEY differs between service files; it signs sessions and "
                     "decrypts Control Centre secrets, so every backend service needs the same value")

    redis = {n: v[P + "REDIS_URL"] for n, v in (("api.env", api), ("worker.env", worker),
             ("scheduler.env", scheduler)) if P + "REDIS_URL" in v}
    if len(set(redis.values())) > 1:
        report.error("MYKHAYA_REDIS_URL differs between api, worker and scheduler")

    for name, values in (("api.env", api), ("worker.env", worker), ("scheduler.env", scheduler)):
        if P + "DATABASE_URL" not in values:
            continue
        parts = _db_parts(values[P + "DATABASE_URL"])
        if parts is None or parts[0] != "postgresql+asyncpg":
            report.error(f"{name}: MYKHAYA_DATABASE_URL must be a postgresql+asyncpg URL")
            continue
        if parts[1] != APP_DB_USER:
            report.error(f"{name}: MYKHAYA_DATABASE_URL must use the {APP_DB_USER} role")
        if postgres.get(P + "DB_PASSWORD") and parts[2] != postgres[P + "DB_PASSWORD"]:
            report.error(f"{name}: MYKHAYA_DATABASE_URL password does not match "
                         "MYKHAYA_DB_PASSWORD in postgres.env")
    if P + "DATABASE_URL" in migrate:
        parts = _db_parts(migrate[P + "DATABASE_URL"])
        if parts is None or parts[0] != "postgresql+asyncpg":
            report.error("migrate.env: MYKHAYA_DATABASE_URL must be a postgresql+asyncpg URL")
        else:
            if parts[1] != MIGRATION_DB_USER:
                report.error(f"migrate.env: MYKHAYA_DATABASE_URL must use the {MIGRATION_DB_USER} role")
            if postgres.get(P + "MIGRATION_DB_PASSWORD") and \
                    parts[2] != postgres[P + "MIGRATION_DB_PASSWORD"]:
                report.error("migrate.env: MYKHAYA_DATABASE_URL password does not match "
                             "MYKHAYA_MIGRATION_DB_PASSWORD in postgres.env")
            app = _db_parts(api.get(P + "DATABASE_URL", ""))
            if app and app[3:] != parts[3:]:
                report.error("migrate.env: MYKHAYA_DATABASE_URL targets a different database "
                             "from api.env")
    pg_values = [postgres.get(k) for k in (profile.admin_password_name,
                                           P + "MIGRATION_DB_PASSWORD", P + "DB_PASSWORD")]
    if all(pg_values) and len(set(pg_values)) < 3:
        report.error("postgres.env: administrator, migration and runtime passwords must differ")

    # A provider configured through the environment must be identical wherever
    # it is supplied (worker delivers, scheduler monitors, api serves PCC/tests).
    for group, label in ((SMTP, "SMTP"), (STRIPE_MONITORING, "Stripe"),
                         (DVLA_MONITORING, "DVLA"), (DVSA_MONITORING, "DVSA"),
                         (FCM, "FCM"), (VAPID, "Web Push"), (FIELD_KEY_ENV_FALLBACK, "field key")):
        for other_name, other in (("worker.env", worker), ("scheduler.env", scheduler)):
            for name in sorted(group & set(other) & set(api)):
                if other[name] != api[name]:
                    report.error(f"{other_name}: {name} differs from api.env ({label} "
                                 "configuration must be identical across services)")

    # Monitoring completeness: a provider the API uses through the environment
    # must reach the scheduler too, or its checks silently report "not applicable".
    def truthy(values: dict[str, str], name: str) -> bool:
        return values.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    if scheduler or api:
        required: list[tuple[str, set[str]]] = []
        if truthy(api, P + "EMAIL_DELIVERY_CONFIGURED"):
            required.append(("SMTP", {n for n in SMTP if n in api}))
        if truthy(api, P + "STRIPE_BILLING_CONFIGURED"):
            required.append(("Stripe", set(STRIPE_MONITORING)))
        dvla_env = api.get(P + "DVLA_ENVIRONMENT", "")
        if dvla_env in DVLA_SELECTED and all(api.get(n) for n in DVLA_SELECTED[dvla_env]):
            required.append(("DVLA", {P + "DVLA_ENVIRONMENT"} | DVLA_SELECTED[dvla_env]))
        dvsa_creds = {P + n for n in ("DVSA_TOKEN_URL", "DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET",
                                      "DVSA_API_KEY")}
        if truthy(api, P + "DVSA_ENABLED") and all(api.get(n) for n in dvsa_creds):
            required.append(("DVSA", {n for n in DVSA_MONITORING if n in api}))
        for flag, label in ((P + "APPLE_SIGN_IN_ENABLED", "Apple"),
                            (P + "GOOGLE_SIGN_IN_ENABLED", "Google")):
            if truthy(api, flag) and not truthy(scheduler, flag):
                report.error(f"scheduler.env: {flag} must be true; {label} sign-in is enabled in "
                             "api.env, so scheduler monitoring would report it as not applicable")
        for label, names in required:
            for name in sorted(names - set(scheduler)):
                report.error(f"scheduler.env: {name} is missing; {label} is configured through "
                             "api.env, so scheduler monitoring would report it as not applicable")

    # Scheduler monitoring needs only the selected DVLA environment's endpoint
    # and key (Settings.dvla_active_endpoint / dvla_active_api_key).
    for name in sorted(set(scheduler) & (DVLA_MONITORING - DVLA_SELECTED.get(
            scheduler.get(P + "DVLA_ENVIRONMENT", ""), set()))):
        if name != P + "DVLA_ENVIRONMENT":
            report.error(f"scheduler.env: {name} is not used by the selected DVLA environment; "
                         "the scheduler receives only the active endpoint and key")

    flag = P + "EMAIL_DELIVERY_CONFIGURED"
    if flag in compose and flag in api and compose[flag] != api[flag]:
        report.error("compose.env: MYKHAYA_EMAIL_DELIVERY_CONFIGURED (shown by web) differs from api.env")

    if profile.name == "prod":
        check_production_separation(files, report)
    else:
        check_development_separation(files, report)
    for name, values in files.items():
        for key, prefix in ((P + "APPLE_PRIVATE_KEY_FILE", "/run/secrets/mykhaya-apple/"),
                            (P + "FIELD_ENCRYPTION_KEYS_FILE", "/run/secrets/mykhaya/"),
                            (P + "BLIND_INDEX_KEYS_FILE", "/run/secrets/mykhaya/")):
            if values.get(key) and not values[key].startswith(prefix):
                report.error(f"{name}: {key} must be inside the read-only {prefix} mount")
        if values.get(P + "APPLE_PRIVATE_KEY") and values.get(P + "APPLE_PRIVATE_KEY_FILE"):
            report.error(f"{name}: set either MYKHAYA_APPLE_PRIVATE_KEY or "
                         f"MYKHAYA_APPLE_PRIVATE_KEY_FILE, not both{profile.apple_hint}")


def check_development_separation(files: dict[str, dict[str, str]], report: Report) -> None:
    # DEV/PROD separation markers. Values are inspected, never printed.
    for name, values in files.items():
        if values.get(P + "STRIPE_SECRET_KEY", "").startswith("sk_live_"):
            report.error(f"{name}: MYKHAYA_STRIPE_SECRET_KEY is a live-mode key; DEV must use a "
                         "Stripe sandbox key")
        if values.get(P + "FCM_PROJECT_ID") == PRODUCTION_FCM_PROJECT_ID:
            report.error(f"{name}: MYKHAYA_FCM_PROJECT_ID is the production Firebase project")
        if values.get(P + "APNS_BUNDLE_ID") == PRODUCTION_APNS_BUNDLE_ID:
            report.error(f"{name}: MYKHAYA_APNS_BUNDLE_ID is the production iOS app")
        dvla = values.get(P + "DVLA_ENVIRONMENT")
        if dvla not in {None, "", "uat", "production"}:
            report.error(f"{name}: MYKHAYA_DVLA_ENVIRONMENT must be blank, uat or production")
        for key, value in values.items():
            if key.endswith(("_FILE", "_DIR", "HOST_DIR")) and _is_production_path(value):
                report.error(f"{name}: {key} points at a production path")


def check_production_separation(files: dict[str, dict[str, str]], report: Report) -> None:
    """PROD must never carry DEV identities. Values are inspected, never printed.

    The PROD files are generated from the PROD .env only, so a DEV value can
    only arrive through a mistake in that file; these markers catch the
    identities that would silently misroute users, payments or notifications.
    """
    def truthy(values: dict[str, str], key: str) -> bool:
        return values.get(key, "").strip().lower() in {"1", "true", "yes", "on"}

    for name, values in files.items():
        if values.get(P + "STRIPE_SECRET_KEY", "").startswith("sk_test_"):
            report.error(f"{name}: MYKHAYA_STRIPE_SECRET_KEY is a test-mode key; production "
                         "rejects it at startup")
        project = values.get(P + "FCM_PROJECT_ID", "")
        if project == DEVELOPMENT_FCM_PROJECT_ID:
            report.error(f"{name}: MYKHAYA_FCM_PROJECT_ID is the DEV Firebase project")
        elif truthy(values, P + "FCM_DELIVERY_CONFIGURED") and project != PRODUCTION_FCM_PROJECT_ID:
            report.error(f"{name}: MYKHAYA_FCM_PROJECT_ID must be {PRODUCTION_FCM_PROJECT_ID} "
                         "when FCM delivery is configured")
        if values.get(P + "APNS_BUNDLE_ID") == DEVELOPMENT_APNS_BUNDLE_ID:
            if truthy(values, P + "APNS_DELIVERY_CONFIGURED"):
                report.error(f"{name}: MYKHAYA_APNS_BUNDLE_ID is the DEV iOS app while APNs "
                             "delivery is configured")
            else:
                report.warn(f"{name}: MYKHAYA_APNS_BUNDLE_ID is the Compose default (the DEV iOS "
                            "app); harmless while APNs delivery is off, but set the PROD bundle "
                            "before enabling it")
        dvla = values.get(P + "DVLA_ENVIRONMENT")
        if dvla not in {None, "", "uat", "production"}:
            report.error(f"{name}: MYKHAYA_DVLA_ENVIRONMENT must be blank, uat or production")
        for key, value in values.items():
            if DEVELOPMENT_HOST in value.lower():
                report.error(f"{name}: {key} refers to the DEV host name")
            if value.startswith(DEVELOPMENT_NATIVE_SCHEME):
                report.error(f"{name}: {key} uses the DEV app's native return scheme")
            if key.endswith(("_FILE", "_DIR", "HOST_DIR")) and _is_development_path(value):
                report.error(f"{name}: {key} points at a development path")


# --- Protected key directories ------------------------------------------------
# The field keyrings and the Apple signing key are readable only by the
# containers' service identity (compose.yml mounts them read-only), never by the
# deployment account. Their contents are therefore inspected from inside a
# short-lived container running as that identity, from the locally built API
# image: no network, no capabilities, read-only root filesystem, only the one
# key directory mounted read-only, no environment files. It reports metadata
# only (lstat and an access(2) permission check); nothing ever opens a key.

SERVICE_UID = 10001  # USER 10001:10001 in apps/api/Dockerfile (runtime stage)
SERVICE_GID = 10001
TRUSTED_KEY_OWNERS = frozenset({0, SERVICE_UID})
TRUSTED_KEY_GROUPS = frozenset({0, SERVICE_GID})
KEY_DIRS = {P + "FIELD_KEYS_HOST_DIR": "/run/secrets/mykhaya/",
            P + "APPLE_KEY_HOST_DIR": "/run/secrets/mykhaya-apple/"}
KEY_FILE_SETTINGS = {P + "FIELD_ENCRYPTION_KEYS_FILE": P + "FIELD_KEYS_HOST_DIR",
                     P + "BLIND_INDEX_KEYS_FILE": P + "FIELD_KEYS_HOST_DIR",
                     P + "APPLE_PRIVATE_KEY_FILE": P + "APPLE_KEY_HOST_DIR"}
PROBE_MOUNT = "/probe"
PROBE_TIMEOUT_SECONDS = 60
PROBE_KINDS = frozenset({"directory", "file", "symlink", "other"})
IMAGE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}")

# Runs inside the probe container. Fixed text: it takes no input, follows no
# links (lstat; access() is asked only of regular files and directories), and
# prints numbers and entry names. os.access() is a permission check for the
# service identity, not proof that a key is valid; the services prove that at
# startup.
PROBE_SCRIPT = """
import json, os, stat, sys

def describe(path, name):
    info = os.lstat(path)
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        kind = "symlink"
    elif stat.S_ISDIR(mode):
        kind = "directory"
    elif stat.S_ISREG(mode):
        kind = "file"
    else:
        kind = "other"
    wanted = os.R_OK | os.X_OK if kind == "directory" else os.R_OK
    return {"name": name, "kind": kind, "mode": stat.S_IMODE(mode), "uid": info.st_uid,
            "gid": info.st_gid, "inode": info.st_ino, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "readable": kind in ("file", "directory") and os.access(path, wanted)}

result = {"uid": os.getuid(), "gid": os.getgid(), "groups": sorted(os.getgroups())}
try:
    result["root"] = describe("/probe", ".")
except FileNotFoundError:
    result["error"] = "missing"
except OSError:
    result["error"] = "unavailable"
else:
    try:
        result["entries"] = [describe("/probe/" + n, n) for n in sorted(os.listdir("/probe"))]
    except PermissionError:
        result["error"] = "denied"
    except OSError:
        result["error"] = "unavailable"
sys.stdout.write(json.dumps(result))
"""


class ProbeFailure(Exception):
    """The key-directory probe could not run; the message is safe to print."""


@dataclass(frozen=True)
class KeyEntry:
    name: str
    kind: str
    mode: int
    uid: int
    gid: int
    inode: int
    readable: bool
    # Metadata only (lstat), used to prove key material was not replaced
    # during a PROD cutover. Absent from older probe output.
    size: int | None = None
    mtime_ns: int | None = None


@dataclass(frozen=True)
class KeyDirListing:
    uid: int
    gid: int
    groups: tuple[int, ...]
    root: KeyEntry | None
    entries: tuple[KeyEntry, ...] | None  # None: the service identity cannot list it
    error: str | None = None


def _safe_name(name: str) -> str:
    """Entry names are diagnostic metadata; keep them printable and short."""
    cleaned = "".join(c if c.isprintable() and c not in "\r\n" else "?" for c in name)
    return cleaned if len(cleaned) <= 64 else cleaned[:61] + "..."


def _entry(raw: object, *, root: bool) -> KeyEntry:
    if not isinstance(raw, dict):
        raise ProbeFailure("the probe returned unexpected output")
    name = raw.get("name")
    numbers = [raw.get(k) for k in ("mode", "uid", "gid", "inode")]
    if (not isinstance(name, str) or raw.get("kind") not in PROBE_KINDS
            or not all(type(n) is int and n >= 0 for n in numbers)
            or type(raw.get("readable")) is not bool
            or (name != "." if root else (not name or "/" in name or name in {".", ".."}))):
        raise ProbeFailure("the probe returned unexpected output")
    optional = {k: raw.get(k) for k in ("size", "mtime_ns")}
    if not all(v is None or (type(v) is int and v >= 0) for v in optional.values()):
        raise ProbeFailure("the probe returned unexpected output")
    return KeyEntry(name, raw["kind"], raw["mode"], raw["uid"], raw["gid"], raw["inode"],
                    raw["readable"], optional["size"], optional["mtime_ns"])


def parse_probe_output(text: str) -> KeyDirListing:
    try:
        data = json.loads(text.strip().splitlines()[-1]) if text.strip() else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ProbeFailure("the probe returned unexpected output")
    ids = [data.get("uid"), data.get("gid")]
    groups = data.get("groups")
    error = data.get("error")
    if (not all(type(i) is int for i in ids) or not isinstance(groups, list)
            or not all(type(g) is int for g in groups)
            or error not in {None, "missing", "unavailable", "denied"}):
        raise ProbeFailure("the probe returned unexpected output")
    root = _entry(data["root"], root=True) if "root" in data else None
    entries = None
    if "entries" in data:
        if not isinstance(data["entries"], list):
            raise ProbeFailure("the probe returned unexpected output")
        entries = tuple(_entry(e, root=False) for e in data["entries"])
    if root is None and error is None or error is None and entries is None:
        raise ProbeFailure("the probe returned unexpected output")
    return KeyDirListing(ids[0], ids[1], tuple(groups), root, entries, error)


def probe_command(image: str, source: str, name: str, script: str = PROBE_SCRIPT,
                  user: str = f"{SERVICE_UID}:{SERVICE_GID}") -> list[str]:
    return ["docker", "run", "--rm", "--name", name, "--pull", "never",
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", user,
            "--label", "app.mykhaya.probe=key-directory",
            "--mount", f"type=bind,source={source},target={PROBE_MOUNT},readonly",
            "--workdir", "/", "--entrypoint", "python", image, "-I", "-S", "-B", "-c", script]


def _docker_failure(stderr: str, what: str) -> ProbeFailure:
    """Map Docker's diagnostics to fixed messages; its own text is never echoed."""
    lowered = stderr.lower()
    if "no such image" in lowered or "unable to find image" in lowered:
        return ProbeFailure("the API image is not available locally; build it first "
                            "(the probe never pulls images)")
    if "cannot connect to the docker daemon" in lowered or "permission denied while trying "\
            "to connect" in lowered:
        return ProbeFailure("the Docker daemon is not reachable")
    if "bind source path does not exist" in lowered:
        return ProbeFailure("the directory is not visible to the Docker daemon")
    return ProbeFailure(f"{what} failed")


def verify_probe_image(image: str, run=subprocess.run) -> None:
    """The probe must run as the identity the services actually use."""
    try:
        result = run(["docker", "image", "inspect", "--format", "{{json .Config.User}}", image],
                     capture_output=True, text=True, check=False, timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        raise ProbeFailure("Docker is unavailable") from None
    if result.returncode != 0:
        raise _docker_failure(result.stderr or "no such image", "inspecting the API image")
    try:
        user = json.loads(result.stdout.strip())
    except ValueError:
        user = None
    if user != f"{SERVICE_UID}:{SERVICE_GID}":
        raise ProbeFailure(f"the API image does not run as the expected service identity "
                           f"{SERVICE_UID}:{SERVICE_GID}")


def docker_key_dir_probe(image: str, run=subprocess.run,
                         user: str = f"{SERVICE_UID}:{SERVICE_GID}"):
    """Return a probe that lists one key directory as the service identity
    (or, for PostgreSQL's secret directory, as the postgres user)."""
    if not IMAGE_REFERENCE.fullmatch(image):
        raise ProbeFailure("the API image reference is not valid")
    verified = False

    def probe(source: str) -> KeyDirListing:
        nonlocal verified
        if not source.startswith("/") or any(c in source for c in ',"\r\n'):
            raise ProbeFailure("the path cannot be passed safely to Docker")
        if not verified:
            verify_probe_image(image, run)
            verified = True
        name = f"mykhaya-keydir-probe-{os.getpid()}-{secrets.token_hex(4)}"
        try:
            result = run(probe_command(image, source, name, user=user), capture_output=True, text=True,
                         check=False, timeout=PROBE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            run(["docker", "rm", "-f", name], capture_output=True, text=True, check=False)
            raise ProbeFailure("the probe container timed out") from None
        except (OSError, subprocess.SubprocessError):
            raise ProbeFailure("Docker is unavailable") from None
        if result.returncode != 0:
            raise _docker_failure(result.stderr or "", "the probe container")
        return parse_probe_output(result.stdout)

    return probe


def _deployment_uid() -> int | None:
    return os.geteuid() if hasattr(os, "geteuid") else None


def check_key_material(entry: KeyEntry, label: str, report: Report, *, directory: bool,
                       deployment_uid: int | None) -> None:
    """Ownership and mode policy for key directories and key files only."""
    if entry.kind == "symlink":
        report.error(f"{label}: must not be a symbolic link")
        return
    expected = "directory" if directory else "file"
    if entry.kind != expected:
        report.error(f"{label}: unexpected file type (only regular key files are allowed"
                     f"{'' if directory else ' inside a key directory'})")
        return
    trusted = f"root (0) or the service account ({SERVICE_UID})"
    if deployment_uid not in {None, 0} and entry.uid == deployment_uid:
        report.error(f"{label}: is owned by the deployment account (UID {entry.uid}); "
                     f"key material must be owned by {trusted}")
    elif entry.uid not in TRUSTED_KEY_OWNERS:
        report.error(f"{label}: is owned by untrusted UID {entry.uid}; expected {trusted}")
    if entry.gid not in TRUSTED_KEY_GROUPS:
        report.error(f"{label}: has untrusted group GID {entry.gid}; expected 0 or {SERVICE_GID}")
    if entry.mode & stat.S_IWGRP:
        report.error(f"{label}: is writable by its group (mode {entry.mode:04o})")
    if entry.mode & stat.S_IWOTH:
        report.error(f"{label}: is writable by other users (mode {entry.mode:04o})")
    if entry.mode & (stat.S_IROTH | stat.S_IXOTH):
        report.error(f"{label}: is readable by other users (mode {entry.mode:04o}; expected "
                     f"{'0700/0750' if directory else '0400/0440/0600/0640'})")
    if not directory and entry.mode & (stat.S_ISUID | stat.S_ISGID):
        report.error(f"{label}: has setuid/setgid bits (mode {entry.mode:04o})")
    if not entry.readable:
        report.error(f"{label}: is not {'listable' if directory else 'readable'} by the service "
                     f"account ({SERVICE_UID}:{SERVICE_GID}), so the services could not use it")


def check_unprovisioned_directory(entry: KeyEntry, key: str, report: Report, *,
                                  deployment_uid: int | None) -> None:
    """An empty key directory that nothing is configured to read (PROD only).

    It holds no key material, so read and search bits are irrelevant (Docker
    creates a missing bind source as root:root 0755). Ownership and write
    access are still enforced, because keys may be installed into it later.
    """
    if entry.kind != "directory":
        report.error(f"{key}: must not be a symbolic link" if entry.kind == "symlink"
                     else f"{key}: unexpected file type")
        return
    if deployment_uid not in {None, 0} and entry.uid == deployment_uid:
        report.error(f"{key}: is owned by the deployment account (UID {entry.uid}); "
                     f"expected root (0) or the service account ({SERVICE_UID})")
    elif entry.uid not in TRUSTED_KEY_OWNERS:
        report.error(f"{key}: is owned by untrusted UID {entry.uid}")
    if entry.gid not in TRUSTED_KEY_GROUPS:
        report.error(f"{key}: has untrusted group GID {entry.gid}; expected 0 or {SERVICE_GID}")
    if entry.mode & (stat.S_IWGRP | stat.S_IWOTH):
        report.error(f"{key}: is writable by its group or other users (mode {entry.mode:04o})")
    report.warn(f"{key}: is empty (not provisioned); nothing is configured to read from it. "
                "Install keys only through the documented procedure, which also sets 0750.")


def check_key_directory(key: str, path: Path, probe, report: Report,
                        referenced: set[str], *, allow_unprovisioned: bool = False) -> None:
    label = f"compose.env: {key}"
    try:
        host = path.lstat()
    except FileNotFoundError:
        report.error(f"{label} does not exist on this host")
        return
    except PermissionError:
        report.error(f"{label}: a parent directory denies the deployment account access")
        return
    except OSError:
        report.error(f"{label}: cannot be inspected")
        return
    if stat.S_ISLNK(host.st_mode):
        report.error(f"{label}: must not be a symbolic link")
        return
    if not stat.S_ISDIR(host.st_mode):
        report.error(f"{label}: is not a directory")
        return
    if probe is None:
        report.error(f"{label}: cannot be verified: no API image was given for the key-directory "
                     "probe (--probe-image)")
        return
    try:
        listing = probe(str(path))
    except ProbeFailure as exc:
        report.error(f"{label}: cannot be verified: {exc}")
        return
    if (listing.uid, listing.gid) != (SERVICE_UID, SERVICE_GID):
        report.error(f"{label}: cannot be verified: the probe did not run as "
                     f"{SERVICE_UID}:{SERVICE_GID}")
        return
    if listing.root is None:
        report.error(f"{label}: cannot be verified: the mounted directory was "
                     f"{listing.error or 'unavailable'}")
        return
    root = listing.root
    # Same directory (bind mounts preserve the inode). The probe's ownership and
    # modes are authoritative: they are what the services see. Under Docker
    # user-namespace remapping the owners appear remapped and fail the policy.
    if root.inode != host.st_ino:
        report.error(f"{label}: the probe saw a different directory from the host "
                     "(was it replaced during validation?)")
        return
    deployment_uid = _deployment_uid()
    if allow_unprovisioned and listing.entries == () and not referenced:
        check_unprovisioned_directory(root, key, report, deployment_uid=deployment_uid)
        return
    check_key_material(root, key, report, directory=True, deployment_uid=deployment_uid)
    if listing.entries is None:
        if root.readable:  # access() allowed it but listing still failed
            report.error(f"{label}: cannot be listed by the service account")
        return
    if not listing.entries:
        report.error(f"{label}: is empty; the services would find no keys")
    for entry in listing.entries:
        check_key_material(entry, f"{key}/{_safe_name(entry.name)}", report, directory=False,
                           deployment_uid=deployment_uid)
    present = {e.name for e in listing.entries if e.kind == "file"}
    for name in sorted(referenced - present):
        report.error(f"{key}: {_safe_name(name)} is named by a *_FILE setting but is not a "
                     "regular file in this directory")


def _referenced_key_files(files: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """Key file names the services are configured to read, per host directory."""
    wanted: dict[str, set[str]] = {key: set() for key in KEY_DIRS}
    for values in files.values():
        for setting, key in KEY_FILE_SETTINGS.items():
            value = values.get(setting, "")
            prefix = KEY_DIRS[key]
            if value.startswith(prefix):  # other locations are rejected elsewhere
                wanted[key].add(value[len(prefix):])
    return wanted


def _required_key_dirs(files: dict[str, dict[str, str]]) -> set[str]:
    """Key directories the configuration says must hold keys (PROD profile).

    Sensitive-field keyrings are needed as soon as they are required or any
    Driveway encryption flag is on, even before a *_FILE path is set.
    """
    common = files.get("common.env", {})
    flags = (P + "SENSITIVE_FIELD_KEYS_REQUIRED", P + "DRIVEWAY_FIELD_ENCRYPTION_WRITE",
             P + "DRIVEWAY_FIELD_ENCRYPTION_READ")
    if any(common.get(f, "").strip().lower() in {"1", "true", "yes", "on"} for f in flags):
        return {P + "FIELD_KEYS_HOST_DIR"}
    return set()


def check_secret_dirs(compose: dict[str, str], repo_root: Path | None, check_perms: bool,
                      report: Report, *, probe=None,
                      files: dict[str, dict[str, str]] | None = None,
                      profile: Profile | None = None) -> None:
    profile = profile or DEV
    referenced = _referenced_key_files(files or {})
    required = _required_key_dirs(files or {}) if profile.allow_unprovisioned_keys else set()
    for key in KEY_DIRS:
        value = compose.get(key, "")
        if not value:
            continue
        path = Path(value)
        if not (path.is_absolute() or value.startswith("/")):
            report.error(f"compose.env: {key} must be an absolute host path")
            continue
        if profile.foreign_path(value):
            report.error(f"compose.env: {key} points at a {profile.foreign_kind} path")
            continue
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            report.error(f"compose.env: {key} cannot be resolved on this host")
            continue
        if repo_root is not None and _inside(resolved, repo_root.resolve()):
            report.error(f"compose.env: {key} is inside the repository working tree")
            continue
        try:
            exists = path.is_dir()
        except OSError:
            exists = False
        if not exists:
            # Compose would silently create an empty root-owned directory.
            report.error(f"compose.env: {key} does not exist on this host")
            continue
        if profile.foreign_path(str(resolved)):
            report.error(f"compose.env: {key} resolves (via a link) to a "
                         f"{profile.foreign_kind} path")
        if check_perms:
            check_key_directory(key, path, probe, report, referenced[key],
                                allow_unprovisioned=profile.allow_unprovisioned_keys
                                and key not in required)


def validate_root(root: Path, *, repo_root: Path | None = None,
                  check_perms: bool = True, probe=None, profile: Profile | None = None,
                  postgres_probe=None) -> Report:
    """Validate the seven files; ``probe`` lists key directories (see
    docker_key_dir_probe) and is required whenever permissions are checked."""
    profile = profile or DEV
    report = Report()
    check_root_location(root, repo_root, report, profile)
    if report.errors and not root.is_dir():
        return report
    if check_perms:
        check_permissions(root, secret=True, is_dir=True, report=report,
                          label="configuration root")
    files: dict[str, dict[str, str]] = {}
    for contract in profile.contracts:
        path = root / contract.name
        if not path.exists():
            report.error(f"{contract.name}: required file is missing")
            continue
        if path.is_symlink():
            report.error(f"{contract.name}: must be a regular file, not a symbolic link")
            continue
        if not path.is_file():
            report.error(f"{contract.name}: is not a regular file")
            continue
        if check_perms:
            check_permissions(path, secret=contract.secret_bearing, is_dir=False, report=report)
        values, problems = parse_env_file(path)
        for problem in problems:
            report.error(problem)
        check_contract(contract, values, report, profile)
        files[contract.name] = values
    unexpected = sorted(p.name for p in root.iterdir()
                        if p.is_file() and p.name.endswith(".env")
                        and p.name not in {c.name for c in profile.contracts})
    for name in unexpected:
        report.error(f"{name}: is not a recognised {profile.label} configuration file "
                     "(test configuration is synthetic and tracked in the repository)")
    if profile.file_backed:
        check_file_backed(files, report, profile)
        if check_perms:
            referenced = referenced_secrets(files)
            for store, store_probe in (("app", probe), ("postgres", postgres_probe)):
                check_secret_store(root, store, referenced, store_probe, report)
    else:
        check_cross_file(files, report, profile)
    check_secret_dirs(files.get("compose.env", {}), repo_root, check_perms, report,
                      probe=probe, files=files, profile=profile)
    return report


# --- Legacy .env splitter (migration aid; never prints values) -----------------

# Legacy-only names and where they go instead.
LEGACY_RENAMES = {P + "POSTGRES_ADMIN_PASSWORD": "POSTGRES_PASSWORD"}
# Exactly the URLs compose.yml builds from the legacy passwords.
LEGACY_APP_URL = "postgresql+asyncpg://mykhaya_app:{}@postgres:5432/mykhaya"
LEGACY_MIGRATION_URL = "postgresql+asyncpg://mykhaya_migrator:{}@postgres:5432/mykhaya"
SPLIT_TARGETS = (COMPOSE, COMMON, API, WORKER, SCHEDULER, MIGRATE, POSTGRES)


def split_legacy_env(legacy: dict[str, str], profile: Profile | None = None
                     ) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Map a legacy root .env onto the service files.

    Every name goes to every file whose contract allows it, so each provider
    group keeps reaching exactly the services it reaches today wherever the
    contract permits (for example, environment-configured Stripe still reaches
    the scheduler's monitoring). Returns (files, report); the report lists
    names only.
    """
    profile = profile or DEV
    common, compose = profile.common_contract, profile.compose_contract
    files: dict[str, dict[str, str]] = {c.name: {} for c in profile.contracts}
    for name, value in legacy.items():
        target_name = profile.legacy_renames.get(name, name)
        for contract in profile.contracts:
            if contract is common or contract is compose:
                if target_name in contract.allowed:
                    files[contract.name][target_name] = value
                continue
            if target_name in contract.allowed and target_name not in common.allowed:
                files[contract.name][target_name] = value
    # Values the legacy model interpolated into the worker with a Compose
    # default (`${NAME:-default}`, where empty also means unset) now come from
    # worker.env, so the defaults are written out to keep the worker identical.
    for name, default in profile.worker_interpolated_defaults.items():
        files["worker.env"][name] = legacy.get(name) or default
    # The scheduler gets only the selected DVLA environment's endpoint and key.
    selected = DVLA_SELECTED.get(legacy.get(P + "DVLA_ENVIRONMENT", ""), set())
    for name in DVLA_MONITORING - selected - {P + "DVLA_ENVIRONMENT"}:
        files["scheduler.env"].pop(name, None)
    for service in ("api.env", "worker.env", "scheduler.env"):
        if P + "DB_PASSWORD" in legacy:
            files[service][P + "DATABASE_URL"] = LEGACY_APP_URL.format(legacy[P + "DB_PASSWORD"])
    if P + "MIGRATION_DB_PASSWORD" in legacy:
        files["migrate.env"][P + "DATABASE_URL"] = LEGACY_MIGRATION_URL.format(
            legacy[P + "MIGRATION_DB_PASSWORD"])
    report: dict[str, list[str]] = {"pinned (no effect today; dropped)": [],
                                    UNCLASSIFIED_HEADING: []}
    if profile.host_only:
        report[HOST_ONLY_HEADING] = []
    placed = {n for values in files.values() for n in values} | set(profile.legacy_renames)
    for name in sorted(legacy):
        if name in placed:
            continue
        if name in profile.pinned:
            report["pinned (no effect today; dropped)"].append(name)
        elif name in profile.host_only:
            report[HOST_ONLY_HEADING].append(name)
        else:
            report[UNCLASSIFIED_HEADING].append(name)
    # What each application service stops receiving compared with the legacy
    # env_file (every legacy name reached api, worker, scheduler and migrate).
    for service in ("api", "worker", "scheduler", "migrate"):
        receives = set().union(*(files[f] for f in profile.service_env_files[service]))
        # Names Compose already pinned for this service (e.g. blank APNs for
        # api/scheduler/migrate) never reached it from the .env either.
        already_pinned = profile.pinned | profile.restated.get(service, frozenset())
        dropped = sorted(n for n in legacy if n.startswith(P) and n not in receives
                         and n not in already_pinned and n not in compose.allowed)
        report[f"no longer delivered to {service}"] = dropped
    return files, report


UNCLASSIFIED_HEADING = "not a setting or Compose input (dropped)"
HOST_ONLY_HEADING = "host-script setting (dropped; read from the shell, not a service)"


def write_split(files: dict[str, dict[str, str]], out: Path, profile: Profile | None = None
                ) -> None:
    """Write every file or none, never overwriting, with restrictive modes.

    Each file is first written under a temporary name in `out` and parsed back;
    only if every file reproduces its values exactly are they all renamed into
    place. Any failure removes the temporary files and leaves `out` unchanged.
    Messages never include a value.
    """
    profile = profile or DEV
    if not out.is_dir():
        raise SystemExit(f"ERROR: {out} does not exist; create it first (mode 0750)")
    existing = [name for name in files if (out / name).exists()]
    if existing:
        raise SystemExit(f"ERROR: refusing to overwrite existing files: {', '.join(existing)}")
    staged: list[tuple[Path, Path]] = []
    try:
        for contract in profile.contracts:
            mode = 0o600 if contract.secret_bearing else 0o640
            temporary = out / f".{contract.name}.split-{os.getpid()}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            staged.append((temporary, out / contract.name))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(f"# Generated from the legacy {profile.label} .env by "
                             "service_env_contract.py --split-legacy-env. "
                             f"Contract: {contract.name}.\n")
                for name in sorted(files[contract.name]):
                    handle.write(f"{name}={format_env_value(files[contract.name][name])}\n")
            parsed, problems = parse_env_file(temporary)
            if problems or parsed != files[contract.name]:
                raise SystemExit(f"ERROR: {contract.name} did not round-trip exactly; nothing "
                                 "was written")
        for temporary, final in staged:
            if final.exists():
                raise SystemExit(f"ERROR: {final.name} appeared during the split; nothing was "
                                 "written")
        for temporary, final in staged:
            os.replace(temporary, final)
        staged = []
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


# --- Resolved Compose model checks (names only) --------------------------------

RESOLVED_ALLOWED = {
    "api": COMMON.allowed | API.allowed | PINNED_BY_COMPOSE | APNS,
    "worker": COMMON.allowed | WORKER.allowed | PINNED_BY_COMPOSE,
    # compose.yml gives the scheduler the API's environment through the YAML
    # anchor, including the API's blank APNs pins (checked blank below).
    "scheduler": COMMON.allowed | SCHEDULER.allowed | PINNED_BY_COMPOSE | APNS,
    "migrate": MIGRATE.allowed | PINNED_BY_COMPOSE | APNS | FIELD_KEY_ENV_FALLBACK
               | {P + "APPLE_SIGN_IN_ENABLED", P + "APPLE_PRIVATE_KEY", P + "APPLE_PRIVATE_KEY_FILE"},
    "postgres": POSTGRES.allowed | {"POSTGRES_DB", "POSTGRES_USER"},
}
# Values compose.yml deliberately pins blank/false for these services; a
# non-empty value means a secret leaked in through a file.
MUST_BE_BLANK = {
    "api": {P + "APNS_TEAM_ID", P + "APNS_KEY_ID", P + "APNS_BUNDLE_ID", P + "APNS_PRIVATE_KEY"},
    "scheduler": {P + "APNS_TEAM_ID", P + "APNS_KEY_ID", P + "APNS_BUNDLE_ID",
                  P + "APNS_PRIVATE_KEY"},
    "migrate": APNS - {P + "APNS_DELIVERY_CONFIGURED"} | FIELD_KEY_ENV_FALLBACK
               | {P + "APPLE_PRIVATE_KEY", P + "APPLE_PRIVATE_KEY_FILE"},
}
EXPECTED_MOUNTS = {
    "api": {"/data/avatars", "/data/support-attachments", "/data/vehicle-photos",
            "/data/meal-images", "/data/home-migrations", "/data/legal-evidence",
            "/run/secrets/mykhaya", "/run/secrets/mykhaya-apple"},
    "worker": {"/data/legal-evidence", "/run/secrets/mykhaya"},
    "scheduler": {"/data/avatars", "/data/meal-images", "/data/vehicle-photos",
                  "/data/home-migrations", "/run/secrets/mykhaya"},
    "migrate": set(),
}
SECRET_MOUNT_TARGETS = {"/run/secrets/mykhaya", "/run/secrets/mykhaya-apple"}


# Names compose.dev.service-env.yml restates in each service's `environment`
# (test_dev_service_env.py keeps this in step with the overlay).
DEV_PINS = frozenset(P + n for n in (
    "ENVIRONMENT", "BUILD_CHANNEL", "REGISTRATION_MODE", "COOKIE_SECURE", "PUBLIC_WEB_URL",
    "ADMIN_URL", "STATUS_URL", "NATIVE_API_URL", "CORS_ORIGINS", "TRUSTED_HOSTS",
    "TRUSTED_PROXY_CIDRS", "ADMIN_ALLOWED_NETWORKS", "ADMIN_MFA_REQUIRED", "DEFAULT_TIMEZONE",
    "DEFAULT_LOCALE", "WEEK_START",
))
BUILD_METADATA = frozenset({P + "VERSION", P + "COMMIT_SHA", P + "BUILD_TIME"})
RESTATED_ENVIRONMENT = {
    "api": DEV_PINS | BUILD_METADATA | APNS | {P + "SYSLOG_DEBUG"},
    "worker": DEV_PINS,
    "scheduler": DEV_PINS | BUILD_METADATA | APNS | {P + "SYSLOG_DEBUG"},
    "migrate": DEV_PINS | BUILD_METADATA | APNS | FIELD_KEY_ENV_FALLBACK
               | {P + "APPLE_SIGN_IN_ENABLED", P + "APPLE_PRIVATE_KEY", P + "APPLE_PRIVATE_KEY_FILE"},
    "postgres": frozenset({"POSTGRES_DB", "POSTGRES_USER"}),
}


# --- Profiles -------------------------------------------------------------------
# One contract module serves both environments. The DEV profile is assembled
# from the constants above and behaves exactly as before; the PROD profile
# differs only where compose.production.yml differs from compose.dev.yml.


@dataclass(frozen=True)
class Profile:
    name: str                                   # "dev" | "prod"
    label: str                                  # "DEV" | "PROD"
    root_variable: str
    contracts: tuple[FileContract, ...]
    common_contract: FileContract
    compose_contract: FileContract
    pinned: frozenset[str]
    pinned_source: str
    json_lists: frozenset[str]
    service_env_files: dict[str, tuple[str, ...]]
    restated: dict[str, frozenset[str]]
    resolved_allowed: dict[str, frozenset[str]]
    must_be_blank: dict[str, frozenset[str]]
    expected_mounts: dict[str, set[str]]
    legacy_renames: dict[str, str]
    admin_password_name: str
    foreign_kind: str                           # the other environment, in messages
    foreign_path: object                        # callable(str) -> bool
    allow_unprovisioned_keys: bool = False
    worker_interpolated_defaults: dict[str, str] = field(default_factory=dict)
    host_only: frozenset[str] = frozenset()
    apple_hint: str = ""
    # Credentials come from Compose file secrets (MK-SEC-001).
    file_backed: bool = False


DEV = Profile(
    name="dev", label="DEV", root_variable="MYKHAYA_DEV_CONFIG_ROOT", contracts=CONTRACTS,
    common_contract=COMMON, compose_contract=COMPOSE, pinned=PINNED_BY_COMPOSE,
    pinned_source="compose.dev.yml/compose.yml", json_lists=frozenset(JSON_LIST_NAMES),
    service_env_files=SERVICE_ENV_FILES, restated=RESTATED_ENVIRONMENT,
    resolved_allowed=RESOLVED_ALLOWED, must_be_blank=MUST_BE_BLANK,
    expected_mounts=EXPECTED_MOUNTS, legacy_renames=LEGACY_RENAMES,
    admin_password_name="POSTGRES_PASSWORD", foreign_kind="production",
    foreign_path=_is_production_path, apple_hint=" (use the file in DEV)",
)

# PROD: compose.production.yml pins only these for the application services;
# compose.yml pins build metadata and the syslog switch. Everything else the
# legacy production .env supplied is installation configuration
# (docs/architecture/deployment-configuration.md).
PROD_PINS = frozenset(P + n for n in ("ENVIRONMENT", "BUILD_CHANNEL", "COOKIE_SECURE",
                                      "ADMIN_MFA_REQUIRED"))
PROD_PINNED = PROD_PINS | BUILD_METADATA | {P + "SYSLOG_DEBUG"}
INSTALLATION = frozenset(P + n for n in (
    "REGISTRATION_MODE", "PUBLIC_WEB_URL", "ADMIN_URL", "STATUS_URL", "NATIVE_API_URL",
    "CORS_ORIGINS", "TRUSTED_HOSTS", "TRUSTED_PROXY_CIDRS", "ADMIN_ALLOWED_NETWORKS",
    "DEFAULT_TIMEZONE", "DEFAULT_LOCALE", "WEEK_START",
))
# Production Settings refuse to start without these (mykhaya/config.py), and
# prod-deploy.sh has always required them; migrate builds the same Settings.
INSTALLATION_REQUIRED = frozenset(P + n for n in (
    "REGISTRATION_MODE", "PUBLIC_WEB_URL", "ADMIN_URL", "STATUS_URL", "NATIVE_API_URL",
    "CORS_ORIGINS", "TRUSTED_HOSTS", "TRUSTED_PROXY_CIDRS", "ADMIN_ALLOWED_NETWORKS",
))
PROD_POSTGRES_PASSWORDS = frozenset({P + "POSTGRES_ADMIN_PASSWORD", P + "MIGRATION_DB_PASSWORD",
                                     P + "DB_PASSWORD"})
CADDY_INTERPOLATION = frozenset({"WEB_DOMAIN", "API_DOMAIN", "ADMIN_DOMAIN", "STATUS_DOMAIN",
                                 P + "CADDY_TRUSTED_PROXY_CIDRS"})
# Read by backup.sh/backup-preflight.sh on the host, never by a container.
BACKUP_SETTINGS = frozenset({P + "BACKUP_DIR", P + "BACKUP_AGE_RECIPIENTS_FILE"})

PROD_COMMON = FileContract(
    "common.env",
    allowed=frozenset(COMMON.allowed | INSTALLATION),
    required=INSTALLATION_REQUIRED,
    forbidden=COMMON.forbidden,
    secret_bearing=False,
    consumers=("api", "worker", "scheduler", "migrate"),
)


def _without_environment_keyrings(base: FileContract) -> FileContract:
    """The same contract with the environment-supplied keyrings forbidden:
    production rejects them at startup, so no PROD file may carry them."""
    return FileContract(base.name, allowed=frozenset(base.allowed - FIELD_KEY_ENV_FALLBACK),
                        required=base.required,
                        forbidden=frozenset(base.forbidden | FIELD_KEY_ENV_FALLBACK),
                        consumers=base.consumers)


PROD_API, PROD_WORKER, PROD_SCHEDULER = (_without_environment_keyrings(c)
                                         for c in (API, WORKER, SCHEDULER))
# PROD postgres.env is an interpolation source (a second --env-file), never an
# env_file: PostgreSQL's service definition stays byte-identical to the legacy
# one, so Compose never recreates it for this migration (an env_file entry
# alone changes the service hash). It holds exactly the names compose.yml
# interpolates for PostgreSQL's one-time initialisation.
PROD_POSTGRES = FileContract("postgres.env", allowed=PROD_POSTGRES_PASSWORDS,
                             required=PROD_POSTGRES_PASSWORDS, consumers=("postgres",))
PROD_COMPOSE = FileContract(
    "compose.env",
    allowed=frozenset(CADDY_INTERPOLATION | BACKUP_SETTINGS | {P + n for n in (
        "FIELD_KEYS_HOST_DIR", "APPLE_KEY_HOST_DIR", "SYSLOG_DEBUG", "EMAIL_DELIVERY_CONFIGURED",
    )}),
    required=frozenset(CADDY_INTERPOLATION | {P + "FIELD_KEYS_HOST_DIR",
                                              P + "APPLE_KEY_HOST_DIR"}),
    forbidden=frozenset(COMPOSE.forbidden | {P + "BACKUP_AGE_IDENTITY"}),
    secret_bearing=False,
)
PROD_CONTRACTS = (PROD_COMMON, PROD_API, PROD_WORKER, PROD_SCHEDULER, MIGRATE, PROD_POSTGRES,
                  PROD_COMPOSE)
APPLE_BLANKED = frozenset({P + "APPLE_SIGN_IN_ENABLED", P + "APPLE_PRIVATE_KEY",
                           P + "APPLE_PRIVATE_KEY_FILE"})
POSTGRES_ENVIRONMENT = frozenset({"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
                                  P + "MIGRATION_DB_PASSWORD", P + "DB_PASSWORD"})

PROD = Profile(
    name="prod", label="PROD", root_variable="MYKHAYA_PROD_CONFIG_ROOT",
    contracts=PROD_CONTRACTS, common_contract=PROD_COMMON, compose_contract=PROD_COMPOSE,
    pinned=PROD_PINNED, pinned_source="compose.production.yml/compose.yml",
    json_lists=frozenset(JSON_LIST_NAMES | {P + "CORS_ORIGINS", P + "TRUSTED_HOSTS"}),
    service_env_files={
        "api": ("common.env", "api.env"),
        "worker": ("common.env", "worker.env"),
        "scheduler": ("common.env", "scheduler.env"),
        "migrate": ("common.env", "migrate.env"),
    },
    restated={
        "api": PROD_PINS | BUILD_METADATA | APNS | {P + "SYSLOG_DEBUG"},
        "worker": PROD_PINS,
        "scheduler": PROD_PINS | BUILD_METADATA | APNS | {P + "SYSLOG_DEBUG"},
        "migrate": PROD_PINS | BUILD_METADATA | APNS | FIELD_KEY_ENV_FALLBACK | APPLE_BLANKED,
        "postgres": POSTGRES_ENVIRONMENT,
    },
    resolved_allowed={
        "api": PROD_COMMON.allowed | PROD_API.allowed | PROD_PINNED | APNS,
        "worker": PROD_COMMON.allowed | PROD_WORKER.allowed | PROD_PINNED,
        "scheduler": PROD_COMMON.allowed | PROD_SCHEDULER.allowed | PROD_PINNED | APNS,
        "migrate": PROD_COMMON.allowed | MIGRATE.allowed | PROD_PINNED | APNS
                   | FIELD_KEY_ENV_FALLBACK | APPLE_BLANKED,
        "postgres": POSTGRES_ENVIRONMENT,
    },
    must_be_blank=MUST_BE_BLANK, expected_mounts=EXPECTED_MOUNTS, legacy_renames={},
    admin_password_name=P + "POSTGRES_ADMIN_PASSWORD", foreign_kind="development",
    foreign_path=_is_development_path, allow_unprovisioned_keys=True,
    # compose.yml (worker) and compose.production.yml (worker) interpolate these.
    worker_interpolated_defaults={
        P + "APNS_DELIVERY_CONFIGURED": "false", P + "APNS_TEAM_ID": "", P + "APNS_KEY_ID": "",
        P + "APNS_BUNDLE_ID": DEVELOPMENT_APNS_BUNDLE_ID, P + "APNS_PRIVATE_KEY": "",
        P + "FCM_DELIVERY_CONFIGURED": "false", P + "FCM_PROJECT_ID": "",
        P + "FCM_CLIENT_EMAIL": "", P + "FCM_PRIVATE_KEY": "",
    },
    host_only=frozenset({P + "PRODUCTION"}),
)
PROFILES = {"dev": DEV, "prod": PROD}


# --- File-backed secrets (MK-SEC-001 v1.2) --------------------------------------
# The third configuration mode, DEV and PROD: F-03's per-service layout, with every
# credential moved out of the environment into a Compose file secret, each
# mounted only into the services granted it, and each process given its role
# (apps/api/mykhaya/process_roles.py enforces the same matrix at startup).
#
# It has its own root (<DEV or PROD root>/file-backed), generated from the F-03 files by
# dev_secrets_migration.py, so the F-03 files stay untouched as the rollback
# source. Layout:
#   file-backed/*.env               non-secret settings, one file per service
#   file-backed/secrets/app/        root:10001 0750, files root:10001 0440
#   file-backed/secrets/postgres/   root:70 0750, files root:70 0440
# Every secret file always exists, because Compose needs each bind source. A
# credential that is not configured is an empty file no setting refers to.

POSTGRES_UID = 70  # the postgres user of the pinned alpine PostgreSQL image
POSTGRES_GID = 70
SECRET_TARGET = "/run/secrets/"


@dataclass(frozen=True)
class SecretFile:
    """One Compose secret: its file name and the services it is mounted into."""

    name: str
    services: tuple[str, ...]
    # Variables holding the literal in the F-03 files. Empty: derived from a
    # database URL or from postgres.env.
    literals: tuple[str, ...] = ()
    kind: str = "line"  # line | pem
    required: bool = False

    @property
    def store(self) -> str:
        return "postgres" if self.services == ("postgres",) else "app"

    @property
    def path(self) -> str:
        return SECRET_TARGET + self.name


SECRET_FILE_SPECS = (
    SecretFile("secret_key", ("api", "worker", "scheduler"), (P + "SECRET_KEY",), required=True),
    SecretFile("app_db_password", ("api", "worker", "scheduler"), required=True),
    SecretFile("migration_db_password", ("migrate",), required=True),
    SecretFile("smtp_password", ("api", "worker", "scheduler"), (P + "SMTP_PASSWORD",)),
    SecretFile("vapid_private_key", ("api", "worker"), (P + "VAPID_PRIVATE_KEY",)),
    SecretFile("apns_private_key", ("worker",), (P + "APNS_PRIVATE_KEY",), "pem"),
    SecretFile("fcm_private_key", ("worker",), (P + "FCM_PRIVATE_KEY",), "pem"),
    SecretFile("apple_private_key", ("api",), (P + "APPLE_PRIVATE_KEY",), "pem"),
    SecretFile("google_client_secret", ("api",), (P + "GOOGLE_CLIENT_SECRET",)),
    SecretFile("stripe_secret_key", ("api", "scheduler"), (P + "STRIPE_SECRET_KEY",)),
    SecretFile("stripe_webhook_secret", ("api",), (P + "STRIPE_WEBHOOK_SECRET",)),
    SecretFile("dvla_uat_api_key", ("api",), (P + "DVLA_UAT_API_KEY",)),
    SecretFile("dvla_production_api_key", ("api",), (P + "DVLA_PRODUCTION_API_KEY",)),
    SecretFile("dvsa_client_id", ("api",), (P + "DVSA_CLIENT_ID",)),
    SecretFile("dvsa_client_secret", ("api",), (P + "DVSA_CLIENT_SECRET",)),
    SecretFile("dvsa_api_key", ("api",), (P + "DVSA_API_KEY",)),
    SecretFile("monitoring_watchdog_url", ("scheduler",), (P + "MONITORING_WATCHDOG_URL",)),
    SecretFile("postgres_admin_password", ("postgres",), required=True),
    SecretFile("postgres_migration_password", ("postgres",), required=True),
    SecretFile("postgres_app_password", ("postgres",), required=True),
)
SECRETS_BY_NAME = {s.name: s for s in SECRET_FILE_SPECS}
# The PostgreSQL bootstrap variables the overlay pins to their files.
POSTGRES_SECRET_ENV = {
    "POSTGRES_PASSWORD_FILE": "postgres_admin_password",
    P + "MIGRATION_DB_PASSWORD_FILE": "postgres_migration_password",
    P + "DB_PASSWORD_FILE": "postgres_app_password",
}
DATABASE_PASSWORD_FILE = P + "DATABASE_PASSWORD_FILE"
PROCESS_ROLE = P + "PROCESS_ROLE"
ROLE_SERVICES = ("api", "worker", "scheduler", "migrate")
SCHEDULER_PRESENCE = frozenset(P + n for n in (
    "DVLA_API_KEY_PRESENT", "DVSA_CREDENTIALS_PRESENT", "STRIPE_WEBHOOK_SECRET_PRESENT"))
FCM_PRESENCE = P + "FCM_PRIVATE_KEY_PRESENT"


def service_secrets(service: str) -> frozenset[str]:
    """The secret names granted to one service."""
    return frozenset(s.name for s in SECRET_FILE_SPECS if service in s.services)


def file_settings(service: str) -> dict[str, str]:
    """`*_FILE` variable -> secret name a service may set."""
    settings = {f"{literal}_FILE": s.name for s in SECRET_FILE_SPECS if service in s.services
                for literal in s.literals}
    if service in ("api", "worker", "scheduler"):
        settings[DATABASE_PASSWORD_FILE] = "app_db_password"
    if service == "migrate":
        settings[DATABASE_PASSWORD_FILE] = "migration_db_password"
    return settings


ALL_LITERALS = frozenset(n for s in SECRET_FILE_SPECS for n in s.literals) | FIELD_KEY_ENV_FALLBACK
ALL_FILE_SETTINGS = frozenset(n for s in ROLE_SERVICES for n in file_settings(s))


def _file_backed(base: FileContract, service: str, *, drop: frozenset[str] = frozenset(),
                 add: frozenset[str] = frozenset()) -> FileContract:
    """An F-03 contract with every credential literal forbidden and exactly
    this service's file settings allowed."""
    settings = frozenset(file_settings(service))
    allowed = (base.allowed - ALL_LITERALS - drop) | settings | add
    required = (base.required - ALL_LITERALS) | frozenset(
        n for n, secret in file_settings(service).items() if SECRETS_BY_NAME[secret].required)
    forbidden = base.forbidden | ALL_LITERALS | drop | (ALL_FILE_SETTINGS - settings) \
        | BOOTSTRAP_PASSWORDS
    return FileContract(base.name, allowed=frozenset(allowed), required=frozenset(required),
                        forbidden=frozenset(forbidden - allowed), consumers=base.consumers,
                        secret_bearing=base.secret_bearing)


SECRETS_API = _file_backed(API, "api", add=frozenset({FCM_PRESENCE}))
SECRETS_WORKER = _file_backed(WORKER, "worker")
SECRETS_SCHEDULER = _file_backed(SCHEDULER, "scheduler", add=SCHEDULER_PRESENCE)
SECRETS_MIGRATE = _file_backed(MIGRATE, "migrate")
SECRETS_COMMON = FileContract(
    "common.env", allowed=COMMON.allowed,
    forbidden=frozenset(COMMON.forbidden | ALL_FILE_SETTINGS | ALL_LITERALS),
    secret_bearing=False, consumers=COMMON.consumers)
# PostgreSQL's three passwords are pinned to files by the overlay.
SECRETS_POSTGRES = FileContract(
    "postgres.env", allowed=frozenset(),
    forbidden=frozenset(BOOTSTRAP_PASSWORDS | set(POSTGRES_SECRET_ENV)), consumers=("postgres",))
SECRETS_COMPOSE = FileContract(
    "compose.env", allowed=COMPOSE.allowed, required=COMPOSE.required,
    forbidden=frozenset(COMPOSE.forbidden | ALL_FILE_SETTINGS), secret_bearing=False)
MIGRATE_PINS = BUILD_METADATA | {P + "ENVIRONMENT", P + "BUILD_CHANNEL", PROCESS_ROLE}
_ROLE = frozenset({PROCESS_ROLE})

DEV_SECRETS = replace(
    DEV, name="dev-secrets", label="DEV file-backed",
    pinned=PINNED_BY_COMPOSE | _ROLE, pinned_source="the DEV Compose files",
    common_contract=SECRETS_COMMON, compose_contract=SECRETS_COMPOSE,
    contracts=(SECRETS_COMMON, SECRETS_API, SECRETS_WORKER, SECRETS_SCHEDULER, SECRETS_MIGRATE,
               SECRETS_POSTGRES, SECRETS_COMPOSE),
    restated={
        "api": RESTATED_ENVIRONMENT["api"] | _ROLE,
        "worker": RESTATED_ENVIRONMENT["worker"] | _ROLE,
        "scheduler": RESTATED_ENVIRONMENT["scheduler"] | _ROLE,
        "migrate": MIGRATE_PINS,
        "postgres": frozenset({"POSTGRES_DB", "POSTGRES_USER"}) | frozenset(POSTGRES_SECRET_ENV),
    },
    resolved_allowed={
        "api": COMMON.allowed | SECRETS_API.allowed | PINNED_BY_COMPOSE | APNS | _ROLE,
        "worker": COMMON.allowed | SECRETS_WORKER.allowed | PINNED_BY_COMPOSE | _ROLE,
        "scheduler": COMMON.allowed | SECRETS_SCHEDULER.allowed | PINNED_BY_COMPOSE | APNS | _ROLE,
        "migrate": SECRETS_MIGRATE.allowed | MIGRATE_PINS,
        "postgres": frozenset({"POSTGRES_DB", "POSTGRES_USER"}) | frozenset(POSTGRES_SECRET_ENV),
    },
    file_backed=True,
)
PROFILES["dev-secrets"] = DEV_SECRETS

# PROD: the same grants on the PROD F-03 layout. The migrate role holds only the
# migration credential, so it loses common.env (installation settings and key
# paths) and every other pinned name.
PROD_SECRETS_API = _file_backed(PROD_API, "api", add=frozenset({FCM_PRESENCE}))
PROD_SECRETS_WORKER = _file_backed(PROD_WORKER, "worker")
PROD_SECRETS_SCHEDULER = _file_backed(PROD_SCHEDULER, "scheduler", add=SCHEDULER_PRESENCE)
PROD_SECRETS_COMMON = FileContract(
    "common.env", allowed=PROD_COMMON.allowed, required=PROD_COMMON.required,
    forbidden=frozenset(PROD_COMMON.forbidden | ALL_FILE_SETTINGS | ALL_LITERALS),
    secret_bearing=False, consumers=("api", "worker", "scheduler"))
PROD_SECRETS_COMPOSE = FileContract(
    "compose.env", allowed=PROD_COMPOSE.allowed, required=PROD_COMPOSE.required,
    forbidden=frozenset(PROD_COMPOSE.forbidden | ALL_FILE_SETTINGS), secret_bearing=False)
PROD_SECRETS = replace(
    PROD, name="prod-secrets", label="PROD file-backed",
    pinned=PROD_PINNED | _ROLE, pinned_source="the production Compose files",
    common_contract=PROD_SECRETS_COMMON, compose_contract=PROD_SECRETS_COMPOSE,
    contracts=(PROD_SECRETS_COMMON, PROD_SECRETS_API, PROD_SECRETS_WORKER,
               PROD_SECRETS_SCHEDULER, SECRETS_MIGRATE, SECRETS_POSTGRES, PROD_SECRETS_COMPOSE),
    service_env_files={**PROD.service_env_files, "migrate": ("migrate.env",)},
    restated={
        **{s: PROD.restated[s] | _ROLE for s in ("api", "worker", "scheduler")},
        "migrate": MIGRATE_PINS,
        "postgres": DEV_SECRETS.restated["postgres"],
    },
    resolved_allowed={
        "api": PROD_COMMON.allowed | PROD_SECRETS_API.allowed | PROD_PINNED | APNS | _ROLE,
        "worker": PROD_COMMON.allowed | PROD_SECRETS_WORKER.allowed | PROD_PINNED | _ROLE,
        "scheduler": PROD_COMMON.allowed | PROD_SECRETS_SCHEDULER.allowed | PROD_PINNED | APNS
                     | _ROLE,
        "migrate": SECRETS_MIGRATE.allowed | MIGRATE_PINS,
        "postgres": DEV_SECRETS.resolved_allowed["postgres"],
    },
    file_backed=True,
)
PROFILES["prod-secrets"] = PROD_SECRETS
# Each F-03 profile's file-backed successor.
FILE_BACKED = {"dev": DEV_SECRETS, "prod": PROD_SECRETS}


def _truthy(values: dict[str, str], name: str) -> bool:
    return values.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def secret_value_problem(kind: str, value: str) -> str | None:
    """Why a value cannot be stored so the application's hardened reader
    (apps/api/mykhaya/secret_files.py) returns it unchanged, or None."""
    data = value.encode("utf-8", "surrogateescape")
    if b"\x00" in data:
        return "contains a NUL byte"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "is not valid UTF-8"
    if kind == "line":
        if "\n" in value or "\r" in value:
            return "must be a single line"
        if value != value.strip():
            return "has leading or trailing whitespace"
        if len(data) > 4095:
            return "is too large"
        return None
    if not re.fullmatch(r"-----BEGIN ([A-Z0-9 ]+)-----\n(?:[A-Za-z0-9+/=]+\n)+-----END \1-----",
                        value):
        return "is not exactly one PEM block"
    return "is too large" if len(data) > 16000 else None


def normalise_secret(kind: str, value: str) -> str:
    """PEM keys arrive in dotenv files with escaped or CRLF line breaks, which
    the application already decodes (notifications/push.py)."""
    if kind == "pem":
        text = value.replace("\\n", "\n").replace("\r\n", "\n").strip()
        return "\n".join(line.strip() for line in text.split("\n"))
    return value


def _split_database_url(url: str) -> tuple[str, str] | None:
    """(password-free URL, decoded password)."""
    parts = _db_parts(url)
    if parts is None or not parts[2] or "@" not in url:
        return None
    scheme, rest = url.split("://", 1)
    userinfo, location = rest.rsplit("@", 1)
    return f"{scheme}://{userinfo.split(':', 1)[0]}@{location}", parts[2]


def derive_file_backed(files: dict[str, dict[str, str]], profile: Profile | None = None
                       ) -> tuple[dict[str, dict[str, str]], dict[str, str], list[str]]:
    """Convert validated F-03 files: (env files, secret values, problems).

    Pure. Nothing is generated or rotated: every secret is the existing value.
    Problems name variables only. ``profile`` is the F-03 profile (default DEV).
    """
    profile = profile or DEV
    problems: list[str] = []
    values: dict[str, str] = {s.name: "" for s in SECRET_FILE_SPECS}
    out = {name: dict(content) for name, content in files.items()}
    env_name = {s: f"{s}.env" for s in ROLE_SERVICES}

    def take(secret: SecretFile, source: str, value: str) -> None:
        value = normalise_secret(secret.kind, value)
        problem = secret_value_problem(secret.kind, value)
        if problem:
            problems.append(f"{source}: the value {problem}")
        elif values[secret.name] and values[secret.name] != value:
            problems.append(f"{source}: differs between service files")
        else:
            values[secret.name] = value

    for name in FIELD_KEY_ENV_FALLBACK:
        if any(content.get(name) for content in files.values()):
            problems.append(f"{name}: the keyring is supplied through the environment; install it "
                            "as a key file first (docs/operations/sensitive-field-keys.md)")
    # Presence flags are stated from what each service's checks read today.
    scheduler, api, worker = (files.get(f"{s}.env", {}) for s in ("scheduler", "api", "worker"))
    flags: dict[str, bool] = {}
    environment = scheduler.get(P + "DVLA_ENVIRONMENT", "").strip()
    if environment:
        key = P + ("DVLA_UAT_API_KEY" if environment == "uat" else "DVLA_PRODUCTION_API_KEY")
        flags[P + "DVLA_API_KEY_PRESENT"] = bool(scheduler.get(key))
    if _truthy(scheduler, P + "DVSA_ENABLED") or scheduler.get(P + "DVSA_TOKEN_URL"):
        flags[P + "DVSA_CREDENTIALS_PRESENT"] = all(scheduler.get(P + n) for n in (
            "DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET", "DVSA_API_KEY"))
    if _truthy(scheduler, P + "STRIPE_BILLING_CONFIGURED"):
        flags[P + "STRIPE_WEBHOOK_SECRET_PRESENT"] = bool(
            scheduler.get(P + "STRIPE_WEBHOOK_SECRET"))
    for service in ("api", "worker", "scheduler", "migrate"):
        content = out.get(env_name[service], {})
        settings = file_settings(service)
        for secret in SECRET_FILE_SPECS:
            for literal in secret.literals:
                value = content.pop(literal, "")
                # A blank literal means "not configured" to the settings model.
                if not value.strip():
                    continue
                if service in secret.services:
                    take(secret, f"{env_name[service]}: {literal}", value)
                    if f"{literal}_FILE" in settings:
                        content[f"{literal}_FILE"] = secret.path
        for name in FIELD_KEY_ENV_FALLBACK:
            content.pop(name, None)
        split = _split_database_url(content.get(P + "DATABASE_URL", ""))
        if split is None:
            problems.append(f"{env_name[service]}: MYKHAYA_DATABASE_URL must be a database URL "
                            "with a password")
            continue
        content[P + "DATABASE_URL"], password = split
        secret = SECRETS_BY_NAME[settings[DATABASE_PASSWORD_FILE]]
        take(secret, f"{env_name[service]}: MYKHAYA_DATABASE_URL password", password)
        content[DATABASE_PASSWORD_FILE] = secret.path
    if api.get(P + "APPLE_PRIVATE_KEY_FILE"):
        out["api.env"][P + "APPLE_PRIVATE_KEY_FILE"] = api[P + "APPLE_PRIVATE_KEY_FILE"]
    for name, present in flags.items():
        out["scheduler.env"][name] = "true" if present else "false"
    if _truthy(api, P + "FCM_DELIVERY_CONFIGURED"):
        out["api.env"][FCM_PRESENCE] = "true" if worker.get(P + "FCM_PRIVATE_KEY") else "false"
    postgres = files.get("postgres.env", {})
    for source, name in ((profile.admin_password_name, "postgres_admin_password"),
                         (P + "MIGRATION_DB_PASSWORD", "postgres_migration_password"),
                         (P + "DB_PASSWORD", "postgres_app_password")):
        take(SECRETS_BY_NAME[name], f"postgres.env: {source}", postgres.get(source, ""))
    out["postgres.env"] = {}
    for secret in SECRET_FILE_SPECS:
        if secret.required and not values[secret.name]:
            problems.append(f"{secret.name}: the required credential is not configured")
    for app, bootstrap in (("app_db_password", "postgres_app_password"),
                           ("migration_db_password", "postgres_migration_password")):
        if values[app] != values[bootstrap]:
            problems.append(f"{app}: differs from the password PostgreSQL was initialised with")
    return out, values, problems


def referenced_secrets(files: dict[str, dict[str, str]]) -> set[str]:
    """Secrets some service is configured to read (PostgreSQL's always are)."""
    wanted = set(POSTGRES_SECRET_ENV.values())
    for service in ROLE_SERVICES:
        content = files.get(f"{service}.env", {})
        wanted |= {secret for name, secret in file_settings(service).items()
                   if content.get(name) == SECRET_TARGET + secret}
    return wanted


def check_file_backed(files: dict[str, dict[str, str]], report: Report,
                      profile: Profile | None = None) -> None:
    """Cross-file rules of the file-backed layout (replaces check_cross_file)."""
    profile = profile or DEV_SECRETS
    api, worker, scheduler, migrate = (files.get(f"{s}.env", {}) for s in ROLE_SERVICES)
    for service in ROLE_SERVICES:
        content, name = files.get(f"{service}.env", {}), f"{service}.env"
        for setting, secret in file_settings(service).items():
            value = content.get(setting)
            if value is None or value == SECRET_TARGET + secret:
                continue
            if setting == P + "APPLE_PRIVATE_KEY_FILE" and \
                    re.fullmatch(r"/run/secrets/mykhaya-apple/[A-Za-z0-9._-]+", value) and \
                    value.rsplit("/", 1)[1] not in {".", ".."}:
                continue
            report.error(f"{name}: {setting} must be {SECRET_TARGET + secret}")
        parts = _db_parts(content.get(P + "DATABASE_URL", ""))
        user = MIGRATION_DB_USER if service == "migrate" else APP_DB_USER
        if parts is None or parts[0] != "postgresql+asyncpg":
            report.error(f"{name}: MYKHAYA_DATABASE_URL must be a postgresql+asyncpg URL")
            continue
        if parts[1] != user:
            report.error(f"{name}: MYKHAYA_DATABASE_URL must use the {user} role")
        if parts[2]:
            report.error(f"{name}: MYKHAYA_DATABASE_URL must not contain a password")
    targets = {(_db_parts(f.get(P + "DATABASE_URL", "")) or ("",) * 5)[3:]
               for f in (api, worker, scheduler, migrate)}
    if len(targets) > 1:
        report.error("MYKHAYA_DATABASE_URL targets different databases between services")
    if len({f.get(P + "REDIS_URL") for f in (api, worker, scheduler)}) > 1:
        report.error("MYKHAYA_REDIS_URL differs between api, worker and scheduler")
    for group in (SMTP, STRIPE_MONITORING, DVLA_MONITORING, DVSA_MONITORING, FCM, VAPID):
        for other_name, other in (("worker.env", worker), ("scheduler.env", scheduler)):
            names = {n for g in group for n in (g, f"{g}_FILE")}
            for name in sorted(names & set(other) & set(api)):
                if other[name] != api[name]:
                    report.error(f"{other_name}: {name} differs from api.env")
    if scheduler.get(P + "DVLA_ENVIRONMENT") and P + "DVLA_API_KEY_PRESENT" not in scheduler:
        report.error("scheduler.env: MYKHAYA_DVLA_API_KEY_PRESENT is required")
    if (_truthy(scheduler, P + "DVSA_ENABLED") or scheduler.get(P + "DVSA_TOKEN_URL")) and \
            P + "DVSA_CREDENTIALS_PRESENT" not in scheduler:
        report.error("scheduler.env: MYKHAYA_DVSA_CREDENTIALS_PRESENT is required")
    if _truthy(scheduler, P + "STRIPE_BILLING_CONFIGURED") and \
            P + "STRIPE_WEBHOOK_SECRET_PRESENT" not in scheduler:
        report.error("scheduler.env: MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT is required")
    if _truthy(api, P + "FCM_DELIVERY_CONFIGURED") and FCM_PRESENCE not in api:
        report.error(f"api.env: {FCM_PRESENCE} is required")
    for name, content in (("scheduler.env", scheduler), ("api.env", api)):
        for flag in sorted((SCHEDULER_PRESENCE | {FCM_PRESENCE}) & set(content)):
            if content[flag] not in {"true", "false"}:
                report.error(f"{name}: {flag} must be true or false")
    # Monitoring inputs the API uses must still reach the scheduler.
    for flag in ("EMAIL_DELIVERY_CONFIGURED", "STRIPE_BILLING_CONFIGURED", "DVSA_ENABLED",
                 "APPLE_SIGN_IN_ENABLED", "GOOGLE_SIGN_IN_ENABLED"):
        if _truthy(api, P + flag) and not _truthy(scheduler, P + flag):
            report.error(f"scheduler.env: {P + flag} must be true, as in api.env")
    if profile is PROD_SECRETS:
        check_production_separation(files, report)
    else:
        check_development_separation(files, report)
    for name, values in files.items():
        for key in (P + "FIELD_ENCRYPTION_KEYS_FILE", P + "BLIND_INDEX_KEYS_FILE"):
            if values.get(key) and not re.fullmatch(r"/run/secrets/mykhaya/[A-Za-z0-9._-]+",
                                                    values[key]):
                report.error(f"{name}: {key} must name a file directly inside the read-only "
                             "/run/secrets/mykhaya/ mount")


def check_secret_store(root: Path, store: str, referenced: set[str], probe, report: Report) -> None:
    """One store directory as its consumers see it: exact file set, ownership,
    modes, readability, and content present exactly when a setting uses it."""
    label = f"secrets/{store}"
    uid, gid = ((POSTGRES_UID, POSTGRES_GID) if store == "postgres" else (SERVICE_UID, SERVICE_GID))
    if probe is None:
        report.error(f"{label}: cannot be verified: no API image was given (--probe-image)")
        return
    path = root / "secrets" / store
    try:
        listing = probe(str(path))
    except ProbeFailure as exc:
        report.error(f"{label}: cannot be verified: {exc}")
        return
    if (listing.uid, listing.gid) != (uid, gid) or listing.root is None or listing.entries is None:
        report.error(f"{label}: is not readable by the service account ({uid}:{gid})")
        return

    def check(entry: KeyEntry, name: str, kind: str, mode: int) -> None:
        if entry.kind != kind:
            report.error(f"{name}: must be a regular {kind}, not a {entry.kind}")
        elif entry.uid != 0 or entry.gid != gid:
            report.error(f"{name}: must be owned by root with group {gid}")
        elif entry.mode != mode:
            report.error(f"{name}: has mode {entry.mode:04o}; expected {mode:04o}")
        elif not entry.readable:
            report.error(f"{name}: is not readable by the service account ({uid}:{gid})")

    check(listing.root, label, "directory", 0o750)
    expected = {s.name for s in SECRET_FILE_SPECS if s.store == store}
    present = {e.name for e in listing.entries}
    for name in sorted(expected - present):
        report.error(f"{label}/{name}: is missing")
    for name in sorted(present - expected):
        report.error(f"{label}/{_safe_name(name)}: is not a recognised secret file")
    for entry in listing.entries:
        if entry.name not in expected:
            continue
        name = f"{label}/{entry.name}"
        check(entry, name, "file", 0o440)
        if entry.size is None:
            report.error(f"{name}: its size could not be checked")
        elif entry.name in referenced and entry.size == 0:
            report.error(f"{name}: is empty but a service is configured to read it")
        elif entry.name not in referenced and entry.size:
            report.error(f"{name}: holds a value that no service is configured to read")


def check_secret_mounts(model: dict, root: Path | None, profile: Profile) -> list[str]:
    """Exact per-service Compose secret grants; no other profile may use any."""
    errors: list[str] = []
    services, declared = model.get("services", {}), model.get("secrets") or {}
    if not profile.file_backed:
        for name, service in services.items():
            if service.get("secrets"):
                errors.append(f"{name}: Compose secrets are not part of this configuration")
        return errors
    for name in sorted(set(declared) - set(SECRETS_BY_NAME)):
        errors.append(f"Compose secret {name} is not in the contract")
    for name, secret in SECRETS_BY_NAME.items():
        definition = declared.get(name) or {}
        extra = set(definition) - {"name", "file"}
        source = str(definition.get("file", ""))
        if extra or not source:
            errors.append(f"Compose secret {name} must be a plain file secret")
        elif root is not None and PurePosixPath(source) != PurePosixPath(
                (root / "secrets" / secret.store / name).as_posix()):
            errors.append(f"Compose secret {name} does not come from {profile.root_variable}")
    for name, service in services.items():
        granted = []
        for entry in service.get("secrets") or []:
            source, target = entry.get("source"), entry.get("target") or entry.get("source")
            granted.append(source)
            if target not in {source, SECRET_TARGET + str(source)}:
                errors.append(f"{name}: secret {source} is mounted at an unexpected path")
            if set(entry) - {"source", "target"}:
                errors.append(f"{name}: secret {source} sets uid, gid or mode, which Compose "
                              "ignores for file secrets")
        for extra in sorted(set(granted) - service_secrets(name)):
            errors.append(f"{name}: must not receive secret {extra}")
        for missing in sorted(service_secrets(name) - set(granted)):
            errors.append(f"{name}: does not receive secret {missing}")
        env = service.get("environment") or {}
        if name in ROLE_SERVICES and env.get(PROCESS_ROLE) != name:
            errors.append(f"{name}: {PROCESS_ROLE} must be {name}")
        if name == "postgres":
            for setting, secret_name in POSTGRES_SECRET_ENV.items():
                if env.get(setting) != SECRET_TARGET + secret_name:
                    errors.append(f"postgres: {setting} must be {SECRET_TARGET + secret_name}")
    return errors


def check_provenance(model: dict, root: Path, profile: Profile | None = None) -> list[str]:
    """Prove each service's merged environment comes only from the config root.

    Works with any Compose version: the merged environment must contain
    exactly the overlay's restated names plus the names in that service's own
    files, and every file-supplied value must arrive unchanged. A root .env (or
    any other source) still being loaded would add names. Values are compared
    in memory; only names are reported.
    """
    profile = profile or DEV
    errors: list[str] = []
    services = model.get("services", {})
    for service, file_names in profile.service_env_files.items():
        if service not in services:
            errors.append(f"{service}: missing from the merged Compose model")
            continue
        supplied: dict[str, str] = {}
        for file_name in file_names:
            path = root / file_name
            if path.is_file():
                values, _ = parse_env_file(path)
                supplied.update(values)
        restated = profile.restated[service]
        env = services[service].get("environment") or {}
        for name in sorted(set(env) - restated - set(supplied)):
            errors.append(f"{service}: receives {name} from outside {profile.root_variable}")
        for name in sorted(set(supplied) - restated):
            if name not in env:
                errors.append(f"{service}: {name} from its file does not reach the container")
            # `compose config` prints every literal "$" as "$$".
            elif str(env[name]).replace("$$", "$") != supplied[name]:
                errors.append(f"{service}: {name} differs from its file (another source wins)")
    if profile.name == "prod":
        errors += check_production_bootstrap_provenance(services, root)
    return errors


def check_production_bootstrap_provenance(services: dict, root: Path) -> list[str]:
    """PROD only: PostgreSQL's bootstrap passwords come from postgres.env by
    interpolation and must reach no other service, under any variable name,
    except each application's own database URL (proved equal to its file)."""
    errors: list[str] = []
    path = root / "postgres.env"
    values, _ = parse_env_file(path) if path.is_file() else ({}, [])
    admin = values.get(P + "POSTGRES_ADMIN_PASSWORD", "")
    migration = values.get(P + "MIGRATION_DB_PASSWORD", "")
    runtime = values.get(P + "DB_PASSWORD", "")
    postgres = (services.get("postgres") or {}).get("environment") or {}
    expected = {"POSTGRES_DB": "mykhaya", "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": admin, P + "MIGRATION_DB_PASSWORD": migration,
                P + "DB_PASSWORD": runtime}
    for name, value in expected.items():
        if str(postgres.get(name, "")).replace("$$", "$") != value or name not in postgres:
            errors.append(f"postgres: {name} does not come unchanged from postgres.env")
    for name in sorted(set(postgres) - set(expected)):
        errors.append(f"postgres: receives {name} from outside MYKHAYA_PROD_CONFIG_ROOT")
    secrets_by_role = (("administrator", admin, set()),
                       ("migration", migration, {("migrate", P + "DATABASE_URL")}),
                       ("runtime", runtime, {(s, P + "DATABASE_URL")
                                             for s in ("api", "worker", "scheduler")}))
    for service, definition in services.items():
        if service == "postgres":
            continue
        env = (definition or {}).get("environment") or {}
        for name, raw in env.items():
            text = str(raw if raw is not None else "").replace("$$", "$")
            for role, secret, permitted in secrets_by_role:
                if secret and secret in text and (service, name) not in permitted:
                    errors.append(f"{service}: {name} contains the PostgreSQL {role} password")
    return errors


def check_resolved_model(model: dict, repo_root: Path, profile: Profile | None = None
                         ) -> list[str]:
    """Allow-list the merged Compose model by variable name and mount target."""
    profile = profile or DEV
    errors: list[str] = []
    services = model.get("services", {})
    for name, service in services.items():
        env = service.get("environment") or {}
        allowed = profile.resolved_allowed.get(name)
        if allowed is not None:
            for var in sorted(set(env) - allowed):
                errors.append(f"{name}: receives {var}, which is outside its contract")
        if name not in {"postgres"}:
            for var in sorted(set(env) & BOOTSTRAP_PASSWORDS):
                errors.append(f"{name}: receives database bootstrap credential {var}")
        for var in sorted(profile.must_be_blank.get(name, set()) & set(env)):
            if env[var] not in ("", None):
                errors.append(f"{name}: {var} must be blank for this service")
        mounts = service.get("volumes") or []
        targets = {m.get("target") for m in mounts}
        if name in profile.expected_mounts and targets != profile.expected_mounts[name]:
            errors.append(f"{name}: mounts {sorted(t for t in targets if t)} but the contract is "
                          f"{sorted(profile.expected_mounts[name])}")
        for mount in mounts:
            if mount.get("target") in SECRET_MOUNT_TARGETS:
                if not mount.get("read_only"):
                    errors.append(f"{name}: secret mount {mount['target']} is not read-only")
                source = str(mount.get("source", ""))
                if profile.foreign_path(source):
                    errors.append(f"{name}: secret mount {mount['target']} uses a "
                                  f"{profile.foreign_kind} path")
                if _inside(Path(source).resolve(), repo_root.resolve()):
                    errors.append(f"{name}: secret mount {mount['target']} comes from the repository")
            elif name not in profile.expected_mounts and name not in {"postgres", "caddy", "redis"} and \
                    mount.get("type") == "bind":
                errors.append(f"{name}: unexpected bind mount {mount.get('target')}")
            if mount.get("type") == "bind" and Path(str(mount.get("source", ""))).name == ".env":
                errors.append(f"{name}: bind-mounts a .env file")
    test = services.get("test")
    if test is not None:
        env = test.get("environment") or {}
        # Host names only: the synthetic file points at the isolated test stack.
        db_host = (_db_parts(str(env.get(P + "DATABASE_URL", ""))) or ("",) * 5)[3]
        redis_host = urlsplit(str(env.get(P + "REDIS_URL", ""))).hostname or ""
        if db_host != "postgres-test" or redis_host != "redis-test":
            errors.append("test: must target only the isolated postgres-test/redis-test hosts")
        if env.get(P + "ENVIRONMENT") != "test":
            errors.append("test: MYKHAYA_ENVIRONMENT must be test")
        if test.get("volumes"):
            errors.append("test: must not mount secrets or data volumes")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--root", type=Path)
    target.add_argument("--check-resolved", metavar="JSON",
                        help="'-' to read `docker compose config --format json` from stdin")
    target.add_argument("--split-legacy-env", metavar="DOTENV", type=Path,
                        help="write the service files from a legacy DEV .env into --out")
    parser.add_argument("--out", type=Path, help="with --split-legacy-env: the new root")
    parser.add_argument("--config-root", type=Path,
                        help="with --check-resolved: also prove provenance against this root")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--skip-permissions", action="store_true",
                        help="only for non-POSIX development hosts; never on the DEV server")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="dev",
                        help="dev (default) or prod: which environment's contract applies")
    parser.add_argument("--probe-image", metavar="IMAGE",
                        help="with --root: the locally built API image used to inspect the "
                             "protected key directories as the service identity (never pulled)")
    args = parser.parse_args(argv)
    profile = PROFILES[args.profile]
    if args.split_legacy_env:
        if args.out is None:
            parser.error("--split-legacy-env requires --out")
        legacy, problems = parse_env_file(args.split_legacy_env)
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        files, report = split_legacy_env(legacy, profile)
        write_split(files, args.out, profile)
        print(f"Wrote {len(files)} files to {args.out} (values not shown).")
        for heading, names in report.items():
            print(f"{heading}: {', '.join(names) if names else 'none'}")
        print("Next: add any missing key-directory paths to compose.env, then run "
              "--root validation before cutover.")
        return 0
    model_arg = args.check_resolved
    if model_arg:
        source = sys.stdin if model_arg == "-" else open(model_arg, encoding="utf-8")
        try:
            model = json.load(source)
        except ValueError:
            print("ERROR: the merged Compose model is not valid JSON", file=sys.stderr)
            return 1
        finally:
            if source is not sys.stdin:
                source.close()
        errors = check_resolved_model(model, args.repo_root, profile)
        errors += check_secret_mounts(model, args.config_root, profile)
        if args.config_root is not None:
            errors += check_provenance(model, args.config_root, profile)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        if errors:
            print(f"Merged {profile.label} Compose model violates the service configuration "
                  "contract", file=sys.stderr)
            return 1
        print(f"Merged {profile.label} Compose model matches the service configuration contract")
        return 0
    check_perms = not args.skip_permissions
    if check_perms and os.name != "posix":
        print("ERROR: permission checks need a POSIX host; pass --skip-permissions only for "
              "local synthetic validation", file=sys.stderr)
        return 2
    probe = postgres_probe = None
    if check_perms and args.probe_image:
        try:
            probe = docker_key_dir_probe(args.probe_image)
            if profile.file_backed:
                postgres_probe = docker_key_dir_probe(args.probe_image,
                                                      user=f"{POSTGRES_UID}:{POSTGRES_GID}")
        except ProbeFailure as exc:
            print(f"ERROR: key-directory probe: {exc}", file=sys.stderr)
            return 1
    report = validate_root(args.root, repo_root=args.repo_root, check_perms=check_perms,
                           probe=probe, profile=profile, postgres_probe=postgres_probe)
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if report.errors:
        print(f"{profile.label} service configuration validation failed:", file=sys.stderr)
        for error in report.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"{profile.label} service configuration validation passed "
          f"({len(profile.contracts)} files checked"
          f"{'' if check_perms else '; permissions NOT checked'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
