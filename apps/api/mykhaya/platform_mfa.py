"""Second-factor authentication for platform administrators: TOTP authenticator
apps, WebAuthn passkeys, and recovery codes.

Deliberately standards-based throughout — pyotp for RFC 6238 TOTP, the `webauthn`
package (duo-labs/py_webauthn) for WebAuthn Level 2 — no bespoke protocol. See
mykhaya.routers.platform for the endpoints that call these helpers and
mykhaya.platform_security for how PlatformSession.status gates access until a
required second factor has been presented.
"""

from __future__ import annotations

import base64
import secrets
import uuid
from datetime import datetime

import pyotp
from pyotp.utils import strings_equal
from redis.asyncio import Redis
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from mykhaya.config import Settings
from mykhaya.security import hash_secret

TOTP_ISSUER = "MyKhaya"
RECOVERY_CODE_COUNT = 10
_CHALLENGE_TTL_SECONDS = 300  # short-lived: long enough for a real authentication
# ceremony, short enough that a leaked/abandoned challenge is useless quickly.


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def totp_matched_step(secret: str, code: str) -> int | None:
    """Verifies `code` against the ±1 accepted time-steps (valid_window=1,
    tolerating ±30s clock drift — standard TOTP practice) and returns exactly
    which step it matched, or None if it matches none of them. Surfacing the
    matched step (rather than a plain bool, as this used to return) is what
    lets PCC-SEC-005's replay guard below mark that specific 30s window as
    spent instead of only knowing "some code was accepted"."""
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = datetime.now()
    base_step = totp.timecode(now)
    for offset in (-1, 0, 1):
        if strings_equal(code, totp.at(now, offset)):
            return base_step + offset
    return None


# ---------------------------------------------------------------------------
# TOTP replay guard (PCC-SEC-005) — Redis, single-use per (purpose,
# administrator, time-step), short TTL. valid_window=1 means a given code
# stays acceptable across roughly a 90s span; without this, the same
# once-observed code could be submitted more than once inside that window.
# Setup-verify and login-verify use separate purposes so enrolling TOTP and
# then immediately signing in with the same still-valid code isn't treated as
# a replay of itself — they're different ceremonies, on (in general) different
# sessions.
# ---------------------------------------------------------------------------

_TOTP_REPLAY_TTL_SECONDS = 90  # slightly longer than the ~90s acceptance span itself


async def claim_totp_step(
    settings: Settings, purpose: str, administrator_id: uuid.UUID, step: int
) -> bool:
    """Atomic set-if-not-exists. True = this step was unclaimed and is now
    claimed (verification may proceed); False = it was already claimed (this
    is a replay, reject it) — a plain get-then-set would itself be racy,
    which is exactly the class of bug this feature exists to close elsewhere."""
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        claimed = await redis.set(
            f"totp-replay:{purpose}:{administrator_id}:{step}",
            "1",
            nx=True,
            ex=_TOTP_REPLAY_TTL_SECONDS,
        )
        return bool(claimed)
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]


def hash_recovery_code(settings: Settings, code: str) -> str:
    # Normalised the same way it will be typed back: case/whitespace-insensitive.
    return hash_secret(code.strip().lower(), settings.secret_key.get_secret_value())


# ---------------------------------------------------------------------------
# WebAuthn challenge storage — Redis, single-use, TTL'd, bound to the specific
# PlatformSession the ceremony belongs to so a challenge issued for one login
# attempt can never be replayed against another.
# ---------------------------------------------------------------------------


def _challenge_key(purpose: str, session_id: uuid.UUID) -> str:
    return f"webauthn-challenge:{purpose}:{session_id}"


async def store_webauthn_challenge(
    settings: Settings, purpose: str, session_id: uuid.UUID, challenge: bytes
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _challenge_key(purpose, session_id),
            base64.urlsafe_b64encode(challenge).decode("ascii"),
            ex=_CHALLENGE_TTL_SECONDS,
        )
    finally:
        await redis.aclose()


async def pop_webauthn_challenge(
    settings: Settings, purpose: str, session_id: uuid.UUID
) -> bytes | None:
    """Single-use: GETDEL retrieves and deletes atomically (PCC-SEC-011) — a
    plain GET-then-DELETE would let two concurrent verify calls both GET the
    same challenge before either DELETE ran. GETDEL is a single Redis command,
    so exactly one caller can ever get the raw challenge back; every
    subsequent call (replayed or concurrent) sees None."""
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_challenge_key(purpose, session_id))
        if raw is None:
            return None
        return base64.urlsafe_b64decode(raw)
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# WebAuthn registration (adding a new passkey)
#
# AdminWebAuthnCredential.credential_id is stored as a base64url *string*
# (bytes_to_base64url of the raw credential ID). Every PublicKeyCredentialDescriptor
# built from a stored credential_id must decode it back with base64url_to_bytes —
# `.encode("utf-8")` on the string is a different, meaningless byte sequence that no
# authenticator will ever match, and previously made passkey sign-in silently
# unusable (the browser reports "no passkeys found" because the allowCredentials/
# excludeCredentials list it was given doesn't correspond to any real credential).
# ---------------------------------------------------------------------------


def build_registration_options(
    settings: Settings,
    administrator_id: uuid.UUID,
    email: str,
    display_name: str,
    existing_credential_ids: list[str],
) -> tuple[str, bytes]:
    """Returns (options_json_for_client, raw_challenge_to_store)."""
    options = generate_registration_options(
        rp_id=settings.admin_webauthn_rp_id,
        rp_name=TOTP_ISSUER,
        user_id=str(administrator_id).encode("utf-8"),
        user_name=email,
        user_display_name=display_name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential_id))
            for credential_id in existing_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options_to_json(options), options.challenge


class WebAuthnRegistrationResult:
    __slots__ = ("credential_id", "public_key", "sign_count")

    def __init__(self, credential_id: str, public_key: str, sign_count: int) -> None:
        self.credential_id = credential_id
        self.public_key = public_key
        self.sign_count = sign_count


def verify_registration(
    settings: Settings, credential_json: str, expected_challenge: bytes
) -> WebAuthnRegistrationResult | None:
    try:
        verified = verify_registration_response(
            credential=credential_json,
            expected_challenge=expected_challenge,
            expected_origin=settings.admin_webauthn_origin,
            expected_rp_id=settings.admin_webauthn_rp_id,
        )
    except WebAuthnException:
        # Covers every malformed/invalid-response case the library can raise —
        # bad JSON, wrong challenge, wrong origin, bad signature, unsupported
        # algorithm, and so on — as one clean "this could not be verified"
        # outcome. The client only ever gets a generic 400, never a stack trace.
        return None
    return WebAuthnRegistrationResult(
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
    )


# ---------------------------------------------------------------------------
# WebAuthn authentication (using a passkey to sign in)
# ---------------------------------------------------------------------------


def build_authentication_options(
    settings: Settings, allowed_credential_ids: list[str]
) -> tuple[str, bytes]:
    options: PublicKeyCredentialRequestOptions = generate_authentication_options(
        rp_id=settings.admin_webauthn_rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential_id))
            for credential_id in allowed_credential_ids
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json(options), options.challenge


def verify_authentication(
    settings: Settings,
    credential_json: str,
    expected_challenge: bytes,
    stored_public_key: str,
    stored_sign_count: int,
) -> int | None:
    """Returns the new sign count to persist, or None if verification failed.

    The sign-count check (WebAuthn's built-in clone-detection signal) is
    delegated entirely to the library — a stored sign count that doesn't
    strictly increase indicates a cloned authenticator and verification fails.
    """
    try:
        verified = verify_authentication_response(
            credential=credential_json,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.admin_webauthn_rp_id,
            expected_origin=settings.admin_webauthn_origin,
            credential_public_key=base64.urlsafe_b64decode(stored_public_key + "=="),
            credential_current_sign_count=stored_sign_count,
        )
    except WebAuthnException:
        return None
    return verified.new_sign_count


# ---------------------------------------------------------------------------
# Family-user passkeys
#
# These helpers deliberately use the same standards-based library and challenge
# storage as PCC, but take the family RP/origin and require user verification.
# The caller remains responsible for the separate family credential table and
# adult-session policy.
# ---------------------------------------------------------------------------


def build_family_registration_options(
    settings: Settings,
    user_id: uuid.UUID,
    email: str,
    display_name: str,
    existing_credential_ids: list[str],
) -> tuple[str, bytes]:
    options = generate_registration_options(
        rp_id=settings.family_webauthn_rp_id,
        rp_name=TOTP_ISSUER,
        user_id=str(user_id).encode("utf-8"),
        user_name=email,
        user_display_name=display_name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential_id))
            for credential_id in existing_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options), options.challenge


def build_family_authentication_options(settings: Settings) -> tuple[str, bytes]:
    options: PublicKeyCredentialRequestOptions = generate_authentication_options(
        rp_id=settings.family_webauthn_rp_id,
        allow_credentials=[],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(options), options.challenge


def verify_family_registration(
    settings: Settings, credential_json: str, expected_challenge: bytes
) -> WebAuthnRegistrationResult | None:
    try:
        verified = verify_registration_response(
            credential=credential_json,
            expected_challenge=expected_challenge,
            expected_origin=settings.family_webauthn_origin,
            expected_rp_id=settings.family_webauthn_rp_id,
        )
    except WebAuthnException:
        return None
    return WebAuthnRegistrationResult(
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
    )


def verify_family_authentication(
    settings: Settings,
    credential_json: str,
    expected_challenge: bytes,
    stored_public_key: str,
    stored_sign_count: int,
) -> int | None:
    try:
        verified = verify_authentication_response(
            credential=credential_json,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.family_webauthn_rp_id,
            expected_origin=settings.family_webauthn_origin,
            credential_public_key=base64.urlsafe_b64decode(stored_public_key + "=="),
            credential_current_sign_count=stored_sign_count,
        )
    except WebAuthnException:
        return None
    return verified.new_sign_count


def _token_challenge_key(purpose: str, token: str, key: str) -> str:
    return f"webauthn-challenge:{purpose}:token:{hash_secret(token, key)}"


async def store_webauthn_token_challenge(
    settings: Settings, purpose: str, token: str, challenge: bytes
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _token_challenge_key(purpose, token, settings.secret_key.get_secret_value()),
            base64.urlsafe_b64encode(challenge).decode("ascii"),
            ex=_CHALLENGE_TTL_SECONDS,
        )
    finally:
        await redis.aclose()


async def pop_webauthn_token_challenge(
    settings: Settings, purpose: str, token: str
) -> bytes | None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(
            _token_challenge_key(purpose, token, settings.secret_key.get_secret_value())
        )
        return base64.urlsafe_b64decode(raw) if raw is not None else None
    finally:
        await redis.aclose()
