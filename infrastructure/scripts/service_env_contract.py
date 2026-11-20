#!/usr/bin/env python3
"""DEV service-specific configuration contract and static validator (F-03 Stage 3A).

This module is the single machine-readable source for which variables each
backend service may receive from the DEV configuration root
(``MYKHAYA_DEV_CONFIG_ROOT``, normally ``/etc/mykhaya/dev``). The allow-lists
are derived from what the code actually reads (see
docs/operations/service-configuration-contracts.md), not from convenience.

The validator never prints, hashes or logs a value. Values are only compared
with each other in memory (for example, that the application database password
in api.env matches the one PostgreSQL was initialised with) and reported by
variable name.

Usage:
    service_env_contract.py --root /etc/mykhaya/dev [--repo-root PATH]
                            [--skip-permissions]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
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


def check_root_location(root: Path, repo_root: Path | None, report: Report) -> None:
    text = str(root)
    if not (root.is_absolute() or text.startswith("/")):
        report.error("configuration root must be an absolute path")
    if _is_production_path(text):
        report.error("configuration root points at a production path; DEV must use its own root")
    if not root.is_dir():
        report.error("configuration root does not exist or is not a directory")
        return
    resolved = root.resolve()
    if _is_production_path(str(resolved)):
        report.error("configuration root resolves (via a link) to a production path")
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


def check_contract(contract: FileContract, values: dict[str, str], report: Report) -> None:
    names = set(values)
    # compose.env is the interpolation source that feeds the pinned values.
    pinned = frozenset() if contract is COMPOSE else PINNED_BY_COMPOSE
    forbidden = contract.forbidden - contract.allowed
    for name in sorted(names & pinned):
        report.error(f"{contract.name}: {name} is pinned by compose.dev.yml/compose.yml; "
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
    for name in sorted(names & JSON_LIST_NAMES):
        try:
            parsed = json.loads(values[name])
            if not isinstance(parsed, list) or not all(isinstance(i, str) for i in parsed):
                raise ValueError
        except ValueError:
            report.error(f"{contract.name}: {name} must be a JSON array of strings")


def check_cross_file(files: dict[str, dict[str, str]], report: Report) -> None:
    api, worker, scheduler = files.get("api.env", {}), files.get("worker.env", {}), \
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
    pg_values = [postgres.get(k) for k in ("POSTGRES_PASSWORD", P + "MIGRATION_DB_PASSWORD",
                                           P + "DB_PASSWORD")]
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
    for name, values in files.items():
        for key, prefix in ((P + "APPLE_PRIVATE_KEY_FILE", "/run/secrets/mykhaya-apple/"),
                            (P + "FIELD_ENCRYPTION_KEYS_FILE", "/run/secrets/mykhaya/"),
                            (P + "BLIND_INDEX_KEYS_FILE", "/run/secrets/mykhaya/")):
            if values.get(key) and not values[key].startswith(prefix):
                report.error(f"{name}: {key} must be inside the read-only {prefix} mount")
        if values.get(P + "APPLE_PRIVATE_KEY") and values.get(P + "APPLE_PRIVATE_KEY_FILE"):
            report.error(f"{name}: set either MYKHAYA_APPLE_PRIVATE_KEY or "
                         "MYKHAYA_APPLE_PRIVATE_KEY_FILE, not both (use the file in DEV)")


def check_secret_dirs(compose: dict[str, str], repo_root: Path | None, check_perms: bool,
                      report: Report) -> None:
    for key in (P + "FIELD_KEYS_HOST_DIR", P + "APPLE_KEY_HOST_DIR"):
        value = compose.get(key, "")
        if not value:
            continue
        path = Path(value)
        if not (path.is_absolute() or value.startswith("/")):
            report.error(f"compose.env: {key} must be an absolute host path")
            continue
        if _is_production_path(value):
            report.error(f"compose.env: {key} points at a production path")
            continue
        if repo_root is not None and _inside(path.resolve(), repo_root.resolve()):
            report.error(f"compose.env: {key} is inside the repository working tree")
            continue
        if not path.is_dir():
            # Compose would silently create an empty root-owned directory.
            report.error(f"compose.env: {key} does not exist on this host")
            continue
        if _is_production_path(str(path.resolve())):
            report.error(f"compose.env: {key} resolves (via a link) to a production path")
        if check_perms:
            check_permissions(path, secret=True, is_dir=True, report=report, label=key)
            for child in sorted(path.iterdir()):
                check_permissions(child, secret=True, is_dir=child.is_dir(), report=report,
                                  label=f"{key}/{child.name}")


def validate_root(root: Path, *, repo_root: Path | None = None,
                  check_perms: bool = True) -> Report:
    report = Report()
    check_root_location(root, repo_root, report)
    if report.errors and not root.is_dir():
        return report
    if check_perms:
        check_permissions(root, secret=True, is_dir=True, report=report,
                          label="configuration root")
    files: dict[str, dict[str, str]] = {}
    for contract in CONTRACTS:
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
        check_contract(contract, values, report)
        files[contract.name] = values
    unexpected = sorted(p.name for p in root.iterdir()
                        if p.is_file() and p.name.endswith(".env")
                        and p.name not in {c.name for c in CONTRACTS})
    for name in unexpected:
        report.error(f"{name}: is not a recognised DEV configuration file "
                     "(test configuration is synthetic and tracked in the repository)")
    check_cross_file(files, report)
    check_secret_dirs(files.get("compose.env", {}), repo_root, check_perms, report)
    return report


# --- Legacy .env splitter (migration aid; never prints values) -----------------

# Legacy-only names and where they go instead.
LEGACY_RENAMES = {P + "POSTGRES_ADMIN_PASSWORD": "POSTGRES_PASSWORD"}
# Exactly the URLs compose.yml builds from the legacy passwords.
LEGACY_APP_URL = "postgresql+asyncpg://mykhaya_app:{}@postgres:5432/mykhaya"
LEGACY_MIGRATION_URL = "postgresql+asyncpg://mykhaya_migrator:{}@postgres:5432/mykhaya"
SPLIT_TARGETS = (COMPOSE, COMMON, API, WORKER, SCHEDULER, MIGRATE, POSTGRES)


def split_legacy_env(legacy: dict[str, str]) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Map a legacy DEV root .env onto the service files.

    Every name goes to every file whose contract allows it, so each provider
    group keeps reaching exactly the services it reaches today wherever the
    contract permits (for example, environment-configured Stripe still reaches
    the scheduler's monitoring). Returns (files, report); the report lists
    names only.
    """
    files: dict[str, dict[str, str]] = {c.name: {} for c in SPLIT_TARGETS}
    for name, value in legacy.items():
        target_name = LEGACY_RENAMES.get(name, name)
        for contract in SPLIT_TARGETS:
            if contract is COMMON or contract is COMPOSE:
                if target_name in contract.allowed:
                    files[contract.name][target_name] = value
                continue
            if target_name in contract.allowed and target_name not in COMMON.allowed:
                files[contract.name][target_name] = value
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
                                    "not a setting or Compose input (dropped)": []}
    placed = {n for values in files.values() for n in values} | set(LEGACY_RENAMES)
    for name in sorted(legacy):
        if name in placed:
            continue
        if name in PINNED_BY_COMPOSE:
            report["pinned (no effect today; dropped)"].append(name)
        else:
            report["not a setting or Compose input (dropped)"].append(name)
    # What each application service stops receiving compared with the legacy
    # env_file (every legacy name reached api, worker, scheduler and migrate).
    for service, file_names in (("api", ("common.env", "api.env")),
                                ("worker", ("common.env", "worker.env")),
                                ("scheduler", ("common.env", "scheduler.env")),
                                ("migrate", ("migrate.env",))):
        receives = set().union(*(files[f] for f in file_names))
        # Names Compose already pinned for this service (e.g. blank APNs for
        # api/scheduler/migrate) never reached it from the .env either.
        already_pinned = PINNED_BY_COMPOSE | RESTATED_ENVIRONMENT.get(service, frozenset())
        dropped = sorted(n for n in legacy if n.startswith(P) and n not in receives
                         and n not in already_pinned and n not in COMPOSE.allowed)
        report[f"no longer delivered to {service}"] = dropped
    return files, report


def write_split(files: dict[str, dict[str, str]], out: Path) -> None:
    """Write every file or none, never overwriting, with restrictive modes.

    Each file is first written under a temporary name in `out` and parsed back;
    only if every file reproduces its values exactly are they all renamed into
    place. Any failure removes the temporary files and leaves `out` unchanged.
    Messages never include a value.
    """
    if not out.is_dir():
        raise SystemExit(f"ERROR: {out} does not exist; create it first (mode 0750)")
    existing = [name for name in files if (out / name).exists()]
    if existing:
        raise SystemExit(f"ERROR: refusing to overwrite existing files: {', '.join(existing)}")
    staged: list[tuple[Path, Path]] = []
    try:
        for contract in SPLIT_TARGETS:
            mode = 0o600 if contract.secret_bearing else 0o640
            temporary = out / f".{contract.name}.split-{os.getpid()}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            staged.append((temporary, out / contract.name))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(f"# Generated from the legacy DEV .env by service_env_contract.py "
                             f"--split-legacy-env. Contract: {contract.name}.\n")
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


def check_provenance(model: dict, root: Path) -> list[str]:
    """Prove each service's merged environment comes only from the DEV root.

    Works with any Compose version: the merged environment must contain
    exactly the overlay's restated names plus the names in that service's own
    files, and every file-supplied value must arrive unchanged. A root .env (or
    any other source) still being loaded would add names. Values are compared
    in memory; only names are reported.
    """
    errors: list[str] = []
    services = model.get("services", {})
    for service, file_names in SERVICE_ENV_FILES.items():
        if service not in services:
            errors.append(f"{service}: missing from the merged Compose model")
            continue
        supplied: dict[str, str] = {}
        for file_name in file_names:
            path = root / file_name
            if path.is_file():
                values, _ = parse_env_file(path)
                supplied.update(values)
        restated = RESTATED_ENVIRONMENT[service]
        env = services[service].get("environment") or {}
        for name in sorted(set(env) - restated - set(supplied)):
            errors.append(f"{service}: receives {name} from outside MYKHAYA_DEV_CONFIG_ROOT")
        for name in sorted(set(supplied) - restated):
            if name not in env:
                errors.append(f"{service}: {name} from its file does not reach the container")
            # `compose config` prints every literal "$" as "$$".
            elif str(env[name]).replace("$$", "$") != supplied[name]:
                errors.append(f"{service}: {name} differs from its file (another source wins)")
    return errors


def check_resolved_model(model: dict, repo_root: Path) -> list[str]:
    """Allow-list the merged Compose model by variable name and mount target."""
    errors: list[str] = []
    services = model.get("services", {})
    for name, service in services.items():
        env = service.get("environment") or {}
        allowed = RESOLVED_ALLOWED.get(name)
        if allowed is not None:
            for var in sorted(set(env) - allowed):
                errors.append(f"{name}: receives {var}, which is outside its contract")
        if name not in {"postgres"}:
            for var in sorted(set(env) & BOOTSTRAP_PASSWORDS):
                errors.append(f"{name}: receives database bootstrap credential {var}")
        for var in sorted(MUST_BE_BLANK.get(name, set()) & set(env)):
            if env[var] not in ("", None):
                errors.append(f"{name}: {var} must be blank for this service")
        mounts = service.get("volumes") or []
        targets = {m.get("target") for m in mounts}
        if name in EXPECTED_MOUNTS and targets != EXPECTED_MOUNTS[name]:
            errors.append(f"{name}: mounts {sorted(t for t in targets if t)} but the contract is "
                          f"{sorted(EXPECTED_MOUNTS[name])}")
        for mount in mounts:
            if mount.get("target") in SECRET_MOUNT_TARGETS:
                if not mount.get("read_only"):
                    errors.append(f"{name}: secret mount {mount['target']} is not read-only")
                source = str(mount.get("source", ""))
                if _is_production_path(source):
                    errors.append(f"{name}: secret mount {mount['target']} uses a production path")
                if _inside(Path(source).resolve(), repo_root.resolve()):
                    errors.append(f"{name}: secret mount {mount['target']} comes from the repository")
            elif name not in EXPECTED_MOUNTS and name not in {"postgres", "caddy", "redis"} and \
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
    args = parser.parse_args(argv)
    if args.split_legacy_env:
        if args.out is None:
            parser.error("--split-legacy-env requires --out")
        legacy, problems = parse_env_file(args.split_legacy_env)
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        files, report = split_legacy_env(legacy)
        write_split(files, args.out)
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
        errors = check_resolved_model(model, args.repo_root)
        if args.config_root is not None:
            errors += check_provenance(model, args.config_root)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        if errors:
            print("Merged DEV Compose model violates the service configuration contract",
                  file=sys.stderr)
            return 1
        print("Merged DEV Compose model matches the service configuration contract")
        return 0
    check_perms = not args.skip_permissions
    if check_perms and os.name != "posix":
        print("ERROR: permission checks need a POSIX host; pass --skip-permissions only for "
              "local synthetic validation", file=sys.stderr)
        return 2
    report = validate_root(args.root, repo_root=args.repo_root, check_perms=check_perms)
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if report.errors:
        print("DEV service configuration validation failed:", file=sys.stderr)
        for error in report.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"DEV service configuration validation passed ({len(CONTRACTS)} files checked"
          f"{'' if check_perms else '; permissions NOT checked'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
