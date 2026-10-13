"""Sensitive Data Protection Phase 2D: Driveway ciphertext-first reads.

With MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ on, a stored ciphertext is the
authoritative registration/VIN; plaintext is used only where the ciphertext
column is NULL; a ciphertext that will not decrypt fails safely with no
plaintext fallback. VIN is decrypted only after visibility is decided. Keys
are deterministic test-only keyrings.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select
from structlog.testing import capture_logs
from test_driveway_field_encryption import KEYRING, VIN, _body, _home, _row
from test_driveway_reminders import ORIGIN, PASSWORD, add_partner, unsafe

import mykhaya.driveway_sensitive as driveway_sensitive
from mykhaya.config import Settings, get_settings
from mykhaya.crypto import KeyUnavailableError, StaticKeyring
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import User, Vehicle

REGISTRATION = "AP22 OOJ"
GENERIC_503 = "Vehicle details can't be loaded right now. Please try again later."


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _settings(*, write: bool, read: bool) -> Settings:
    return get_settings().model_copy(
        update={"driveway_field_encryption_write": write, "driveway_field_encryption_read": read}
    )


def _use(write: bool, read: bool) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings(write=write, read=read)


# Columns a test deliberately tampered with, keyed by vehicle id, holding the
# ORIGINAL values; restored at teardown so corrupt rows never leak into other
# tests (driveway_ciphertext_check scans the whole shared test table).
_ORIGINALS: dict[str, dict[str, Any]] = {}


@pytest.fixture(autouse=True)
async def _reset_overrides(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    yield
    app.dependency_overrides.pop(get_settings, None)
    async with SessionFactory() as db:
        for vehicle_id, originals in _ORIGINALS.items():
            row = await db.get(Vehicle, uuid.UUID(vehicle_id))
            if row is not None:
                for key, value in originals.items():
                    setattr(row, key, value)
        await db.commit()
    _ORIGINALS.clear()


async def _create(client: AsyncClient, home_id: uuid.UUID, body: dict[str, object]) -> dict:
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/vehicles", json=body)
    assert response.status_code == 201, response.text
    _assert_no_ciphertext(response.text)
    return response.json()


async def _set_columns(vehicle_id: str, **values: Any) -> None:
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(vehicle_id))
        assert row is not None
        originals = _ORIGINALS.setdefault(vehicle_id, {})
        for key, value in values.items():
            originals.setdefault(key, getattr(row, key))
            setattr(row, key, value)
        await db.commit()


def _assert_no_ciphertext(text: str) -> None:
    assert "ciphertext" not in text and "mkf1." not in text


def _tamper(envelope: str) -> str:
    """Flip one character of the ciphertext body (still well-formed base64url)."""
    head, body = envelope.rsplit(".", 1)
    middle = len(body) // 2
    flipped = "A" if body[middle] != "A" else "B"
    return f"{head}.{body[:middle]}{flipped}{body[middle + 1 :]}"


async def _encrypted_vehicle(client: AsyncClient, prefix: str) -> tuple[uuid.UUID, uuid.UUID, dict]:
    _use(write=True, read=False)
    owner_id, home_id = await _home(client, prefix)
    vehicle = await _create(client, home_id, _body(owner_id, registration=REGISTRATION, vin=VIN))
    return owner_id, home_id, vehicle


async def _detail(client: AsyncClient, home_id: uuid.UUID, vehicle_id: str) -> Any:
    return await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}")


# --- 1. Read flag off ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_flag_off_uses_plaintext_exactly_as_before(client: AsyncClient) -> None:
    _, home_id, vehicle = await _encrypted_vehicle(client, "p2d-off")
    # Plaintext deliberately disagrees with the (valid) ciphertext.
    await _set_columns(vehicle["id"], registration="PLAIN 0FF", vin="PLAINVIN000000001")
    _use(write=True, read=False)
    response = await _detail(client, home_id, vehicle["id"])
    assert response.status_code == 200
    assert response.json()["registration"] == "PLAIN 0FF"
    assert response.json()["vin"] == "PLAINVIN000000001"


def test_read_flag_defaults_to_false_and_is_independent_of_write() -> None:
    fields = Settings.model_fields
    assert fields["driveway_field_encryption_read"].default is False
    assert fields["driveway_field_encryption_write"].default is False
    settings = _settings(write=True, read=False)
    assert settings.driveway_field_encryption_write and not settings.driveway_field_encryption_read


# --- 2/3. Read flag on: ciphertext is authoritative --------------------------------------


@pytest.mark.asyncio
async def test_read_flag_on_returns_decrypted_values_even_when_plaintext_disagrees(
    client: AsyncClient,
) -> None:
    _, home_id, vehicle = await _encrypted_vehicle(client, "p2d-on")
    _use(write=True, read=True)
    agreeing = await _detail(client, home_id, vehicle["id"])
    assert agreeing.status_code == 200
    assert agreeing.json()["registration"] == REGISTRATION and agreeing.json()["vin"] == VIN

    # Proof the ciphertext — not the plaintext — is now the source of truth.
    await _set_columns(vehicle["id"], registration="PLAIN DIFF", vin="PLAINVIN000000002")
    detail = await _detail(client, home_id, vehicle["id"])
    listing = await client.get(f"/api/v1/homes/{home_id}/vehicles")
    assert detail.status_code == 200 and listing.status_code == 200
    assert detail.json()["registration"] == REGISTRATION and detail.json()["vin"] == VIN
    item = next(i for i in listing.json()["items"] if i["id"] == vehicle["id"])
    assert item["registration"] == REGISTRATION and item["vin"] == VIN
    for response in (detail, listing):
        _assert_no_ciphertext(response.text)
        assert "PLAIN DIFF" not in response.text


# --- 4. Missing ciphertext: transitional fallback ---------------------------------------


@pytest.mark.asyncio
async def test_null_ciphertext_falls_back_to_plaintext_and_logs_an_event_only(
    client: AsyncClient,
) -> None:
    _use(write=False, read=False)
    owner_id, home_id = await _home(client, "p2d-fallback")
    vehicle = await _create(client, home_id, _body(owner_id, registration=REGISTRATION, vin=VIN))
    assert (await _row(vehicle["id"])).registration_ciphertext is None
    _use(write=False, read=True)
    with capture_logs() as logs:
        response = await _detail(client, home_id, vehicle["id"])
    assert response.status_code == 200
    assert response.json()["registration"] == REGISTRATION and response.json()["vin"] == VIN
    fallbacks = [e for e in logs if e["event"] == "driveway.sensitive_read_plaintext_fallback"]
    assert {e["field"] for e in fallbacks} == {"registration", "vin"}
    # No value anywhere in the logs; the Phase 2D events carry no IDs either
    # (the pre-existing request log line legitimately records the URL path).
    rendered = json.dumps(logs, default=str)
    assert REGISTRATION not in rendered and VIN not in rendered
    assert all(set(event) == {"field", "event", "log_level"} for event in fallbacks)


# --- 5/6. Integrity failures: no fallback, generic error ---------------------------------


@pytest.mark.asyncio
async def test_corrupt_ciphertext_fails_safely_without_plaintext_fallback(
    client: AsyncClient,
) -> None:
    _, home_id, vehicle = await _encrypted_vehicle(client, "p2d-corrupt")
    row = await _row(vehicle["id"])
    assert row.registration_ciphertext
    tampered = _tamper(row.registration_ciphertext)
    await _set_columns(vehicle["id"], registration_ciphertext=tampered)
    _use(write=True, read=True)
    with capture_logs() as logs:
        detail = await _detail(client, home_id, vehicle["id"])
        listing = await client.get(f"/api/v1/homes/{home_id}/vehicles")
    for response in (detail, listing):
        assert response.status_code == 503
        assert response.json() == {"detail": GENERIC_503}
        assert REGISTRATION not in response.text
        _assert_no_ciphertext(response.text)
    failures = [e for e in logs if e["event"] == "driveway.sensitive_read_failed"]
    assert failures and {e["field"] for e in failures} == {"registration"}
    assert {e["error"] for e in failures} == {"SensitiveValueDecryptionError"}
    assert all(set(event) == {"field", "error", "event", "log_level"} for event in failures)
    rendered = json.dumps(logs, default=str)
    for secret in (REGISTRATION, VIN, tampered, tampered.rsplit(".", 1)[1]):
        assert secret not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown_key_id", "wrong_key", "missing_keyring", "malformed"])
async def test_key_and_envelope_failures_fail_safely(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _, home_id, vehicle = await _encrypted_vehicle(client, f"p2d-{failure.replace('_', '-')}")
    if failure == "unknown_key_id":
        other = StaticKeyring(
            purpose="field-encryption",
            environment="test",
            active="other",
            keys={"other": hashlib.sha256(b"mykhaya-test-only-key:other").digest()},
        )
        monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: other)
    elif failure == "wrong_key":
        impostor = StaticKeyring(
            purpose="field-encryption",
            environment="test",
            active="t2b",
            keys={"t2b": hashlib.sha256(b"mykhaya-test-only-key:impostor").digest()},
        )
        monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: impostor)
    elif failure == "missing_keyring":

        def unavailable() -> StaticKeyring:
            raise KeyUnavailableError("No field-encryption keyring is provisioned.")

        monkeypatch.setattr(driveway_sensitive, "get_field_keyring", unavailable)
    else:
        await _set_columns(vehicle["id"], registration_ciphertext="mkf1.t2b.not-a-valid-envelope")
    _use(write=True, read=True)
    response = await _detail(client, home_id, vehicle["id"])
    assert response.status_code == 503
    assert response.json() == {"detail": GENERIC_503}
    assert REGISTRATION not in response.text and VIN not in response.text


# --- 7. VIN authorization: decrypt only after visibility --------------------------------


@pytest.mark.asyncio
async def test_vin_is_never_decrypted_for_a_viewer_who_may_not_see_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id, home_id, vehicle = await _encrypted_vehicle(client, "p2d-vin")
    # Corrupt the VIN envelope: any attempt to decrypt it would 503, so a 200
    # for the partner proves no VIN decryption was attempted at all.
    row = await _row(vehicle["id"])
    assert row.vin_ciphertext
    await _set_columns(vehicle["id"], vin_ciphertext=_tamper(row.vin_ciphertext))
    purposes: list[str] = []
    real_decrypt = driveway_sensitive.decrypt_sensitive_value

    def spy(envelope: str, *, binding: Any, keyring: Any) -> str:
        purposes.append(binding.purpose)
        return real_decrypt(envelope, binding=binding, keyring=keyring)

    monkeypatch.setattr(driveway_sensitive, "decrypt_sensitive_value", spy)
    partner_id = await add_partner(home_id, "p2d-vin-partner")
    _use(write=True, read=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner:
        async with SessionFactory() as db:
            partner_user = await db.get(User, partner_id)
            assert partner_user is not None
            email = partner_user.email
        login = await unsafe(
            partner, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200
        detail = await _detail(partner, home_id, vehicle["id"])
        listing = await partner.get(f"/api/v1/homes/{home_id}/vehicles")
    for response in (detail, listing):
        assert response.status_code == 200, response.text
        _assert_no_ciphertext(response.text)
    assert detail.json()["registration"] == REGISTRATION
    assert detail.json().get("vin") is None
    assert "vehicle.vin" not in purposes and "vehicle.registration" in purposes

    # The owner IS entitled, so the (corrupt) VIN is decrypted — and fails safely.
    purposes.clear()
    owner_view = await _detail(client, home_id, vehicle["id"])
    assert owner_view.status_code == 503 and "vehicle.vin" in purposes
    assert owner_id  # owner session is `client`


# --- 8/11. API contract and existing behaviour with both flags on --------------------------


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("flags_on", [True, False])
async def test_driveway_flows_stay_compatible(client: AsyncClient, flags_on: bool) -> None:
    _use(write=flags_on, read=flags_on)
    owner_id, home_id = await _home(client, f"p2d-compat-{str(flags_on).lower()}")
    vehicle = await _create(client, home_id, _body(owner_id, registration=REGISTRATION, vin=VIN))
    assert vehicle["registration"] == REGISTRATION and vehicle["vin"] == VIN
    base = f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}"

    updated = await unsafe(
        client,
        "PATCH",
        base,
        json=_body(
            owner_id,
            registration="AB12 CDE",
            vin=VIN,
            nickname="Edited",
            expected_updated_at=vehicle["updated_at"],
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["registration"] == "AB12 CDE" and updated.json()["vin"] == VIN

    photo = await unsafe(
        client, "POST", f"{base}/photo", files={"file": ("c.png", _png(), "image/png")}
    )
    assert photo.status_code == 200, photo.text
    assert photo.json()["registration"] == "AB12 CDE"
    reminder = await unsafe(
        client,
        "POST",
        f"{base}/reminders",
        json={"title": "MOT due", "due_date": "2027-01-01"},
    )
    assert reminder.status_code == 201, reminder.text
    reminders = await client.get(f"{base}/reminders")
    assert reminders.status_code == 200 and len(reminders.json()["items"]) == 1
    removed_photo = await unsafe(client, "DELETE", f"{base}/photo")
    assert removed_photo.status_code == 200

    listing = await client.get(f"/api/v1/homes/{home_id}/vehicles")
    detail = await client.get(base)
    for response in (updated, photo, removed_photo, listing, detail, reminders):
        _assert_no_ciphertext(response.text)
    assert detail.json()["registration"] == "AB12 CDE"


# --- 9. Home Migration export ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_export_carries_logical_values_never_ciphertext(
    client: AsyncClient, tmp_path: Path
) -> None:
    from mykhaya.tools.home_migration import MigrationError, export_home

    _, home_id, vehicle = await _encrypted_vehicle(client, "p2d-export")
    await _set_columns(vehicle["id"], registration="PLAIN EXPT")

    def exported(read: bool) -> Any:
        settings = _settings(write=True, read=read).model_copy(
            update={"environment": "development"}
        )
        return export_home(home_id, tmp_path / f"package-{read}.json", settings)

    with_read = await exported(True)
    rows = with_read["data"]["vehicles"]
    assert [r["registration"] for r in rows] == [REGISTRATION]  # from ciphertext
    assert [r["vin"] for r in rows] == [VIN]
    serialised = json.dumps(with_read)
    assert "ciphertext" not in serialised and "mkf1." not in serialised

    without_read = await exported(False)
    assert [r["registration"] for r in without_read["data"]["vehicles"]] == ["PLAIN EXPT"]
    assert "ciphertext" not in json.dumps(without_read)

    row = await _row(vehicle["id"])
    assert row.registration_ciphertext
    await _set_columns(vehicle["id"], registration_ciphertext=_tamper(row.registration_ciphertext))
    with pytest.raises(MigrationError, match="protected details could not be read"):
        await exported(True)


# --- 10. Provider-facing helper ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_registration_comes_through_the_ciphertext_first_read(
    client: AsyncClient,
) -> None:
    _, _, vehicle = await _encrypted_vehicle(client, "p2d-provider")
    await _set_columns(vehicle["id"], registration="PLAIN PROV")
    async with SessionFactory() as db:
        row = await db.scalar(select(Vehicle).where(Vehicle.id == uuid.UUID(vehicle["id"])))
    assert row is not None
    assert (
        driveway_sensitive.registration_for_provider(row, _settings(write=True, read=True))
        == REGISTRATION
    )
    assert (
        driveway_sensitive.registration_for_provider(row, _settings(write=True, read=False))
        == "PLAIN PROV"
    )


def test_no_application_code_reads_stored_identifiers_directly() -> None:
    """Static guard: outside the central module (and the parity/backfill
    tooling, which must compare raw columns), nothing reads a stored
    vehicle's registration/VIN attribute directly."""
    import re

    root = Path(__file__).resolve().parents[1] / "mykhaya"
    allowed = {
        "driveway_sensitive.py",
        "crypto/field.py",  # documentation comment naming the purpose label only
        "tools/driveway_ciphertext_check.py",
        "tools/driveway_ciphertext_backfill.py",
        "tools/driveway_nickname_audit.py",
        "models.py",
    }
    pattern = re.compile(r"\b(vehicle|row|Vehicle)\.(registration|vin)\b(?!_)")
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.relative_to(root).as_posix() not in allowed
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
