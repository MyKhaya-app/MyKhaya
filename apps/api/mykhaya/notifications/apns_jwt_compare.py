"""Console-only structural comparison for two APNs provider JWTs.

The supplied Apple JWT is accepted through stdin or ``--apple-jwt`` but is
never printed. This module performs no APNs request.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

from mykhaya.config import get_settings
from mykhaya.notifications.push import (
    _build_apns_bearer,
    _normalise_apns_private_key,
    resolve_apns_config,
)


@dataclass(frozen=True)
class JwtStructure:
    valid: bool
    alg: str
    kid: str
    iss: str
    iat: str
    header_keys: tuple[str, ...]
    payload_keys: tuple[str, ...]
    header_bytes: int
    payload_bytes: int
    signature_bytes: int
    padding: bool
    base64url_valid: bool
    has_typ: bool
    unexpected_claims: tuple[str, ...]
    duplicate_keys: tuple[str, ...]
    utf8_valid: bool


class _DuplicateJsonKey(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _safe_text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value and len(value) <= 128 and all(
        ord(character) >= 0x20 for character in value
    ):
        return value
    return "invalid"


def _decode_segment(segment: str) -> tuple[bytes, bool, bool]:
    if not segment:
        return b"", False, False
    padding = "=" in segment
    unpadded = segment.rstrip("=")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if any(character not in allowed for character in unpadded):
        return b"", padding, False
    padding_count = len(segment) - len(unpadded)
    if (
        len(unpadded) % 4 == 1
        or padding_count > 2
        or (padding_count and len(segment) % 4 != 0)
        or segment != unpadded + "=" * padding_count
    ):
        return b"", padding, False
    try:
        decoded = base64.urlsafe_b64decode(unpadded + "=" * (-len(unpadded) % 4))
    except (TypeError, ValueError):
        return b"", padding, False
    return decoded, padding, base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() == unpadded


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def inspect_jwt(token: str) -> JwtStructure:
    segments = token.strip().split(".")
    if len(segments) != 3:
        return JwtStructure(
            False,
            "invalid",
            "invalid",
            "invalid",
            "invalid",
            (),
            (),
            0,
            0,
            0,
            False,
            False,
            False,
            (),
            (),
            False,
        )

    header_bytes, header_padding, header_b64 = _decode_segment(segments[0])
    payload_bytes, payload_padding, payload_b64 = _decode_segment(segments[1])
    signature_bytes, signature_padding, signature_b64 = _decode_segment(segments[2])
    utf8_valid = True
    duplicate_keys: list[str] = []
    try:
        header = json.loads(header_bytes.decode("utf-8"), object_pairs_hook=_object_pairs)
    except _DuplicateJsonKey as exc:
        duplicate_keys.append(_safe_text(exc.key))
        header = {}
        utf8_valid = False
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        utf8_valid = False
        header = {}
    try:
        payload = json.loads(payload_bytes.decode("utf-8"), object_pairs_hook=_object_pairs)
    except _DuplicateJsonKey as exc:
        duplicate_keys.append(_safe_text(exc.key))
        payload = {}
        utf8_valid = False
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        utf8_valid = False
        payload = {}

    header_is_object = isinstance(header, dict)
    payload_is_object = isinstance(payload, dict)
    header_keys = tuple(sorted(header)) if header_is_object else ()
    payload_keys = tuple(sorted(payload)) if payload_is_object else ()
    valid = (
        header_is_object
        and payload_is_object
        and utf8_valid
        and header_b64
        and payload_b64
        and signature_b64
        and len(signature_bytes) == 64
    )
    return JwtStructure(
        valid,
        _safe_text(header.get("alg")) if header_is_object else "invalid",
        _safe_text(header.get("kid")) if header_is_object else "invalid",
        _safe_text(payload.get("iss")) if payload_is_object else "invalid",
        _safe_text(payload.get("iat")) if payload_is_object else "invalid",
        header_keys,
        payload_keys,
        len(header_bytes),
        len(payload_bytes),
        len(signature_bytes),
        header_padding or payload_padding or signature_padding,
        header_b64 and payload_b64 and signature_b64,
        header_is_object and "typ" in header,
        tuple(sorted(key for key in payload_keys if key not in {"iss", "iat"})),
        tuple(sorted(set(duplicate_keys))),
        utf8_valid,
    )


def _print_structure(label: str, structure: JwtStructure) -> None:
    print(f"{label}.valid={str(structure.valid).lower()}")
    print(f"{label}.alg={structure.alg}")
    print(f"{label}.kid={structure.kid}")
    print(f"{label}.iss={structure.iss}")
    print(f"{label}.iat={structure.iat}")
    print(f"{label}.header_keys={','.join(structure.header_keys)}")
    print(f"{label}.payload_keys={','.join(structure.payload_keys)}")
    print(f"{label}.header_json_bytes={structure.header_bytes}")
    print(f"{label}.payload_json_bytes={structure.payload_bytes}")
    print(f"{label}.signature_bytes={structure.signature_bytes}")
    print(f"{label}.segments_contain_padding={str(structure.padding).lower()}")
    print(f"{label}.base64url_valid={str(structure.base64url_valid).lower()}")
    print(f"{label}.header_contains_typ={str(structure.has_typ).lower()}")
    print(f"{label}.unexpected_claims={','.join(structure.unexpected_claims) or 'none'}")
    print(f"{label}.duplicate_keys={','.join(structure.duplicate_keys) or 'none'}")
    print(f"{label}.utf8_valid={str(structure.utf8_valid).lower()}")


def _standard_jwt_structure(config: Any, issued_at: int) -> tuple[str, JwtStructure] | None:
    try:
        from authlib.jose import jwt
    except ImportError:
        return None
    try:
        token = jwt.encode(
            {"alg": "ES256", "kid": config.key_id},
            {"iss": config.team_id, "iat": issued_at},
            _normalise_apns_private_key(config.private_key).encode("utf-8"),
        )
    except Exception:
        return None
    if isinstance(token, bytes):
        token = token.decode("ascii")
    return "authlib", inspect_jwt(token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare APNs JWT structure without printing JWTs."
    )
    parser.add_argument("--apple-jwt", help="Apple-generated JWT; stdin is preferred.")
    args = parser.parse_args(argv)
    apple_token = args.apple_jwt if args.apple_jwt is not None else sys.stdin.read().strip()
    settings = get_settings()
    config = resolve_apns_config(settings)
    if not config.configured:
        raise SystemExit("APNs provider-token configuration is incomplete")
    issued_at = int(time.time())
    topic = config.bundle_id or "app.mykhaya.mobile"
    mykhaya_token = _build_apns_bearer(
        config, issued_at=issued_at, topic=topic, emit_diagnostics=False
    )
    apple = inspect_jwt(apple_token)
    mykhaya = inspect_jwt(mykhaya_token)
    _print_structure("apple", apple)
    _print_structure("mykhaya", mykhaya)
    print(f"kid_equal={str(apple.kid == mykhaya.kid).lower()}")
    print(f"iss_equal={str(apple.iss == mykhaya.iss).lower()}")
    print(f"alg_equal={str(apple.alg == mykhaya.alg).lower()}")
    print(f"header_keyset_equal={str(set(apple.header_keys) == set(mykhaya.header_keys)).lower()}")
    print(
        f"payload_keyset_equal={str(set(apple.payload_keys) == set(mykhaya.payload_keys)).lower()}"
    )
    print(f"signature_length_equal={str(apple.signature_bytes == mykhaya.signature_bytes).lower()}")
    standard = _standard_jwt_structure(config, issued_at)
    if standard is None:
        print("standard_jwt_library=unavailable")
    else:
        library, structure = standard
        print(f"standard_jwt_library={library}")
        standard_matches = (
            structure.header_keys == mykhaya.header_keys
            and structure.payload_keys == mykhaya.payload_keys
            and structure.signature_bytes == mykhaya.signature_bytes
        )
        print(f"standard_jwt_structure_matches_mykhaya={str(standard_matches).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
