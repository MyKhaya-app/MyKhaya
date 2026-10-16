"""Sensitive Data Protection Phase 2B: Driveway registration/VIN dual-write.

Plaintext stays authoritative for every read; with
MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE on, every registration/VIN write also
maintains an AES-256-GCM envelope bound to the vehicle's id and column. Keys
here are deterministic *test-only* keyrings — never real key material.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_driveway_reminders import (
    ORIGIN,
    create_driveway_home,
    create_verified_user,
    unique_email,
    unsafe,
)

import mykhaya.driveway_sensitive as driveway_sensitive
from mykhaya.config import Settings, get_settings
from mykhaya.crypto import (
    KeyUnavailableError,
    SensitiveValueDecryptionError,
    StaticKeyring,
    decrypt_sensitive_value,
)
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import registration_binding, vin_binding
from mykhaya.main import app
from mykhaya.models import Vehicle

REGISTRATION = "AP22 OOJ"
VIN = "WBA8E1C55JA000001"
API_ROOT = Path(__file__).resolve().parents[1] / "mykhaya"

KEYRING = StaticKeyring(
    purpose="field-encryption",
    environment="test",
    active="t2b",
    keys={"t2b": hashlib.sha256(b"mykhaya-test-only-key:phase-2b").digest()},
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _settings(*, write: bool) -> Settings:
    return get_settings().model_copy(update={"driveway_field_encryption_write": write})


@pytest.fixture
def dual_write(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Flag on, with a usable test keyring."""
    settings = _settings(write=True)
    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def flag_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    settings = _settings(write=False)

    def must_not_be_called() -> StaticKeyring:
        raise AssertionError("the keyring must not be touched with dual-write off")

    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", must_not_be_called)
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


async def _home(client: AsyncClient, prefix: str) -> tuple[uuid.UUID, uuid.UUID]:
    owner_id = await create_verified_user(client, unique_email(prefix), "Owner")
    home_id = await create_driveway_home(client, f"Phase 2B {prefix}")
    return owner_id, home_id


def _body(owner_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "nickname": "Family car",
        "owner_user_id": str(owner_id),
        "country_code": "GB",
        "registration": REGISTRATION,
        "vin": VIN,
    }
    body.update(overrides)
    return body


async def _create(client: AsyncClient, home_id: uuid.UUID, body: dict[str, object]) -> dict:
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/vehicles", json=body)
    assert response.status_code == 201, response.text
    _assert_no_ciphertext_in(response.text)
    return response.json()


async def _update(
    client: AsyncClient, home_id: uuid.UUID, vehicle: dict, owner_id: uuid.UUID, **changes: object
) -> dict:
    body = _body(
        owner_id,
        nickname=vehicle["nickname"],
        registration=vehicle["registration"],
        vin=vehicle.get("vin"),
        expected_updated_at=vehicle["updated_at"],
    )
    body.update(changes)
    response = await unsafe(
        client, "PATCH", f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}", json=body
    )
    assert response.status_code == 200, response.text
    _assert_no_ciphertext_in(response.text)
    return response.json()


async def _row(vehicle_id: str) -> Vehicle:
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(vehicle_id))
        assert row is not None
        return row


def _assert_no_ciphertext_in(text: str) -> None:
    assert "ciphertext" not in text
    assert "mkf1." not in text


# --- 1. Flag off -------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_writes_plaintext_only(client: AsyncClient, flag_off: Settings) -> None:
    owner_id, home_id = await _home(client, "p2b-off")
    vehicle = await _create(client, home_id, _body(owner_id))
    row = await _row(vehicle["id"])
    assert (row.registration, row.vin) == (REGISTRATION, VIN)
    assert row.registration_ciphertext is None and row.vin_ciphertext is None
    assert vehicle["registration"] == REGISTRATION and vehicle["vin"] == VIN


def test_flag_defaults_to_false() -> None:
    assert Settings.model_fields["driveway_field_encryption_write"].default is False


# --- 2. Flag on: create --------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_create_dual_writes_registration_and_vin(
    client: AsyncClient, dual_write: Settings
) -> None:
    owner_id, home_id = await _home(client, "p2b-create")
    vehicle = await _create(client, home_id, _body(owner_id))
    row = await _row(vehicle["id"])
    assert (row.registration, row.vin) == (REGISTRATION, VIN)
    assert row.registration_ciphertext and row.registration_ciphertext.startswith("mkf1.t2b.")
    assert row.vin_ciphertext and row.vin_ciphertext.startswith("mkf1.t2b.")
    assert REGISTRATION not in row.registration_ciphertext and VIN not in row.vin_ciphertext
    binding_id = uuid.UUID(vehicle["id"])
    assert (
        decrypt_sensitive_value(
            row.registration_ciphertext, binding=registration_binding(binding_id), keyring=KEYRING
        )
        == REGISTRATION
    )
    assert (
        decrypt_sensitive_value(
            row.vin_ciphertext, binding=vin_binding(binding_id), keyring=KEYRING
        )
        == VIN
    )
    # Reads stay plaintext and the response contract is unchanged.
    assert vehicle["registration"] == REGISTRATION and vehicle["vin"] == VIN
    detail = await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")
    listing = await client.get(f"/api/v1/homes/{home_id}/vehicles")
    for response in (detail, listing):
        assert response.status_code == 200
        _assert_no_ciphertext_in(response.text)
    assert detail.json()["registration"] == REGISTRATION


@pytest.mark.asyncio
async def test_flag_on_create_without_identifiers_stores_no_ciphertext(
    client: AsyncClient, dual_write: Settings
) -> None:
    owner_id, home_id = await _home(client, "p2b-empty")
    vehicle = await _create(client, home_id, _body(owner_id, registration=None, vin=None))
    row = await _row(vehicle["id"])
    assert row.registration is None and row.registration_ciphertext is None
    assert row.vin is None and row.vin_ciphertext is None


# --- 3. Update -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updates_keep_ciphertext_in_step_without_needless_reencryption(
    client: AsyncClient, dual_write: Settings
) -> None:
    owner_id, home_id = await _home(client, "p2b-update")
    vehicle = await _create(client, home_id, _body(owner_id))
    original = await _row(vehicle["id"])
    binding_id = uuid.UUID(vehicle["id"])

    # Unrelated field: neither envelope is replaced (a re-encryption would
    # change it, since every encryption uses a fresh random nonce).
    vehicle = await _update(client, home_id, vehicle, owner_id, nickname="Renamed", colour="Blue")
    row = await _row(vehicle["id"])
    assert row.registration_ciphertext == original.registration_ciphertext
    assert row.vin_ciphertext == original.vin_ciphertext

    # Registration changes: both registration columns change; VIN untouched.
    vehicle = await _update(client, home_id, vehicle, owner_id, registration="AB12 CDE")
    row = await _row(vehicle["id"])
    assert row.registration == "AB12 CDE"
    assert row.registration_ciphertext != original.registration_ciphertext
    assert row.registration_ciphertext is not None
    assert (
        decrypt_sensitive_value(
            row.registration_ciphertext, binding=registration_binding(binding_id), keyring=KEYRING
        )
        == "AB12 CDE"
    )
    assert row.vin_ciphertext == original.vin_ciphertext

    # VIN changes: both VIN columns change.
    vehicle = await _update(client, home_id, vehicle, owner_id, vin="WBA8E1C55JA000002")
    row = await _row(vehicle["id"])
    assert row.vin == "WBA8E1C55JA000002"
    assert row.vin_ciphertext is not None and row.vin_ciphertext != original.vin_ciphertext
    assert (
        decrypt_sensitive_value(
            row.vin_ciphertext, binding=vin_binding(binding_id), keyring=KEYRING
        )
        == "WBA8E1C55JA000002"
    )

    # Clearing either value clears both of its columns.
    vehicle = await _update(client, home_id, vehicle, owner_id, registration=None)
    row = await _row(vehicle["id"])
    assert row.registration is None and row.registration_ciphertext is None
    assert row.vin_ciphertext is not None
    vehicle = await _update(client, home_id, vehicle, owner_id, vin=None)
    row = await _row(vehicle["id"])
    assert row.vin is None and row.vin_ciphertext is None


@pytest.mark.asyncio
async def test_plaintext_change_with_flag_off_never_leaves_stale_ciphertext(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    app.dependency_overrides[get_settings] = lambda: _settings(write=True)
    try:
        owner_id, home_id = await _home(client, "p2b-stale")
        vehicle = await _create(client, home_id, _body(owner_id))
        app.dependency_overrides[get_settings] = lambda: _settings(write=False)
        vehicle = await _update(client, home_id, vehicle, owner_id, registration="ZZ99 ZZZ")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    row = await _row(vehicle["id"])
    # The changed field's old envelope is invalidated, not left describing the
    # previous plaintext; the unchanged VIN keeps its still-valid envelope.
    assert row.registration == "ZZ99 ZZZ" and row.registration_ciphertext is None
    assert row.vin_ciphertext is not None


@pytest.mark.asyncio
async def test_viewer_who_cannot_see_vin_never_touches_vin_ciphertext(
    client: AsyncClient, dual_write: Settings
) -> None:
    """The existing VIN-preservation rule extends to the ciphertext column."""
    from test_driveway_reminders import add_partner

    owner_id, home_id = await _home(client, "p2b-vin-guard")
    vehicle = await _create(client, home_id, _body(owner_id))
    original = await _row(vehicle["id"])
    partner_id = await add_partner(home_id, "p2b-partner")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner:
        from test_driveway_reminders import PASSWORD

        async with SessionFactory() as db:
            from mykhaya.models import User

            email = (await db.get(User, partner_id)).email  # type: ignore[union-attr]
        login = await unsafe(
            partner, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200
        response = await unsafe(
            partner,
            "PATCH",
            f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
            json=_body(
                owner_id, vin=None, expected_updated_at=vehicle["updated_at"], nickname="Shared"
            ),
        )
    # A standard partner has driveway.manage but may not see this vehicle's
    # VIN, so the edit succeeds while the VIN and its ciphertext stay intact.
    assert response.status_code == 200, response.text
    assert response.json().get("vin") is None
    _assert_no_ciphertext_in(response.text)
    row = await _row(vehicle["id"])
    assert row.nickname == "Shared"
    assert row.vin == VIN and row.vin_ciphertext == original.vin_ciphertext
    assert row.registration_ciphertext == original.registration_ciphertext


# --- 4. AAD protection ---------------------------------------------------------


@pytest.mark.asyncio
async def test_ciphertext_is_bound_to_its_vehicle_and_its_field(
    client: AsyncClient, dual_write: Settings
) -> None:
    owner_id, home_id = await _home(client, "p2b-aad")
    first = await _create(client, home_id, _body(owner_id))
    second = await _create(client, home_id, _body(owner_id))
    first_row = await _row(first["id"])
    first_id, second_id = uuid.UUID(first["id"]), uuid.UUID(second["id"])
    assert first_row.registration_ciphertext and first_row.vin_ciphertext

    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(
            first_row.registration_ciphertext,
            binding=registration_binding(second_id),
            keyring=KEYRING,
        )
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(
            first_row.registration_ciphertext, binding=vin_binding(first_id), keyring=KEYRING
        )
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(
            first_row.vin_ciphertext, binding=registration_binding(first_id), keyring=KEYRING
        )
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(
            first_row.vin_ciphertext, binding=vin_binding(second_id), keyring=KEYRING
        )


# --- 5. Key failure ------------------------------------------------------------


@pytest.mark.asyncio
async def test_unavailable_keyring_fails_the_write_without_partial_commit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> StaticKeyring:
        raise KeyUnavailableError("No field-encryption keyring is provisioned.")

    owner_id, home_id = await _home(client, "p2b-nokey")
    # A vehicle created while dual-write is off, to exercise the update path.
    app.dependency_overrides[get_settings] = lambda: _settings(write=False)
    try:
        vehicle = await _create(client, home_id, _body(owner_id))
        monkeypatch.setattr(driveway_sensitive, "get_field_keyring", unavailable)
        app.dependency_overrides[get_settings] = lambda: _settings(write=True)

        async with SessionFactory() as db:
            before = await db.scalar(
                select(func.count()).select_from(Vehicle).where(Vehicle.group_id == home_id)
            )
        created = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/vehicles", json=_body(owner_id)
        )
        assert created.status_code == 503
        assert created.json()["detail"] == (
            "Vehicle details can't be saved right now. Please try again later."
        )
        async with SessionFactory() as db:
            after = await db.scalar(
                select(func.count()).select_from(Vehicle).where(Vehicle.group_id == home_id)
            )
        assert after == before

        updated = await unsafe(
            client,
            "PATCH",
            f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
            json=_body(
                owner_id,
                registration="NEW1 REG",
                nickname="Should not persist",
                expected_updated_at=vehicle["updated_at"],
            ),
        )
        assert updated.status_code == 503
        row = await _row(vehicle["id"])
        # Nothing from the failed request was committed — not even the
        # unrelated nickname change.
        assert row.registration == REGISTRATION and row.nickname == "Family car"
        assert row.registration_ciphertext is None
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_unchanged_identifiers_need_no_keyring_even_with_flag_on(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing other fields never forces an encryption (or a key lookup)."""

    def unavailable() -> StaticKeyring:
        raise KeyUnavailableError("No field-encryption keyring is provisioned.")

    owner_id, home_id = await _home(client, "p2b-nokey-edit")
    app.dependency_overrides[get_settings] = lambda: _settings(write=False)
    try:
        vehicle = await _create(client, home_id, _body(owner_id))
        monkeypatch.setattr(driveway_sensitive, "get_field_keyring", unavailable)
        app.dependency_overrides[get_settings] = lambda: _settings(write=True)
        vehicle = await _update(client, home_id, vehicle, owner_id, nickname="Just a rename")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert vehicle["nickname"] == "Just a rename"


# --- 6/7. Write-path coverage, lookup and Home Migration ---------------------------


def test_every_vehicle_identifier_write_goes_through_the_central_module() -> None:
    """Static guard: outside mykhaya.driveway_sensitive, nothing assigns a
    registration/VIN (or their ciphertext) on a row, and the only Vehicle(...)
    constructions are the router's create and the PCC showcase seeder, both of
    which take their ciphertext from the central helper. A new write path must
    be added through that module."""
    assignment = re.compile(r"\.(registration|vin|registration_ciphertext|vin_ciphertext)\s*=(?!=)")
    offenders: list[str] = []
    constructions: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        relative = path.relative_to(API_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if relative != "driveway_sensitive.py" and assignment.search(source):
            offenders.append(relative)
        if re.search(r"\bVehicle\(", source) and relative != "models.py":
            constructions.append(relative)
    assert offenders == []
    assert sorted(constructions) == ["routers/driveway.py", "showcase/ultimate.py"]
    for writer in constructions:
        source = (API_ROOT / writer).read_text(encoding="utf-8")
        assert "vehicle_sensitive_ciphertexts(" in source
        assert "**ciphertexts" in source


@pytest.mark.asyncio
async def test_vehicle_lookup_never_writes_a_vehicle(
    client: AsyncClient, dual_write: Settings
) -> None:
    """The official lookup only returns suggested details; persisting them
    goes through create (covered above), so lookup cannot bypass dual-write."""
    owner_id, home_id = await _home(client, "p2b-lookup")
    async with SessionFactory() as db:
        before = await db.scalar(select(func.count()).select_from(Vehicle))
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/lookup",
        json={"country_code": "GB", "registration": REGISTRATION},
    )
    assert response.status_code == 200
    async with SessionFactory() as db:
        after = await db.scalar(select(func.count()).select_from(Vehicle))
    assert after == before


def test_home_migration_packages_never_carry_ciphertext() -> None:
    from mykhaya.tools.home_migration import SECRET_COLUMNS, _export_row

    assert {"registration_ciphertext", "vin_ciphertext"} <= SECRET_COLUMNS
    exported = _export_row(
        {
            "id": str(uuid.uuid4()),
            "registration": REGISTRATION,
            "registration_ciphertext": "mkf1.t2b.AAAA",
            "vin_ciphertext": "mkf1.t2b.BBBB",
        }
    )
    assert "registration_ciphertext" not in exported and "vin_ciphertext" not in exported


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [True, False])
async def test_home_migration_import_rederives_ciphertext_for_the_new_row(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, write: bool
) -> None:
    from mykhaya.tools.home_migration import export_home, import_home

    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    app.dependency_overrides[get_settings] = lambda: _settings(write=True)
    try:
        owner_id, home_id = await _home(client, f"p2b-migrate-{str(write).lower()}")
        source = await _create(client, home_id, _body(owner_id))
    finally:
        app.dependency_overrides.pop(get_settings, None)

    source_settings = _settings(write=False).model_copy(update={"environment": "development"})
    package = await export_home(home_id, tmp_path / "package.json", source_settings)
    serialised = json.dumps(package)
    assert "ciphertext" not in serialised and "mkf1." not in serialised

    target = get_settings().model_copy(
        update={"environment": "production", "driveway_field_encryption_write": write}
    )
    report = await import_home(
        package, target, dry_run=False, target_environment="production", confirm=True
    )
    imported_home = uuid.UUID(report["target_home_id"])
    async with SessionFactory() as db:
        row = await db.scalar(select(Vehicle).where(Vehicle.group_id == imported_home))
    assert row is not None and row.id != uuid.UUID(source["id"])
    assert (row.registration, row.vin) == (REGISTRATION, VIN)
    if write:
        assert row.registration_ciphertext and row.vin_ciphertext
        assert (
            decrypt_sensitive_value(
                row.registration_ciphertext, binding=registration_binding(row.id), keyring=KEYRING
            )
            == REGISTRATION
        )
        assert (
            decrypt_sensitive_value(
                row.vin_ciphertext, binding=vin_binding(row.id), keyring=KEYRING
            )
            == VIN
        )
    else:
        assert row.registration_ciphertext is None and row.vin_ciphertext is None


# --- Operator verification tool ------------------------------------------------


@pytest.mark.asyncio
async def test_ciphertext_check_verifies_counts_only_and_detects_moved_ciphertext(
    client: AsyncClient, dual_write: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mykhaya.tools.driveway_ciphertext_check as check

    monkeypatch.setattr(check, "get_field_keyring", lambda: KEYRING)
    owner_id, home_id = await _home(client, "p2b-check")
    first = await _create(client, home_id, _body(owner_id))
    second = await _create(client, home_id, _body(owner_id, registration="CD34 EFG"))

    before = await check.check_vehicle_ciphertexts()
    assert all(isinstance(value, int) for value in before.values())
    assert before["registration_verified"] >= 2 and check.healthy(before)
    rendered = json.dumps(before)
    for secret in (REGISTRATION, "CD34 EFG", VIN, "mkf1.", first["id"], str(home_id)):
        assert secret not in rendered

    # Move the second vehicle's registration envelope onto the first: the AAD
    # row binding must make the checker report it, not silently accept it.
    second_row = await _row(second["id"])
    first_row = await _row(first["id"])
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(first["id"]))
        assert row is not None
        row.registration_ciphertext = second_row.registration_ciphertext
        await db.commit()
    try:
        tampered = await check.check_vehicle_ciphertexts()
        assert tampered["registration_decrypt_failed"] == before["registration_decrypt_failed"] + 1
        assert not check.healthy(tampered)
    finally:
        async with SessionFactory() as db:
            row = await db.get(Vehicle, uuid.UUID(first["id"]))
            assert row is not None
            row.registration_ciphertext = first_row.registration_ciphertext
            await db.commit()
    assert check.healthy(await check.check_vehicle_ciphertexts())


def test_ciphertext_keys_are_redacted_from_logs_and_audit_records() -> None:
    from mykhaya.audit_redaction import redact_audit_metadata
    from mykhaya.platform_audit import safe_values
    from mykhaya.syslog_forwarding import redact

    values = {"registration_ciphertext": "mkf1.t2b.AAAA", "vin_ciphertext": "mkf1.t2b.BBBB"}
    for redacted in (redact(values), redact_audit_metadata(values), safe_values(values)):
        assert "mkf1." not in json.dumps(redacted)
