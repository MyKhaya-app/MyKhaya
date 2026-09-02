from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import EmailStr, TypeAdapter, ValidationError

from mykhaya.config import Settings
from mykhaya.url_validation import is_valid_http_url

SettingValueType = Literal["text", "email", "url", "boolean", "integer", "list"]
SettingRisk = Literal["normal", "sensitive"]
# "effective": actually consumed by running code today.
# "informational": stored/displayed with no behavioural claim either way.
# "not_enforced": a placeholder — no code path reads it yet. See the
# grep-verified runtime-consumption audit in
# docs/architecture/platform-control-centre.md before changing this for any
# key; PCC confirmation copy is driven directly by this field and must never
# claim an operational effect a "not_enforced" setting doesn't have.
SettingRuntimeEffect = Literal["effective", "informational", "not_enforced"]


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    description: str
    section: str
    value_type: SettingValueType
    python_type: type
    risk: SettingRisk
    runtime_effect: SettingRuntimeEffect
    consumer_visible: bool = False


SETTINGS_SCHEMA: dict[str, SettingDefinition] = {
    "platform_display_name": SettingDefinition(
        key="platform_display_name",
        label="Platform name",
        description="The name shown for MyKhaya in administrator-facing surfaces.",
        section="General",
        value_type="text",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
    "support_contact_address": SettingDefinition(
        key="support_contact_address",
        label="Support email address",
        description="Where support-related correspondence should be directed.",
        section="Support",
        value_type="email",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
    "service_status_url": SettingDefinition(
        key="service_status_url",
        label="Service status page",
        description="The page consumers are sent to from Help & Support to check MyKhaya's status.",
        section="Support",
        value_type="url",
        python_type=str,
        risk="normal",
        runtime_effect="effective",
        consumer_visible=True,
    ),
    "registration_enabled": SettingDefinition(
        key="registration_enabled",
        label="Allow new registrations",
        description="Whether new accounts may be created.",
        section="Registration & Access",
        value_type="boolean",
        python_type=bool,
        risk="sensitive",
        runtime_effect="not_enforced",
    ),
    "invite_only_mode": SettingDefinition(
        key="invite_only_mode",
        label="Invite-only registration",
        description="Restrict new registrations to holders of a valid invitation.",
        section="Registration & Access",
        value_type="boolean",
        python_type=bool,
        risk="sensitive",
        runtime_effect="not_enforced",
    ),
    "email_verification_required": SettingDefinition(
        key="email_verification_required",
        label="Require email verification",
        description="Require a new account to verify its email address before use.",
        section="Registration & Access",
        value_type="boolean",
        python_type=bool,
        risk="sensitive",
        runtime_effect="not_enforced",
    ),
    "allowed_registration_domains": SettingDefinition(
        key="allowed_registration_domains",
        label="Allowed registration domains",
        description="If set, new registrations are limited to these email domains.",
        section="Registration & Access",
        value_type="list",
        python_type=list,
        risk="sensitive",
        runtime_effect="not_enforced",
    ),
    "invitation_expiry_days": SettingDefinition(
        key="invitation_expiry_days",
        label="Invitation expiry",
        description="How many days a Home invitation remains valid for, in days.",
        section="Registration & Access",
        value_type="integer",
        python_type=int,
        risk="normal",
        runtime_effect="not_enforced",
    ),
    "maximum_homes_per_user": SettingDefinition(
        key="maximum_homes_per_user",
        label="Maximum Homes per user",
        description="The most Homes a single user may belong to.",
        section="Home Limits",
        value_type="integer",
        python_type=int,
        risk="normal",
        runtime_effect="not_enforced",
    ),
    "maximum_members_per_home": SettingDefinition(
        key="maximum_members_per_home",
        label="Maximum members per Home",
        description="The most members a single Home may have.",
        section="Home Limits",
        value_type="integer",
        python_type=int,
        risk="normal",
        runtime_effect="not_enforced",
    ),
    "maintenance_mode": SettingDefinition(
        key="maintenance_mode",
        label="Maintenance mode",
        description="Take MyKhaya offline for maintenance.",
        section="General",
        value_type="boolean",
        python_type=bool,
        risk="sensitive",
        runtime_effect="not_enforced",
    ),
    "default_locale": SettingDefinition(
        key="default_locale",
        label="Default language / locale",
        description="The locale used for new accounts unless they choose otherwise.",
        section="Regional",
        value_type="text",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
    "default_timezone": SettingDefinition(
        key="default_timezone",
        label="Default timezone",
        description="The timezone used for new Homes unless they choose otherwise.",
        section="Regional",
        value_type="text",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
    "privacy_notice_version": SettingDefinition(
        key="privacy_notice_version",
        label="Privacy notice version",
        description="The version identifier of the currently published Privacy Notice.",
        section="Legal",
        value_type="text",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
    "terms_version": SettingDefinition(
        key="terms_version",
        label="Terms version",
        description="The version identifier of the currently published Terms of Service.",
        section="Legal",
        value_type="text",
        python_type=str,
        risk="normal",
        runtime_effect="informational",
    ),
}

# These keys are surfaced read-only in GET /platform/settings under
# "environment" (see routers/platform.py) and must never be accepted by
# PUT /platform/settings/{key} — they are deployment/infrastructure
# configuration, not administrator-managed operational settings.
ENVIRONMENT_ONLY_KEYS = frozenset({"public_url", "admin_url", "status_url"})

_EMAIL_ADAPTER: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


def validate_setting_value(definition: SettingDefinition, value: Any) -> None:
    """Raises ValueError with a user-facing message if `value` is not a valid
    value for `definition`. Extends, rather than duplicates, the original
    isinstance/range checks that already lived inline in update_setting."""
    if definition.python_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("That value must be a whole number.")
        if not 1 <= value <= 10_000:
            raise ValueError("That numeric value is outside the allowed range.")
        return
    if not isinstance(value, definition.python_type):
        raise ValueError("That setting or value is not valid.")
    # isinstance narrows `value` to `object` here (definition.python_type is a
    # plain `type`, not a literal class mypy can use to narrow further) —
    # re-widen back to Any rather than fighting the checker with casts at
    # every call below.
    checked_value: Any = value
    if definition.value_type == "url":
        if not is_valid_http_url(checked_value):
            raise ValueError("That must be a valid http(s) URL.")
        parts = urlsplit(checked_value)
        if parts.username is not None or parts.password is not None:
            raise ValueError("That URL must not contain a username or password.")
    elif definition.value_type == "email":
        try:
            _EMAIL_ADAPTER.validate_python(checked_value)
        except ValidationError as exc:
            raise ValueError("That must be a valid email address.") from exc
    elif definition.value_type == "list":
        if not all(isinstance(item, str) and item.strip() for item in checked_value):
            raise ValueError("That must be a list of non-empty text values.")


def resolve_environment_fallback(key: str, settings: Settings) -> Any | None:
    """The one place a setting key maps to its environment bootstrap/default
    value, used only when no PlatformSetting row exists yet for that key.
    Adding a future fallback means adding one line here, nowhere else."""
    if key == "service_status_url":
        return settings.status_url
    return None
