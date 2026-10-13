"""Generate or rotate a sensitive-field keyring document.

Writes the JSON document to stdout only — never to a log, never to the
database. The operator redirects it straight into the protected key file
(see docs/operations/sensitive-field-keys.md)::

    # new keyring
    python -m mykhaya.crypto.generate_keyring --purpose field-encryption \\
        --environment production --key-id k2026a > field-encryption-keys.json

    # rotation: keep every existing key, add a new one and make it active
    python -m mykhaya.crypto.generate_keyring --rotate field-encryption-keys.json \\
        --key-id k2027a > field-encryption-keys.next.json

Key bytes come from ``os.urandom`` (the OS CSPRNG). The output is validated
by the same parser the application uses before it is printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from mykhaya.crypto.errors import KeyConfigurationError
from mykhaya.crypto.keyring import KEY_BYTES, KEYRING_FORMAT, parse_keyring


def new_keyring_document(*, purpose: str, environment: str, key_id: str) -> str:
    document = {
        "format": KEYRING_FORMAT,
        "purpose": purpose,
        "environment": environment,
        "active": key_id,
        "keys": {key_id: base64.b64encode(os.urandom(KEY_BYTES)).decode("ascii")},
    }
    rendered = json.dumps(document, indent=2) + "\n"
    parse_keyring(rendered, expected_purpose=purpose)  # type: ignore[arg-type]
    return rendered


_PURPOSES = ("field-encryption", "blind-index")
FINGERPRINT_LABEL = b"mykhaya-keyring-fingerprint-v1"


def _purpose_of(document: str) -> str:
    try:
        purpose = json.loads(document).get("purpose")
    except (json.JSONDecodeError, AttributeError):
        raise KeyConfigurationError("The keyring is not a valid JSON object.") from None
    if purpose not in _PURPOSES:
        raise KeyConfigurationError("The keyring does not declare a known purpose.")
    return str(purpose)


def keyring_fingerprint(document: str) -> dict[str, object]:
    """A non-secret summary that identifies the exact key material.

    Each fingerprint is HMAC-SHA256(key, fixed label) truncated to 64 bits:
    it reveals nothing about the key, but two keyrings produce identical
    output only if every key ID maps to the same 32 key bytes. Safe to print,
    paste into an operations log, or compare between escrow and production.
    """
    purpose = _purpose_of(document)
    keyring = parse_keyring(document, expected_purpose=purpose)  # type: ignore[arg-type]
    return {
        "purpose": purpose,
        "environment": keyring.environment,
        "active": keyring.active_key_id(),
        "fingerprints": {
            key_id: hmac.new(
                keyring.get_key(key_id), FINGERPRINT_LABEL, hashlib.sha256
            ).hexdigest()[:16]
            for key_id in keyring.key_ids()
        },
    }


def rotated_keyring_document(existing: str, *, key_id: str) -> str:
    purpose = _purpose_of(existing)
    parse_keyring(existing, expected_purpose=purpose)  # type: ignore[arg-type]
    data = json.loads(existing)
    if key_id in data["keys"]:
        raise KeyConfigurationError("That key ID already exists in the keyring.")
    data["keys"][key_id] = base64.b64encode(os.urandom(KEY_BYTES)).decode("ascii")
    data["active"] = key_id
    rendered = json.dumps(data, indent=2) + "\n"
    parse_keyring(rendered, expected_purpose=purpose)  # type: ignore[arg-type]
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--purpose", choices=("field-encryption", "blind-index"))
    parser.add_argument("--environment", choices=("production", "development", "test"))
    parser.add_argument("--key-id")
    parser.add_argument("--rotate", type=Path, help="existing keyring file to extend")
    parser.add_argument(
        "--fingerprint", type=Path, help="print a non-secret fingerprint of a keyring file"
    )
    args = parser.parse_args(argv)
    try:
        if args.fingerprint:
            summary = keyring_fingerprint(args.fingerprint.read_text(encoding="utf-8"))
            sys.stdout.write(json.dumps(summary, indent=2) + "\n")
            return 0
        if not args.key_id:
            parser.error("--key-id is required to generate or rotate a keyring")
        if args.rotate:
            document = rotated_keyring_document(
                args.rotate.read_text(encoding="utf-8"), key_id=args.key_id
            )
        else:
            if not args.purpose or not args.environment:
                parser.error("--purpose and --environment are required for a new keyring")
            document = new_keyring_document(
                purpose=args.purpose, environment=args.environment, key_id=args.key_id
            )
    except (KeyConfigurationError, OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
