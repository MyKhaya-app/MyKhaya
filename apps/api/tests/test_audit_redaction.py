"""Audit metadata is redacted *before storage*, not only before logging.

Unit-level: audit()/platform_audit() are called with a stub session that just
collects added rows, so these assertions inspect exactly what would be
written to audit_events / administrative_audit_events.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

from structlog.testing import capture_logs

from mykhaya.audit import audit
from mykhaya.audit_redaction import redact_audit_metadata
from mykhaya.models import AdministrativeAuditEvent, AuditEvent, PlatformRole
from mykhaya.platform_audit import platform_audit

# Fixed IDs (never uuid4) so a numeric sensitive value such as 1200 can never
# coincidentally appear inside a random UUID and make the leak checks flaky.
_IDS = iter(uuid.UUID(int=n) for n in range(1, 1000))


def _id() -> uuid.UUID:
    return next(_IDS)


SENSITIVE_VALUES = {
    "registration": "AP22 OOJ",
    "vin": "WBA00000000000000",
    "policy_number": "POL-123-SECRET",
    "insurance_provider_reference": "INS-REF-999",
    "address": "1 Acacia Avenue",
    "location_text": "Riverside School gates",
    "amount": 435.27,
    "planned_amount": 1200,
    "reason": "Custody arrangement changed after court hearing",
    "complimentary_reason": "Family friend of founder",
    "email": "megan@example.com",
    "recipient_email": "grandma@example.com",
    "display_name": "Megan Hales",
    "name": "The Hales Home",
    "title": "Hospital appointment",
    "note": "Owes £500 to bank",
    "birth_year": 2014,
}
STRUCTURAL = {
    "vehicle_id": str(_id()),
    "owner_user_id": str(_id()),
    "country_code": "GB",
    "lifecycle": "archived",
    "relationship": "partner",
    "source_event": "manual",
    "category_count": 3,
    "capacity_exempt": True,
    "template_type": "household_invitation",
    "enabled": False,
    "platform_display_name": None,
    "previous_source": "unset",
    "trigger": "legacy_snapshot_repair",
}


class _CollectingSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)


def _request() -> Any:
    return SimpleNamespace(state=SimpleNamespace(request_id="req-1"))


def _platform_context() -> Any:
    return SimpleNamespace(
        administrator=SimpleNamespace(id=_id(), role=PlatformRole.owner),
        session=SimpleNamespace(id=_id()),
        source_ip="127.0.0.1",
    )


def _assert_no_sensitive_values(rendered: str) -> None:
    for value in SENSITIVE_VALUES.values():
        assert str(value) not in rendered, value


def test_redaction_removes_personal_values_but_keeps_structure() -> None:
    result = redact_audit_metadata({**SENSITIVE_VALUES, **STRUCTURAL})
    for key in SENSITIVE_VALUES:
        assert result[key] == "[REDACTED]", key
    for key, value in STRUCTURAL.items():
        assert result[key] == value, key


def test_redaction_recurses_into_nested_structures() -> None:
    result = redact_audit_metadata(
        {
            "changes": {"vin": "WBA00000000000000", "count": 2},
            "items": [{"email": "a@example.com", "id": "x"}],
        }
    )
    assert result == {
        "changes": {"vin": "[REDACTED]", "count": 2},
        "items": [{"email": "[REDACTED]", "id": "x"}],
    }


def test_empty_private_values_stay_empty_and_secrets_stay_fully_redacted() -> None:
    result = redact_audit_metadata(
        {"email": None, "api_key": None, "client_secret": {"nested": "x"}, "token": "abc"}
    )
    assert result == {
        "email": None,
        "api_key": "[REDACTED]",
        "client_secret": "[REDACTED]",
        "token": "[REDACTED]",
    }


def test_secret_looking_text_inside_allowed_values_is_scrubbed() -> None:
    result = redact_audit_metadata({"detail": "Authorization: Bearer abc.def.ghi"})
    assert "abc.def.ghi" not in json.dumps(result)


def test_retain_is_an_explicit_per_call_exception() -> None:
    result = redact_audit_metadata(
        {"name": "Audited Home", "email": "x@example.com"}, retain={"name"}
    )
    assert result == {"name": "Audited Home", "email": "[REDACTED]"}


def test_household_audit_stores_and_logs_only_redacted_metadata() -> None:
    db = _CollectingSession()
    with capture_logs() as logs:
        audit(
            db,  # type: ignore[arg-type]
            _request(),
            "driveway.vehicle.updated",
            _id(),
            _id(),
            "vehicle",
            _id(),
            {**SENSITIVE_VALUES, **STRUCTURAL},
        )
    (row,) = db.added
    assert isinstance(row, AuditEvent)
    _assert_no_sensitive_values(json.dumps(row.metadata_, default=str))
    _assert_no_sensitive_values(json.dumps(logs, default=str))
    assert row.metadata_["vehicle_id"] == STRUCTURAL["vehicle_id"]
    assert row.metadata_["country_code"] == "GB"


def test_administrative_audit_stores_and_logs_only_redacted_values() -> None:
    db = _CollectingSession()
    with capture_logs() as logs:
        platform_audit(
            db,  # type: ignore[arg-type]
            _request(),  # type: ignore[arg-type]
            _platform_context(),
            "user.updated",
            "user",
            _id(),
            reason="Operator-entered justification",
            previous={**SENSITIVE_VALUES, "lifecycle": "active"},
            new={**SENSITIVE_VALUES, **STRUCTURAL, "password": "hunter2"},
        )
    (row,) = db.added
    assert isinstance(row, AdministrativeAuditEvent)
    stored = json.dumps([row.previous_values, row.new_values], default=str)
    _assert_no_sensitive_values(stored)
    _assert_no_sensitive_values(json.dumps(logs, default=str))
    assert "hunter2" not in stored
    assert row.new_values["lifecycle"] == "archived"
    assert row.previous_values["lifecycle"] == "active"
    # The dedicated operator-reason column is unchanged by metadata redaction.
    assert row.reason == "Operator-entered justification"


def test_administrative_audit_retain_keeps_only_the_named_field_in_storage() -> None:
    db = _CollectingSession()
    with capture_logs() as logs:
        platform_audit(
            db,  # type: ignore[arg-type]
            _request(),  # type: ignore[arg-type]
            _platform_context(),
            "home.permanently_deleted",
            "home",
            _id(),
            previous={"lifecycle": "archived", "name": "Audited Home", "email": "x@example.com"},
            retain=frozenset({"name"}),
        )
    (row,) = db.added
    assert row.previous_values == {
        "lifecycle": "archived",
        "name": "Audited Home",
        "email": "[REDACTED]",
    }
    # Retention applies to the stored record only; the forwarded log copy
    # is still fully redacted.
    assert "Audited Home" not in json.dumps(logs, default=str)
