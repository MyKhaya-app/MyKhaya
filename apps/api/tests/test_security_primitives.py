import uuid

from mykhaya.ids import uuid7
from mykhaya.security import decode_derived_token, derived_token, hash_secret, normalise_email


def test_uuid7_has_correct_version_and_sortable_timestamp() -> None:
    first = uuid7()
    second = uuid7()
    assert first.version == 7
    assert first.variant == uuid.RFC_4122
    assert first.int < second.int


def test_derived_tokens_are_purpose_bound_and_tamper_evident() -> None:
    identifier = uuid7()
    token = derived_token(identifier, "verify_email", "a" * 32)
    assert decode_derived_token(token, "verify_email", "a" * 32) == identifier
    assert decode_derived_token(token, "reset_password", "a" * 32) is None
    assert decode_derived_token(token[:-1] + "A", "verify_email", "a" * 32) is None
    assert token not in hash_secret(token, "a" * 32)


def test_email_normalisation_is_predictable() -> None:
    assert normalise_email("  Person@Example.COM ") == "person@example.com"
