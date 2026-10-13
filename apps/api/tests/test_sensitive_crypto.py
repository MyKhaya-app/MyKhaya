"""Phase 2A: central sensitive-field cryptography (mykhaya.crypto).

Pure unit tests — no database, Redis or network. Every key here is a
deterministic *test-only* key derived from a fixed label; none of them can be
loaded outside the test/development environments because each keyring
document declares environment "test".
"""

from __future__ import annotations

import base64
import hashlib
import json
import traceback
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs

from mykhaya.config import Settings, get_settings
from mykhaya.crypto import (
    FieldBinding,
    KeyConfigurationError,
    MalformedEnvelopeError,
    SensitiveDataError,
    SensitiveValueDecryptionError,
    StaticKeyring,
    UnknownKeyIdError,
    blind_index,
    blind_index_candidates,
    decrypt_sensitive_value,
    encrypt_sensitive_value,
    envelope_key_id,
    needs_reencryption,
    parse_keyring,
    reencrypt_sensitive_value,
)
from mykhaya.crypto.config import load_sensitive_keyrings, validate_sensitive_key_configuration
from mykhaya.crypto.field import NONCE_BYTES, parse_envelope

PLAINTEXT = "AP22 OOJ"
ROW_ID = uuid.UUID("018f0000-0000-7000-8000-000000000001")
OTHER_ROW_ID = uuid.UUID("018f0000-0000-7000-8000-000000000002")
BINDING = FieldBinding(
    purpose="vehicle.registration", column="vehicles.registration_ciphertext", row_id=ROW_ID
)


def _test_key(label: str) -> bytes:
    return hashlib.sha256(f"mykhaya-test-only-key:{label}".encode()).digest()


def _b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


def _field_keyring(active: str = "t1", *key_ids: str, environment: str = "test") -> StaticKeyring:
    ids = key_ids or (active,)
    return StaticKeyring(
        purpose="field-encryption",
        environment=environment,  # type: ignore[arg-type]
        active=active,
        keys={key_id: _test_key(f"field:{key_id}") for key_id in ids},
    )


def _blind_keyring(active: str = "b1", *key_ids: str) -> StaticKeyring:
    ids = key_ids or (active,)
    return StaticKeyring(
        purpose="blind-index",
        environment="test",
        active=active,
        keys={key_id: _test_key(f"blind:{key_id}") for key_id in ids},
    )


def _document(purpose: str, keys: dict[str, bytes], active: str, environment: str = "test") -> str:
    return json.dumps(
        {
            "format": "mykhaya-keyring-v1",
            "purpose": purpose,
            "environment": environment,
            "active": active,
            "keys": {key_id: _b64(key) for key_id, key in keys.items()},
        }
    )


FIELD_DOC = _document("field-encryption", {"t1": _test_key("field:t1")}, "t1")
BLIND_DOC = _document("blind-index", {"b1": _test_key("blind:b1")}, "b1")


# --- Round trip, nonces, envelope ------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    assert decrypt_sensitive_value(envelope, binding=BINDING, keyring=keyring) == PLAINTEXT


@pytest.mark.parametrize("value", ["", "ü-ñ 日本 🚗", "x" * 5000])
def test_round_trip_handles_empty_unicode_and_long_values(value: str) -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(value, binding=BINDING, keyring=keyring)
    assert decrypt_sensitive_value(envelope, binding=BINDING, keyring=keyring) == value


def test_envelope_format_carries_version_and_key_id_but_not_plaintext() -> None:
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=_field_keyring())
    version, key_id, body = envelope.split(".")
    assert (version, key_id) == ("mkf1", "t1")
    assert PLAINTEXT not in envelope
    assert PLAINTEXT.replace(" ", "") not in envelope
    assert "=" not in body


def test_each_encryption_uses_a_fresh_random_nonce() -> None:
    keyring = _field_keyring()
    envelopes = {
        encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring) for _ in range(50)
    }
    assert len(envelopes) == 50
    nonces = {parse_envelope(envelope).payload[:NONCE_BYTES] for envelope in envelopes}
    assert len(nonces) == 50


# --- Tamper detection and AAD binding ----------------------------------------


def test_ciphertext_tampering_is_detected() -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    payload = bytearray(parse_envelope(envelope).payload)
    for index in (0, NONCE_BYTES, len(payload) - 1):  # nonce, ciphertext, tag
        tampered = bytearray(payload)
        tampered[index] ^= 0x01
        body = base64.urlsafe_b64encode(bytes(tampered)).rstrip(b"=").decode()
        with pytest.raises(SensitiveValueDecryptionError):
            decrypt_sensitive_value(f"mkf1.t1.{body}", binding=BINDING, keyring=keyring)


def test_ciphertext_is_bound_to_its_row() -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    moved = FieldBinding(purpose=BINDING.purpose, column=BINDING.column, row_id=OTHER_ROW_ID)
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(envelope, binding=moved, keyring=keyring)


def test_ciphertext_is_bound_to_its_column() -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    other_column = FieldBinding(
        purpose=BINDING.purpose, column="vehicles.vin_ciphertext", row_id=ROW_ID
    )
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(envelope, binding=other_column, keyring=keyring)


def test_ciphertext_is_bound_to_its_purpose() -> None:
    keyring = _field_keyring()
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    other_purpose = FieldBinding(purpose="vehicle.vin", column=BINDING.column, row_id=ROW_ID)
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(envelope, binding=other_purpose, keyring=keyring)


def test_editing_the_key_id_in_the_header_is_detected() -> None:
    # Both keys are present, so the swap reaches AES-GCM: the key ID is part
    # of the AAD and the wrong key is used, so authentication must fail.
    keyring = _field_keyring("t1", "t1", "t2")
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    swapped = envelope.replace("mkf1.t1.", "mkf1.t2.", 1)
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(swapped, binding=BINDING, keyring=keyring)


@pytest.mark.parametrize(
    ("purpose", "column"),
    [
        ("Vehicle.Registration", "vehicles.registration"),
        ("vehicle registration", "vehicles.registration"),
        ("vehicle.registration", ""),
        ("", "vehicles.registration"),
        ("vehicle.registration", "vehicles.registration\x00x"),
    ],
)
def test_binding_labels_are_restricted_identifiers(purpose: str, column: str) -> None:
    with pytest.raises(ValueError):
        FieldBinding(purpose=purpose, column=column, row_id=ROW_ID)


# --- Keys: wrong key, unknown ID, active selection, rotation ------------------


def test_wrong_key_fails_authentication() -> None:
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=_field_keyring())
    impostor = StaticKeyring(
        purpose="field-encryption", environment="test", active="t1", keys={"t1": _test_key("x")}
    )
    with pytest.raises(SensitiveValueDecryptionError):
        decrypt_sensitive_value(envelope, binding=BINDING, keyring=impostor)


def test_unknown_key_id_is_reported_by_id_only() -> None:
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=_field_keyring("t1"))
    with pytest.raises(UnknownKeyIdError) as raised:
        decrypt_sensitive_value(envelope, binding=BINDING, keyring=_field_keyring("t9"))
    assert raised.value.key_id == "t1"


def test_new_writes_use_the_active_key() -> None:
    keyring = _field_keyring("t2", "t1", "t2")
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    assert envelope_key_id(envelope) == "t2"


def test_old_key_versions_remain_readable_after_rotation() -> None:
    before = _field_keyring("t1", "t1")
    old_envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=before)
    after = _field_keyring("t2", "t1", "t2")
    assert decrypt_sensitive_value(old_envelope, binding=BINDING, keyring=after) == PLAINTEXT


def test_reencryption_moves_a_value_to_the_active_key() -> None:
    old_envelope = encrypt_sensitive_value(
        PLAINTEXT, binding=BINDING, keyring=_field_keyring("t1", "t1")
    )
    rotated = _field_keyring("t2", "t1", "t2")
    assert needs_reencryption(old_envelope, keyring=rotated)

    new_envelope = reencrypt_sensitive_value(old_envelope, binding=BINDING, keyring=rotated)
    assert envelope_key_id(new_envelope) == "t2"
    assert not needs_reencryption(new_envelope, keyring=rotated)
    # Idempotent: a resumed rotation pass leaves an already-current value alone.
    assert reencrypt_sensitive_value(new_envelope, binding=BINDING, keyring=rotated) == new_envelope

    retired = _field_keyring("t2", "t2")
    assert decrypt_sensitive_value(new_envelope, binding=BINDING, keyring=retired) == PLAINTEXT
    with pytest.raises(UnknownKeyIdError):
        decrypt_sensitive_value(old_envelope, binding=BINDING, keyring=retired)


def test_reencryption_refuses_a_tampered_value() -> None:
    keyring = _field_keyring("t2", "t1", "t2")
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=_field_keyring("t1"))
    moved = FieldBinding(purpose=BINDING.purpose, column=BINDING.column, row_id=OTHER_ROW_ID)
    with pytest.raises(SensitiveValueDecryptionError):
        reencrypt_sensitive_value(envelope, binding=moved, keyring=keyring)


def test_field_and_blind_index_keyrings_are_not_interchangeable() -> None:
    with pytest.raises(KeyConfigurationError):
        encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=_blind_keyring())
    with pytest.raises(KeyConfigurationError):
        blind_index("AP22OOJ", purpose="vehicle.registration", scope="h", keyring=_field_keyring())


# --- Malformed envelopes -------------------------------------------------------


@pytest.mark.parametrize(
    "envelope",
    [
        "",
        "AP22 OOJ",
        "mkf1",
        "mkf1.t1",
        "mkf1.t1.",
        "mkf2.t1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "mkf1.T1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "mkf1.t1.AAAA",  # shorter than nonce + tag
        "mkf1.t1.!!!!notbase64!!!!",
        "mkf1.t1.AAAA.extra",
        "mkf1..AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ],
)
def test_malformed_envelopes_are_rejected(envelope: str) -> None:
    with pytest.raises(MalformedEnvelopeError):
        decrypt_sensitive_value(envelope, binding=BINDING, keyring=_field_keyring())


def test_non_string_envelope_is_rejected() -> None:
    with pytest.raises(MalformedEnvelopeError):
        decrypt_sensitive_value(b"mkf1.t1.AAAA", binding=BINDING, keyring=_field_keyring())  # type: ignore[arg-type]


# --- No plaintext / key leakage ------------------------------------------------


def _leak_markers(keyring: StaticKeyring) -> list[str]:
    markers = [PLAINTEXT, PLAINTEXT.replace(" ", "")]
    for key_id in keyring.key_ids():
        key = keyring.get_key(key_id)
        markers += [_b64(key), key.hex(), base64.urlsafe_b64encode(key).decode().rstrip("=")]
    return markers


def test_failures_never_expose_plaintext_ciphertext_or_key_material() -> None:
    keyring = _field_keyring("t2", "t1", "t2")
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=keyring)
    moved = FieldBinding(purpose=BINDING.purpose, column=BINDING.column, row_id=OTHER_ROW_ID)
    failures: list[SensitiveDataError] = []
    for attempt in (
        lambda: decrypt_sensitive_value(envelope, binding=moved, keyring=keyring),
        lambda: decrypt_sensitive_value(envelope, binding=BINDING, keyring=_field_keyring("t9")),
        lambda: decrypt_sensitive_value(envelope[:-4], binding=BINDING, keyring=keyring),
        lambda: decrypt_sensitive_value("mkf1.t1.%%%", binding=BINDING, keyring=keyring),
    ):
        with pytest.raises(SensitiveDataError) as raised:
            attempt()
        failures.append(raised.value)
    body = envelope.split(".")[2]
    for failure in failures:
        rendered = "".join(traceback.format_exception(failure)) + repr(failure) + str(failure)
        assert failure.__cause__ is None
        assert failure.__suppress_context__ or failure.__context__ is None
        assert body not in rendered
        for marker in _leak_markers(keyring):
            assert marker not in rendered


def test_keyring_repr_never_renders_key_bytes() -> None:
    keyring = _field_keyring("t2", "t1", "t2")
    rendered = repr(keyring) + str(keyring) + repr(keyring._keys)  # noqa: SLF001
    for marker in _leak_markers(keyring)[2:]:
        assert marker not in rendered
    assert "t1" in rendered and "t2" in rendered


def test_keyring_parse_errors_do_not_echo_the_document() -> None:
    secret_text = _b64(_test_key("leak-probe"))
    bad_documents = [
        f'{{"format": "mykhaya-keyring-v1", {secret_text}',
        _document("field-encryption", {"t1": b"short"}, "t1").replace(
            _b64(b"short"), secret_text[:10]
        ),
        json.dumps(
            {
                "format": "mykhaya-keyring-v1",
                "purpose": "field-encryption",
                "environment": "test",
                "active": "t1",
                "keys": {"t1": secret_text + "!!"},
            }
        ),
    ]
    for document in bad_documents:
        with pytest.raises(KeyConfigurationError) as raised:
            parse_keyring(document, expected_purpose="field-encryption")
        rendered = "".join(traceback.format_exception(raised.value))
        assert secret_text not in rendered
        assert secret_text[:10] not in rendered


def test_startup_validation_logs_sources_and_key_ids_only(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path, field_encryption_keys=SecretStr(FIELD_DOC), blind_index_keys=SecretStr(BLIND_DOC)
    )
    with capture_logs() as logs:
        status = validate_sensitive_key_configuration(settings, service="api")
    assert status.provisioned
    assert (status.field_active_key_id, status.blind_index_active_key_id) == ("t1", "b1")
    rendered = json.dumps(logs, default=str)
    assert "sensitive_field_keys_loaded" in rendered
    for key in (_test_key("field:t1"), _test_key("blind:b1")):
        assert _b64(key) not in rendered
        assert key.hex() not in rendered


# --- Keyring document validation -------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda doc: {**doc, "format": "other"}, "format"),
        (lambda doc: {**doc, "purpose": "blind-index"}, "purpose"),
        (lambda doc: {**doc, "environment": "staging"}, "environment"),
        (lambda doc: {**doc, "active": "missing"}, "active key"),
        (lambda doc: {**doc, "keys": {}}, "at least one key"),
        (lambda doc: {**doc, "keys": {"BAD.ID": doc["keys"]["t1"]}}, "Key IDs"),
        (lambda doc: {**doc, "keys": {"t1": _b64(b"\x00" * 31)}}, "32 bytes"),
        (lambda doc: {**doc, "keys": {"t1": _b64(b"\x00" * 32)}}, "not random"),
        (
            lambda doc: {**doc, "keys": {"t1": doc["keys"]["t1"], "t2": doc["keys"]["t1"]}},
            "same key bytes",
        ),
    ],
)
def test_invalid_keyring_documents_fail_closed(mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    document = json.dumps(mutate(json.loads(FIELD_DOC)))
    with pytest.raises(KeyConfigurationError, match=message):
        parse_keyring(document, expected_purpose="field-encryption")


# --- Blind index ---------------------------------------------------------------


def test_blind_index_is_deterministic_keyed_and_versioned() -> None:
    keyring = _blind_keyring()
    first = blind_index("AP22OOJ", purpose="vehicle.registration", scope="home-1", keyring=keyring)
    second = blind_index("AP22OOJ", purpose="vehicle.registration", scope="home-1", keyring=keyring)
    assert first == second
    key_id, digest = first.split(".")
    assert key_id == "b1" and len(digest) == 64
    assert digest != hashlib.sha256(b"AP22OOJ").hexdigest()
    other_key = StaticKeyring(
        purpose="blind-index", environment="test", active="b1", keys={"b1": _test_key("other")}
    )
    assert first != blind_index(
        "AP22OOJ", purpose="vehicle.registration", scope="home-1", keyring=other_key
    )


def test_blind_index_separates_scope_and_purpose() -> None:
    keyring = _blind_keyring()
    base = blind_index("AP22OOJ", purpose="vehicle.registration", scope="home-1", keyring=keyring)
    assert base != blind_index(
        "AP22OOJ", purpose="vehicle.registration", scope="home-2", keyring=keyring
    )
    assert base != blind_index("AP22OOJ", purpose="vehicle.vin", scope="home-1", keyring=keyring)


def test_blind_index_candidates_cover_every_key_during_rotation() -> None:
    old = blind_index(
        "AP22OOJ", purpose="vehicle.registration", scope="h", keyring=_blind_keyring()
    )
    rotated = _blind_keyring("b2", "b1", "b2")
    candidates = blind_index_candidates(
        "AP22OOJ", purpose="vehicle.registration", scope="h", keyring=rotated
    )
    assert old in candidates
    assert blind_index("AP22OOJ", purpose="vehicle.registration", scope="h", keyring=rotated) in (
        candidates
    )


def test_blind_index_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        blind_index("", purpose="vehicle.registration", scope="h", keyring=_blind_keyring())


# --- Key loading and startup validation ------------------------------------------


def _settings(tmp_path: Path, **update: object) -> Settings:
    values: dict[str, object] = {
        "field_encryption_keys_file": str(tmp_path / "absent-field.json"),
        "blind_index_keys_file": str(tmp_path / "absent-blind.json"),
        "field_encryption_keys": None,
        "blind_index_keys": None,
        "sensitive_field_keys_required": False,
    }
    values.update(update)
    return get_settings().model_copy(update=values)


def test_unprovisioned_keyrings_are_allowed_in_phase_2a(tmp_path: Path) -> None:
    field, blind, status = load_sensitive_keyrings(_settings(tmp_path))
    assert field is None and blind is None and not status.provisioned


def test_required_flag_makes_missing_keyrings_fatal(tmp_path: Path) -> None:
    with pytest.raises(KeyConfigurationError, match="required"):
        load_sensitive_keyrings(_settings(tmp_path, sensitive_field_keys_required=True))


def test_keyrings_load_from_files(tmp_path: Path) -> None:
    (tmp_path / "field.json").write_text(FIELD_DOC, encoding="utf-8")
    (tmp_path / "blind.json").write_text(BLIND_DOC, encoding="utf-8")
    field, blind, status = load_sensitive_keyrings(
        _settings(
            tmp_path,
            field_encryption_keys_file=str(tmp_path / "field.json"),
            blind_index_keys_file=str(tmp_path / "blind.json"),
        )
    )
    assert field is not None and blind is not None
    assert (status.field_source, status.blind_index_source) == ("file", "file")


def test_keyrings_load_from_environment_outside_production(tmp_path: Path) -> None:
    _, _, status = load_sensitive_keyrings(
        _settings(
            tmp_path,
            field_encryption_keys=SecretStr(FIELD_DOC),
            blind_index_keys=SecretStr(BLIND_DOC),
        )
    )
    assert (status.field_source, status.blind_index_source) == ("environment", "environment")


def test_file_and_environment_together_is_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "field.json").write_text(FIELD_DOC, encoding="utf-8")
    with pytest.raises(KeyConfigurationError, match="exactly one"):
        load_sensitive_keyrings(
            _settings(
                tmp_path,
                field_encryption_keys_file=str(tmp_path / "field.json"),
                field_encryption_keys=SecretStr(FIELD_DOC),
                blind_index_keys=SecretStr(BLIND_DOC),
            )
        )


def test_keyrings_must_be_provisioned_together(tmp_path: Path) -> None:
    with pytest.raises(KeyConfigurationError, match="together"):
        load_sensitive_keyrings(_settings(tmp_path, field_encryption_keys=SecretStr(FIELD_DOC)))


def test_field_and_blind_keyrings_must_not_share_key_material(tmp_path: Path) -> None:
    shared = _document("blind-index", {"b1": _test_key("field:t1")}, "b1")
    with pytest.raises(KeyConfigurationError, match="share"):
        load_sensitive_keyrings(
            _settings(
                tmp_path,
                field_encryption_keys=SecretStr(FIELD_DOC),
                blind_index_keys=SecretStr(shared),
            )
        )


def test_production_keyrings_are_refused_outside_production(tmp_path: Path) -> None:
    production_doc = _document("field-encryption", {"p1": _test_key("p1")}, "p1", "production")
    with pytest.raises(KeyConfigurationError, match="outside production"):
        load_sensitive_keyrings(
            _settings(
                tmp_path,
                field_encryption_keys=SecretStr(production_doc),
                blind_index_keys=SecretStr(BLIND_DOC),
            )
        )


def test_production_refuses_non_production_keyrings(tmp_path: Path) -> None:
    (tmp_path / "field.json").write_text(FIELD_DOC, encoding="utf-8")
    (tmp_path / "blind.json").write_text(BLIND_DOC, encoding="utf-8")
    with pytest.raises(KeyConfigurationError, match="Production refuses"):
        load_sensitive_keyrings(
            _settings(
                tmp_path,
                environment="production",
                field_encryption_keys_file=str(tmp_path / "field.json"),
                blind_index_keys_file=str(tmp_path / "blind.json"),
            )
        )


def test_production_settings_reject_environment_supplied_keys(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MYKHAYA_ENVIRONMENT", "production")
    # Satisfy the unrelated production cookie rule so the keyring rule is the
    # one under test (the test container pins cookie_secure=false).
    monkeypatch.setenv("MYKHAYA_COOKIE_SECURE", "true")
    monkeypatch.setenv("MYKHAYA_FIELD_ENCRYPTION_KEYS", FIELD_DOC)
    with pytest.raises(ValidationError, match="development/test fallback"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_blank_key_variables_mean_unset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MYKHAYA_FIELD_ENCRYPTION_KEYS", "")
    monkeypatch.setenv("MYKHAYA_BLIND_INDEX_KEYS", "  ")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.field_encryption_keys is None
    assert settings.blind_index_keys is None


def test_crypto_package_is_independent_of_the_session_secret(tmp_path: Path) -> None:
    """Rotating MYKHAYA_SECRET_KEY must not change what the field keyring
    decrypts — the keyring never derives from it."""
    keyring_settings = _settings(
        tmp_path, field_encryption_keys=SecretStr(FIELD_DOC), blind_index_keys=SecretStr(BLIND_DOC)
    )
    field, _, _ = load_sensitive_keyrings(keyring_settings)
    assert field is not None
    envelope = encrypt_sensitive_value(PLAINTEXT, binding=BINDING, keyring=field)
    rotated = keyring_settings.model_copy(
        update={"secret_key": SecretStr("a-completely-different-session-secret-0123456789")}
    )
    rotated_field, _, _ = load_sensitive_keyrings(rotated)
    assert rotated_field is not None
    assert decrypt_sensitive_value(envelope, binding=BINDING, keyring=rotated_field) == PLAINTEXT


# --- Keyring generator / rotation CLI ------------------------------------------


def test_generated_keyrings_are_valid_random_and_environment_labelled() -> None:
    from mykhaya.crypto.generate_keyring import new_keyring_document

    first = new_keyring_document(purpose="field-encryption", environment="test", key_id="g1")
    second = new_keyring_document(purpose="field-encryption", environment="test", key_id="g1")
    keyring = parse_keyring(first, expected_purpose="field-encryption")
    assert keyring.environment == "test" and keyring.active_key_id() == "g1"
    assert json.loads(first)["keys"]["g1"] != json.loads(second)["keys"]["g1"]


def test_rotation_keeps_old_keys_and_activates_the_new_one() -> None:
    from mykhaya.crypto.generate_keyring import rotated_keyring_document

    rotated_doc = rotated_keyring_document(FIELD_DOC, key_id="t2")
    rotated = parse_keyring(rotated_doc, expected_purpose="field-encryption")
    assert rotated.key_ids() == ("t1", "t2") and rotated.active_key_id() == "t2"
    old_envelope = encrypt_sensitive_value(
        PLAINTEXT,
        binding=BINDING,
        keyring=parse_keyring(FIELD_DOC, expected_purpose="field-encryption"),
    )
    assert decrypt_sensitive_value(old_envelope, binding=BINDING, keyring=rotated) == PLAINTEXT
    with pytest.raises(KeyConfigurationError, match="already exists"):
        rotated_keyring_document(rotated_doc, key_id="t1")


def test_generator_cli_writes_only_the_document_to_stdout(capsys) -> None:  # type: ignore[no-untyped-def]
    from mykhaya.crypto.generate_keyring import main

    assert main(["--purpose", "blind-index", "--environment", "test", "--key-id", "c1"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    parse_keyring(captured.out, expected_purpose="blind-index")
    assert main(["--key-id", "BAD.ID", "--purpose", "blind-index", "--environment", "test"]) == 2


def test_fingerprint_identifies_key_material_without_revealing_it(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from mykhaya.crypto.generate_keyring import keyring_fingerprint, main

    original = keyring_fingerprint(FIELD_DOC)
    # Byte-different but cryptographically identical copy (whitespace, key order).
    reformatted = json.dumps(json.loads(FIELD_DOC), indent=4, sort_keys=True)
    assert keyring_fingerprint(reformatted) == original
    assert original["active"] == "t1" and original["environment"] == "test"
    different = _document("field-encryption", {"t1": _test_key("not-the-same")}, "t1")
    assert keyring_fingerprint(different) != original

    path = tmp_path / "field.json"
    path.write_text(FIELD_DOC, encoding="utf-8")
    assert main(["--fingerprint", str(path)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == original
    key = _test_key("field:t1")
    for marker in (_b64(key), key.hex(), base64.urlsafe_b64encode(key).decode().rstrip("=")):
        assert marker not in printed
