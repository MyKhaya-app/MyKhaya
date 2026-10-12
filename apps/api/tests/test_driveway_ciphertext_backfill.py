"""Sensitive Data Protection Phase 2C: operator-run Driveway ciphertext backfill.

Vehicles are created through the real API with dual-write off (plaintext
only), then the backfill tool is run against the isolated test database. The
test database also holds other modules' vehicles, so assertions are made on
this module's own rows; global counts are only compared as deltas or
zero/non-zero properties. Keys are deterministic test-only keyrings.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from structlog.testing import capture_logs
from test_driveway_field_encryption import KEYRING, _body, _home
from test_driveway_reminders import ORIGIN, unsafe

import mykhaya.driveway_sensitive as driveway_sensitive
import mykhaya.tools.driveway_ciphertext_backfill as backfill
from mykhaya.config import Settings, get_settings
from mykhaya.crypto import KeyUnavailableError, StaticKeyring, decrypt_sensitive_value
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import registration_binding, vin_binding
from mykhaya.main import app
from mykhaya.models import Vehicle

# Stored exactly as typed (the API only trims the ends): the backfill must
# encrypt this byte-for-byte, with no upper-casing or space collapsing.
ODD_REGISTRATION = "ab12  cDe"
VIN = "WBA8E1C55JA000009"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _settings(*, write: bool) -> Settings:
    return get_settings().model_copy(update={"driveway_field_encryption_write": write})


@pytest.fixture
def keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[StaticKeyring]:
    monkeypatch.setattr(backfill, "get_field_keyring", lambda: KEYRING)
    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    yield KEYRING


async def _create(client: AsyncClient, home_id: uuid.UUID, body: dict[str, object]) -> str:
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/vehicles", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _plaintext_vehicles(client: AsyncClient, prefix: str) -> tuple[uuid.UUID, dict[str, str]]:
    """A Home with three plaintext-only vehicles: registration+VIN,
    registration only, and neither."""
    app.dependency_overrides[get_settings] = lambda: _settings(write=False)
    try:
        owner_id, home_id = await _home(client, prefix)
        ids = {
            "both": await _create(
                client, home_id, _body(owner_id, registration=ODD_REGISTRATION, vin=VIN)
            ),
            "registration_only": await _create(
                client, home_id, _body(owner_id, registration="ZX98 YWV", vin=None)
            ),
            "neither": await _create(client, home_id, _body(owner_id, registration=None, vin=None)),
        }
    finally:
        app.dependency_overrides.pop(get_settings, None)
    return home_id, ids


async def _snapshot(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Every column of the given rows, for byte-for-byte comparisons."""
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(Vehicle).where(Vehicle.id.in_([uuid.UUID(i) for i in ids])))
        ).all()
        return {
            str(row.id): {column.key: getattr(row, column.key) for column in Vehicle.__table__.c}
            for row in rows
        }


# --- 1. Dry-run --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_identifies_missing_ciphertext_and_writes_nothing(
    client: AsyncClient, keyring: StaticKeyring
) -> None:
    _, ids = await _plaintext_vehicles(client, "p2c-dry")
    before = await _snapshot(list(ids.values()))
    code, report = await backfill.run_backfill(apply=False, settings=_settings(write=True))
    assert code == backfill.EXIT_OK
    assert report["mode"] == "dry-run"
    assert report["registration_needs_backfill"] >= 2 and report["vin_needs_backfill"] >= 1
    assert report["registration_backfilled"] == 0 and report["vin_backfilled"] == 0
    assert (
        report["registration_plaintext"]
        == report["registration_already_encrypted"] + report["registration_needs_backfill"]
    )
    assert report["vin_plaintext"] == report["vin_already_encrypted"] + report["vin_needs_backfill"]
    assert await _snapshot(list(ids.values())) == before


# --- 2/3/5/9. Apply: fills, exact plaintext, nulls, integrity ------------------------


@pytest.mark.asyncio
async def test_apply_fills_missing_ciphertext_from_exact_plaintext_only(
    client: AsyncClient, keyring: StaticKeyring
) -> None:
    _, ids = await _plaintext_vehicles(client, "p2c-apply")
    before = await _snapshot(list(ids.values()))
    code, report = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert code == backfill.EXIT_OK, report
    assert report["registration_backfilled"] >= 2 and report["vin_backfilled"] >= 1
    after = await _snapshot(list(ids.values()))

    both = after[ids["both"]]
    both_id = uuid.UUID(ids["both"])
    assert both["registration"] == ODD_REGISTRATION and both["vin"] == VIN
    assert both["registration_ciphertext"].startswith("mkf1.t2b.")
    assert (
        decrypt_sensitive_value(
            both["registration_ciphertext"], binding=registration_binding(both_id), keyring=KEYRING
        )
        == ODD_REGISTRATION
    )
    assert (
        decrypt_sensitive_value(
            both["vin_ciphertext"], binding=vin_binding(both_id), keyring=KEYRING
        )
        == VIN
    )

    registration_only = after[ids["registration_only"]]
    assert registration_only["registration_ciphertext"] is not None
    assert registration_only["vin"] is None and registration_only["vin_ciphertext"] is None

    neither = after[ids["neither"]]
    assert neither["registration_ciphertext"] is None and neither["vin_ciphertext"] is None

    # Plaintext integrity: every column except the two ciphertext columns is
    # byte-for-byte unchanged — including updated_at (no optimistic-lock churn).
    for vehicle_id, row in after.items():
        for key, value in row.items():
            if key in {"registration_ciphertext", "vin_ciphertext"}:
                continue
            assert value == before[vehicle_id][key], (vehicle_id, key)


# --- 4/6. Existing ciphertext and idempotency -----------------------------------------


@pytest.mark.asyncio
async def test_existing_ciphertext_is_untouched_and_reapply_is_a_no_op(
    client: AsyncClient, keyring: StaticKeyring
) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings(write=True)
    try:
        owner_id, home_id = await _home(client, "p2c-existing")
        encrypted_id = await _create(client, home_id, _body(owner_id, vin=VIN))
    finally:
        app.dependency_overrides.pop(get_settings, None)
    _, ids = await _plaintext_vehicles(client, "p2c-idem")
    all_ids = [encrypted_id, *ids.values()]
    original = await _snapshot([encrypted_id])

    code, _ = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert code == backfill.EXIT_OK
    first = await _snapshot(all_ids)
    assert first[encrypted_id] == original[encrypted_id]

    code, report = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert code == backfill.EXIT_OK
    assert report["registration_backfilled"] == 0 and report["vin_backfilled"] == 0
    assert report["registration_needs_backfill"] == 0 and report["vin_needs_backfill"] == 0
    assert await _snapshot(all_ids) == first


# --- 7/8. Refusals --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_false_allows_dry_run_but_refuses_apply(
    client: AsyncClient, keyring: StaticKeyring
) -> None:
    _, ids = await _plaintext_vehicles(client, "p2c-flag")
    before = await _snapshot(list(ids.values()))
    code, report = await backfill.run_backfill(apply=False, settings=_settings(write=False))
    assert code == backfill.EXIT_OK and report["registration_needs_backfill"] >= 2
    code, report = await backfill.run_backfill(apply=True, settings=_settings(write=False))
    assert code == backfill.EXIT_REFUSED
    assert report["refused"] == "driveway_field_encryption_write_disabled"
    assert await _snapshot(list(ids.values())) == before


@pytest.mark.asyncio
async def test_missing_keyring_refuses_before_modifying_any_row(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, ids = await _plaintext_vehicles(client, "p2c-nokey")
    before = await _snapshot(list(ids.values()))

    def unavailable() -> StaticKeyring:
        raise KeyUnavailableError("No field-encryption keyring is provisioned.")

    monkeypatch.setattr(backfill, "get_field_keyring", unavailable)
    code, report = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert code == backfill.EXIT_REFUSED
    assert report["refused"] == "field_encryption_keyring_unavailable"
    assert await _snapshot(list(ids.values())) == before


@pytest.mark.asyncio
async def test_failure_part_way_through_rolls_back_every_write(
    client: AsyncClient, keyring: StaticKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, ids = await _plaintext_vehicles(client, "p2c-rollback")
    before = await _snapshot(list(ids.values()))
    real_encrypt = backfill.encrypt_sensitive_value
    calls = {"n": 0}

    def fail_on_second_call(*args: Any, **kwargs: Any) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure mid-backfill")
        return real_encrypt(*args, **kwargs)

    monkeypatch.setattr(backfill, "encrypt_sensitive_value", fail_on_second_call)
    code, report = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert code == backfill.EXIT_FAILED
    assert report["failed"] == "RuntimeError"
    assert report["registration_backfilled"] == 0 and report["vin_backfilled"] == 0
    # The first (successful) UPDATE was rolled back with the rest.
    assert await _snapshot(list(ids.values())) == before


# --- 10. Output safety -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_and_logs_contain_counts_only(
    client: AsyncClient, keyring: StaticKeyring
) -> None:
    home_id, ids = await _plaintext_vehicles(client, "p2c-output")
    with capture_logs() as logs:
        dry_code, dry = await backfill.run_backfill(apply=False, settings=_settings(write=True))
        code, applied = await backfill.run_backfill(apply=True, settings=_settings(write=True))
    assert dry_code == code == backfill.EXIT_OK
    after = await _snapshot(list(ids.values()))
    forbidden = [ODD_REGISTRATION, "ZX98 YWV", VIN, str(home_id), *ids.values(), "mkf1."]
    forbidden += [
        value
        for row in after.values()
        for value in (row["registration_ciphertext"], row["vin_ciphertext"])
        if value
    ]
    for rendered in (json.dumps(dry), json.dumps(applied), json.dumps(logs, default=str)):
        for secret in forbidden:
            assert secret not in rendered
    for report in (dry, applied):
        assert set(report) == set(backfill._empty_report("x"))
        assert all(isinstance(value, int) for key, value in report.items() if key != "mode")


def test_cli_defaults_to_dry_run_and_prints_counts_only(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_be_called() -> StaticKeyring:
        raise AssertionError("dry-run must not need the keyring")

    monkeypatch.setattr(backfill, "get_field_keyring", must_not_be_called)
    assert backfill.main([]) == backfill.EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run" and report["registration_backfilled"] == 0
    assert all(isinstance(value, int) for key, value in report.items() if key != "mode")


def test_backfill_is_never_wired_into_automatic_execution() -> None:
    """Operator-only: nothing imports or invokes the tool outside itself."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    references = [
        path.relative_to(root).as_posix()
        for base in ("mykhaya", "migrations")
        for path in (root / base).rglob("*.py")
        if "driveway_ciphertext_backfill" in path.read_text(encoding="utf-8")
        and path.name != "driveway_ciphertext_backfill.py"
    ]
    # Deployment scripts and Compose files are checked by
    # infrastructure/tests/test_sensitive_data_infrastructure.py (host-side,
    # where the repository root exists).
    assert references == []


def test_backfill_reuses_the_shared_bindings_and_encryption() -> None:
    """The backfill is the one sanctioned ciphertext writer besides
    mykhaya.driveway_sensitive; it must use the very same bindings and the
    central encryption function, not copies."""
    import mykhaya.crypto as crypto

    assert backfill.registration_binding is driveway_sensitive.registration_binding
    assert backfill.vin_binding is driveway_sensitive.vin_binding
    assert backfill.encrypt_sensitive_value is crypto.encrypt_sensitive_value
