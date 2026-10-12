"""Central redaction for audit metadata *before it is stored*.

Audit rows are long-lived (administrative audit: 7 years) and travel into
every database backup, so they follow a stricter rule than log lines: record
who/what/when/which-resource and structural facts (IDs, enum values, counts,
booleans, timestamps, lifecycle states) — never personal content.

This applies everything ``syslog_forwarding.redact`` already removes from
logs (secrets, emails, names, titles, registrations, VINs…) plus
audit-specific categories that are acceptable in an operational log line but
not in a permanent record: free-text ``reason`` values, monetary amounts,
locations/addresses and insurance identifiers.

Values under a redacted key become ``"[REDACTED]"`` (the key is kept, so the
record still shows *that* the field was involved); a ``None`` value under a
private key stays ``None``. Secret-named keys keep their existing behaviour
(always ``"[REDACTED]"``). Everything else — UUIDs,
enums, numbers, booleans, nested structure — passes through unchanged.

``retain`` is an explicit, reviewed per-call exception for a field whose
retention is itself documented policy (e.g. the Home name on a permanent
Home-deletion record, see docs/security/data-retention.md). Use sparingly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mykhaya.syslog_forwarding import PRIVATE_NAMES, REDACTED, redact

AUDIT_PRIVATE_NAMES = frozenset(
    {
        "reason",
        "amount",
        "location",
        "location_text",
        "address",
        "postcode",
        "postal_code",
        "registration",
        "registration_number",
        "vin",
        "policy_number",
        "note",
        "notes",
        "home_name",
        "user_name",
        "full_name",
        "first_name",
        "last_name",
        "child_name",
        "member_name",
        "birth_day",
        "birth_month",
        "birth_year",
        "date_of_birth",
        "phone",
        "phone_number",
    }
)
AUDIT_PRIVATE_SUFFIXES = (
    "_reason",
    "_amount",
    "_email",
    "_registration",
    "_vin",
    "_policy_number",
    "_location",
    "_postcode",
    "_note",
    "_notes",
)
AUDIT_PRIVATE_PREFIXES = ("insurance_",)


def _is_audit_private(key: str) -> bool:
    lowered = key.casefold()
    return (
        lowered in AUDIT_PRIVATE_NAMES
        or lowered.endswith(AUDIT_PRIVATE_SUFFIXES)
        or lowered.startswith(AUDIT_PRIVATE_PREFIXES)
    )


def _redact_audit_value(value: Any, key: str | None, retain: frozenset[str]) -> Any:
    if key is not None and key.casefold() in retain:
        return value
    if key is not None and redact("", key) == REDACTED and key.casefold() not in PRIVATE_NAMES:
        # Secret-named key (password/token/api_key/…): redacted whole, even
        # when the value is a nested structure or None — unchanged behaviour.
        return REDACTED
    if key is not None and (_is_audit_private(key) or key.casefold() in PRIVATE_NAMES):
        # An absent value discloses nothing, and keeping None distinguishes
        # "was empty" from "held something" without revealing what.
        return None if value is None else REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_audit_value(item_value, str(item_key), retain)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_audit_value(item, None, retain) for item in value]
    # Fall through to the shared log redaction for secrets/private names and
    # secret-looking string content (bearer tokens, key=… pairs, URL creds).
    return redact(value, key)


def redact_audit_metadata(
    values: Mapping[str, Any] | None, *, retain: Iterable[str] = ()
) -> dict[str, Any]:
    retained = frozenset(key.casefold() for key in retain)
    return {
        str(key): _redact_audit_value(value, str(key), retained)
        for key, value in (values or {}).items()
    }
