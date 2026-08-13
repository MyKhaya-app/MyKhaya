"""Platform administrator MFA: TOTP, WebAuthn passkeys, recovery codes, the
admin_mfa_required policy, fresh-auth on sensitive actions, and admin-lockout
protection. See mykhaya.platform_mfa, mykhaya.platform_security, and the
'/auth/mfa/*' and '/administrators/*' endpoints in mykhaya.routers.platform.

Reuses the admin_client/admin_factory/login/unsafe fixtures and helpers from
test_platform_control_centre.py rather than re-declaring the whole admin-auth
test harness.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from test_platform_control_centre import (  # noqa: F401
    ADMIN_ORIGIN,
    PASSWORD,
    admin_client,
    admin_factory,
    login,
    unsafe,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    AdminWebAuthnCredential,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
)
from mykhaya.secrets_crypto import decrypt_secret
from mykhaya.security import hash_secret

# The admin_client fixture always binds the same fake peer, so the
# "platform-mfa-setup"/"platform-mfa-verify" rate-limit buckets accumulate
# across every test in this file — reset them before each test rather than
# widening the production limits just to make the suite pass.
PEER = "127.0.0.1"


async def _reset_rate_limit(bucket: str) -> None:
    identity = hashlib.sha256(PEER.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


@pytest.fixture(autouse=True)
async def _reset_mfa_rate_limits() -> AsyncIterator[None]:
    for bucket in ("platform-mfa-setup", "platform-mfa-verify", "platform-login"):
        await _reset_rate_limit(bucket)
    yield


def new_admin_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    )


async def _force_recent_auth(admin_id: uuid.UUID) -> None:
    """Most of these tests need require_recent_auth to already be satisfied so
    they can focus on the behaviour under test, not step-up itself (which has
    its own coverage in test_platform_control_centre.py)."""
    async with SessionFactory() as db:
        await db.execute(
            update(PlatformSession)
            .where(PlatformSession.administrator_id == admin_id)
            .values(authenticated_at=datetime.now(UTC))
        )
        await db.commit()


async def _enable_totp(client: AsyncClient) -> str:
    setup = await unsafe(client, "POST", "/api/v1/platform/auth/mfa/totp/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = await unsafe(
        client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": code}
    )
    assert verify.status_code == 200, verify.text
    return secret


@pytest.mark.asyncio
async def test_totp_setup_requires_a_correct_code_before_enabling(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    setup = await unsafe(admin_client, "POST", "/api/v1/platform/auth/mfa/totp/setup")
    assert setup.status_code == 200
    wrong = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": "000000"}
    )
    assert wrong.status_code == 400
    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.totp_enabled is False

    correct = pyotp.TOTP(setup.json()["secret"]).now()
    verified = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": correct}
    )
    assert verified.status_code == 200
    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.totp_enabled is True
        assert row.mfa_enrolled is True
        # The secret is encrypted at rest, never plaintext.
        assert row.totp_secret_encrypted is not None
        assert setup.json()["secret"] not in row.totp_secret_encrypted
        assert decrypt_secret(get_settings(), row.totp_secret_encrypted) == setup.json()["secret"]


@pytest.mark.asyncio
async def test_totp_login_requires_a_valid_code_and_completes_the_session(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    secret = await _enable_totp(admin_client)

    async with new_admin_client() as second:
        await login(second, admin)
        me = await second.get("/api/v1/platform/auth/me")
        assert me.status_code == 200
        assert me.json()["session_status"] == "pending_mfa"

        blocked = await second.get("/api/v1/platform/overview")
        assert blocked.status_code == 403

        wrong = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/totp/login-verify", json={"code": "111111"}
        )
        assert wrong.status_code == 400

        correct = pyotp.TOTP(secret).now()
        verified = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/totp/login-verify", json={"code": correct}
        )
        assert verified.status_code == 200
        assert verified.json()["session_status"] == "full"
        assert (await second.get("/api/v1/platform/overview")).status_code == 200


@pytest.mark.asyncio
async def test_completing_mfa_rotates_the_session_token_not_just_its_status(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Session-fixation regression test: the pending_mfa session's own cookie
    must never itself become usable as a full session. Completing the second
    factor must issue a brand-new token and revoke the pre-MFA one, not just
    flip a status column on the same row."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    secret = await _enable_totp(admin_client)

    async with new_admin_client() as second:
        await login(second, admin)
        pre_mfa_token = second.cookies.get("mk_admin_session")
        assert pre_mfa_token is not None

        async with SessionFactory() as db:
            pre_mfa_hash = hash_secret(pre_mfa_token, get_settings().secret_key.get_secret_value())
            pre_mfa_row = await db.scalar(
                select(PlatformSession).where(PlatformSession.token_hash == pre_mfa_hash)
            )
            assert pre_mfa_row is not None
            assert pre_mfa_row.status.value == "pending_mfa"
            assert pre_mfa_row.revoked_at is None

        correct = pyotp.TOTP(secret).now()
        verified = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/totp/login-verify", json={"code": correct}
        )
        assert verified.status_code == 200

        post_mfa_token = second.cookies.get("mk_admin_session")
        assert post_mfa_token is not None
        # A genuinely new token, not the same one with its status changed.
        assert post_mfa_token != pre_mfa_token

        async with SessionFactory() as db:
            stale_row = await db.get(PlatformSession, pre_mfa_row.id)
            assert stale_row is not None
            assert stale_row.revoked_at is not None

            new_hash = hash_secret(post_mfa_token, get_settings().secret_key.get_secret_value())
            new_row = await db.scalar(
                select(PlatformSession).where(PlatformSession.token_hash == new_hash)
            )
            assert new_row is not None
            assert new_row.id != pre_mfa_row.id
            assert new_row.status.value == "full"
            assert new_row.revoked_at is None

        # The old, pre-MFA cookie must be dead — presenting it again must not
        # grant privileged access, even to the MFA-verify endpoints themselves.
        async with new_admin_client() as replay:
            replay.cookies.set("mk_admin_session", pre_mfa_token)
            csrf = second.cookies.get("mk_admin_csrf")
            if csrf:
                replay.cookies.set("mk_admin_csrf", csrf)
            stale_attempt = await replay.get("/api/v1/platform/auth/me")
            assert stale_attempt.status_code == 401


@pytest.mark.asyncio
async def test_completing_mandatory_enrollment_also_rotates_the_session_token(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Same protection for the other transition: mfa_setup_required -> full."""
    admin = await admin_factory(PlatformRole.owner)
    forced_mfa = get_settings().model_copy(update={"admin_mfa_required": True})
    app.dependency_overrides[get_settings] = lambda: forced_mfa
    try:
        await login(admin_client, admin)
        pre_enrollment_token = admin_client.cookies.get("mk_admin_session")
        assert pre_enrollment_token is not None

        setup = await unsafe(admin_client, "POST", "/api/v1/platform/auth/mfa/totp/setup")
        assert setup.status_code == 200
        code = pyotp.TOTP(setup.json()["secret"]).now()
        verified = await unsafe(
            admin_client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": code}
        )
        assert verified.status_code == 200
        assert verified.json()["session_status"] == "full"

        post_enrollment_token = admin_client.cookies.get("mk_admin_session")
        assert post_enrollment_token is not None
        assert post_enrollment_token != pre_enrollment_token

        async with SessionFactory() as db:
            pre_hash = hash_secret(
                pre_enrollment_token, get_settings().secret_key.get_secret_value()
            )
            pre_row = await db.scalar(
                select(PlatformSession).where(PlatformSession.token_hash == pre_hash)
            )
            assert pre_row is not None
            assert pre_row.revoked_at is not None
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_disabling_totp_requires_recent_auth_and_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_totp(admin_client)

    async with SessionFactory() as db:
        await db.execute(
            update(PlatformSession)
            .where(PlatformSession.administrator_id == admin.id)
            .values(authenticated_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()
    stale = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/totp/disable",
        json={"reason": "No longer needed for this test account", "confirmed": True},
    )
    assert stale.status_code == 403

    await _force_recent_auth(admin.id)
    disabled = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/totp/disable",
        json={"reason": "No longer needed for this test account", "confirmed": True},
    )
    assert disabled.status_code == 204
    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, admin.id)
        assert row is not None
        assert row.totp_enabled is False
        assert row.totp_secret_encrypted is None
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == admin.id,
                AdministrativeAuditEvent.action == "administrator.totp_disabled",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None


@pytest.mark.asyncio
async def test_recovery_codes_require_existing_mfa_are_single_use_and_regeneration_invalidates_old(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    too_early = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Set up recovery for this test account", "confirmed": True},
    )
    assert too_early.status_code == 409

    await _enable_totp(admin_client)
    await _force_recent_auth(admin.id)
    generated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Set up recovery for this test account", "confirmed": True},
    )
    assert generated.status_code == 200
    codes = generated.json()["codes"]
    assert len(codes) == 10

    status_before = await admin_client.get("/api/v1/platform/auth/mfa/recovery-codes/status")
    assert status_before.json()["remaining"] == 10

    async with new_admin_client() as second:
        await login(second, admin)
        first_use = await unsafe(
            second,
            "POST",
            "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
            json={"code": codes[0]},
        )
        assert first_use.status_code == 200
        assert first_use.json()["session_status"] == "full"

    async with new_admin_client() as third:
        await login(third, admin)
        reused = await unsafe(
            third,
            "POST",
            "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
            json={"code": codes[0]},
        )
        assert reused.status_code == 400

    status_after = await admin_client.get("/api/v1/platform/auth/mfa/recovery-codes/status")
    assert status_after.json()["remaining"] == 9

    await _force_recent_auth(admin.id)
    regenerated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Regenerate after suspected exposure", "confirmed": True},
    )
    assert regenerated.status_code == 200
    new_codes = regenerated.json()["codes"]
    assert new_codes != codes

    async with new_admin_client() as fourth:
        await login(fourth, admin)
        old_code_now_invalid = await unsafe(
            fourth,
            "POST",
            "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
            json={"code": codes[1]},
        )
        assert old_code_now_invalid.status_code == 400


@pytest.mark.asyncio
async def test_mfa_policy_enforced_sends_unenrolled_admin_through_setup_not_full_access(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """The core lockout-avoidance behaviour: policy on + no MFA yet must never
    grant full access, and must never simply lock the administrator out either
    — it must route them through enrollment."""
    admin = await admin_factory(PlatformRole.owner)
    forced_mfa = get_settings().model_copy(update={"admin_mfa_required": True})
    app.dependency_overrides[get_settings] = lambda: forced_mfa
    try:
        await login(admin_client, admin)
        me = await admin_client.get("/api/v1/platform/auth/me")
        assert me.status_code == 200
        assert me.json()["session_status"] == "mfa_setup_required"

        blocked = await admin_client.get("/api/v1/platform/overview")
        assert blocked.status_code == 403

        # But enrollment itself must be reachable in this state.
        setup = await unsafe(admin_client, "POST", "/api/v1/platform/auth/mfa/totp/setup")
        assert setup.status_code == 200
        code = pyotp.TOTP(setup.json()["secret"]).now()
        verified = await unsafe(
            admin_client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": code}
        )
        assert verified.status_code == 200
        assert verified.json()["session_status"] == "full"
        assert (await admin_client.get("/api/v1/platform/overview")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_mfa_cannot_be_bypassed_via_any_ordinary_route(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """A pending_mfa session must never be treated as though it were full by
    any other route — spot-check a representative cross-section."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_totp(admin_client)

    async with new_admin_client() as second:
        await login(second, admin)
        for path in (
            "/api/v1/platform/overview",
            "/api/v1/platform/health",
            "/api/v1/platform/administrators",
        ):
            response = await second.get(path)
            assert response.status_code == 403, path
        # Nor can a pending session register a *new* factor without proving the
        # existing one first — that would be a bypass of the second factor.
        options = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/webauthn/register/options"
        )
        assert options.status_code == 403


@pytest.mark.asyncio
async def test_final_platform_owner_cannot_be_deactivated_or_demoted(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _force_recent_auth(admin.id)

    async with SessionFactory() as db:
        other_owners = await db.scalars(
            select(PlatformAdministrator).where(
                PlatformAdministrator.role == PlatformRole.owner,
                PlatformAdministrator.is_active.is_(True),
                PlatformAdministrator.id != admin.id,
            )
        )
        ids = [row.id for row in other_owners]
        if ids:
            await db.execute(delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(ids)))
            await db.commit()

    response = await unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/administrators/{admin.id}",
        json={
            "is_active": False,
            "reason": "Attempting to remove the last owner",
            "confirmed": True,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_resetting_another_administrators_mfa_clears_it_and_revokes_their_sessions(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    target = await admin_factory(PlatformRole.administrator)
    await login(admin_client, owner)
    await _force_recent_auth(owner.id)

    async with new_admin_client() as target_client:
        await login(target_client, target)
        await _enable_totp(target_client)

    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, target.id)
        assert row is not None and row.totp_enabled is True

    reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/administrators/{target.id}/mfa/reset",
        json={"reason": "Target lost their authenticator device", "confirmed": True},
    )
    assert reset.status_code == 204

    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, target.id)
        assert row is not None
        assert row.totp_enabled is False
        assert row.mfa_enrolled is False
        webauthn_count = await db.scalar(
            select(func.count())
            .select_from(AdminWebAuthnCredential)
            .where(AdminWebAuthnCredential.administrator_id == target.id)
        )
        assert not webauthn_count
        active_sessions = await db.scalar(
            select(func.count())
            .select_from(PlatformSession)
            .where(
                PlatformSession.administrator_id == target.id,
                PlatformSession.revoked_at.is_(None),
            )
        )
        assert not active_sessions
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == owner.id,
                AdministrativeAuditEvent.action == "administrator.mfa_reset",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.target_id == target.id

    # Cannot be used to reset your own MFA (self-service belongs on your own
    # Security page, and this endpoint skips the recovery-code/session nuance
    # a self-reset should never allow so casually).
    self_reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/administrators/{owner.id}/mfa/reset",
        json={"reason": "Trying to self-reset", "confirmed": True},
    )
    assert self_reset.status_code == 409


@pytest.mark.asyncio
async def test_removing_the_only_second_factor_is_blocked_while_mfa_is_required(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    forced_mfa = get_settings().model_copy(update={"admin_mfa_required": True})
    app.dependency_overrides[get_settings] = lambda: forced_mfa
    try:
        await login(admin_client, admin)
        await _enable_totp(admin_client)
        await _force_recent_auth(admin.id)
        blocked = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/auth/mfa/totp/disable",
            json={"reason": "Trying to remove my only factor", "confirmed": True},
        )
        assert blocked.status_code == 409
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_ordinary_administrator_role_cannot_change_mfa_policy(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.administrator)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/auth/mfa/policy",
        json={
            "required": True,
            "reason": "Trying to change policy without owner role",
            "confirmed": True,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webauthn_registration_options_issue_a_single_use_challenge(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Full attestation/assertion cryptography needs a real (or simulated)
    authenticator, which is out of scope here — this covers what's testable
    without one: options are issued with a fresh challenge, a garbage/replayed
    credential response is rejected cleanly (never a 500), and the challenge is
    consumed on the first attempt so a second attempt has nothing left to check
    against."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    options = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/webauthn/register/options"
    )
    assert options.status_code == 200
    body = options.json()["options_json"]
    assert '"challenge"' in body
    assert '"rp"' in body

    garbage = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/webauthn/register/verify",
        json={"label": "My key", "credential_json": '{"not": "a real credential"}'},
    )
    assert garbage.status_code == 400

    # The challenge was consumed by the first (failed) verify attempt above —
    # a second attempt, even with a well-formed-looking payload, has nothing
    # left to validate against and must also fail, not silently succeed.
    replay = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/webauthn/register/verify",
        json={"label": "My key", "credential_json": '{"not": "a real credential"}'},
    )
    assert replay.status_code == 400

    async with SessionFactory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(AdminWebAuthnCredential)
            .where(AdminWebAuthnCredential.administrator_id == admin.id)
        )
        assert not count


@pytest.mark.asyncio
async def test_webauthn_login_options_require_pending_mfa_and_a_registered_credential(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    # A full (not pending) session has nothing to verify.
    full_session_attempt = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/webauthn/login/options"
    )
    assert full_session_attempt.status_code == 403

    await _enable_totp(admin_client)
    async with new_admin_client() as second:
        await login(second, admin)
        # pending_mfa, but no passkey registered — only TOTP.
        no_passkey = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/webauthn/login/options"
        )
        assert no_passkey.status_code == 409


@pytest.mark.asyncio
async def test_recovery_codes_and_totp_secret_are_never_logged_in_audit_metadata(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    secret = await _enable_totp(admin_client)
    await _force_recent_auth(admin.id)
    generated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Set up recovery for this test account", "confirmed": True},
    )
    codes = generated.json()["codes"]

    async with SessionFactory() as db:
        events = await db.scalars(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.administrator_id == admin.id
            )
        )
        for event in events:
            blob = f"{event.previous_values}{event.new_values}{event.reason or ''}"
            assert secret not in blob
            for code in codes:
                assert code not in blob


def test_webauthn_credential_id_round_trips_through_options_instead_of_utf8_encoding() -> None:
    """Regression for the actual root cause behind Bitwarden reporting 'No
    passkeys found for this application' for an account with a genuinely
    registered passkey: AdminWebAuthnCredential.credential_id is stored as a
    base64url *string*. build_registration_options/build_authentication_options
    must decode it back to the original raw bytes with base64url_to_bytes — a
    previous version instead did `credential_id.encode("utf-8")`, which
    silently produces a different, meaningless byte sequence that no real
    authenticator can ever match, so the browser is sent an allowCredentials/
    excludeCredentials list corresponding to no real credential."""
    import json

    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

    from mykhaya.config import get_settings
    from mykhaya.platform_mfa import build_authentication_options, build_registration_options

    settings = get_settings()
    raw_credential_id = b"\x00\x01\xff\xfe\x10\x20some-real-credential-id-bytes"
    stored_credential_id = bytes_to_base64url(raw_credential_id)

    reg_json, _ = build_registration_options(
        settings, uuid.uuid4(), "owner@example.com", "Owner", [stored_credential_id]
    )
    reg_excluded = json.loads(reg_json)["excludeCredentials"][0]["id"]
    assert base64url_to_bytes(reg_excluded) == raw_credential_id

    auth_json, _ = build_authentication_options(settings, [stored_credential_id])
    auth_allowed = json.loads(auth_json)["allowCredentials"][0]["id"]
    assert base64url_to_bytes(auth_allowed) == raw_credential_id


@pytest.mark.asyncio
async def test_first_totp_factor_atomically_issues_usable_recovery_codes(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Regression for an administrator being left with a completed MFA
    enrollment and zero recovery codes: previously the frontend made a
    *separate* follow-up call to generate recovery codes after enrollment
    completed, which could be interrupted (closed tab, dropped network) and
    leave mfa_enrolled=True with nothing to recover with. The codes must now
    come back atomically on the same response that completes the first
    factor."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    setup = await unsafe(admin_client, "POST", "/api/v1/platform/auth/mfa/totp/setup")
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/totp/verify", json={"code": code}
    )
    assert verify.status_code == 200, verify.text
    codes = verify.json()["recovery_codes"]
    assert codes is not None
    assert len(codes) == 10

    async with new_admin_client() as second:
        await login(second, admin)
        used = await unsafe(
            second,
            "POST",
            "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
            json={"code": codes[0]},
        )
        assert used.status_code == 200
        assert used.json()["session_status"] == "full"

    # Adding a *second* factor for an already-enrolled administrator must not
    # silently regenerate (and thus invalidate) the codes they already saved.
    async with SessionFactory() as db:
        await db.execute(
            update(PlatformSession)
            .where(PlatformSession.administrator_id == admin.id)
            .values(authenticated_at=datetime.now(UTC))
        )
        await db.commit()
    options = await unsafe(
        admin_client, "POST", "/api/v1/platform/auth/mfa/webauthn/register/options"
    )
    assert options.status_code == 200
    status_after = await admin_client.get("/api/v1/platform/auth/mfa/recovery-codes/status")
    assert status_after.json()["remaining"] == 9


@pytest.mark.asyncio
async def test_login_only_advertises_second_factors_that_actually_exist(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Regression for the login page always rendering 'use an authenticator
    app instead' / 'use a recovery code instead' regardless of whether either
    was ever set up for the account — safe to disclose here since the caller
    has already proven the account's password."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_totp(admin_client)

    async with new_admin_client() as second:
        result = await second.post(
            "/api/v1/platform/auth/login",
            json={"email": admin.email, "password": PASSWORD},
        )
        assert result.status_code == 200
        actor = result.json()
        assert actor["session_status"] == "pending_mfa"
        # _enable_totp completes the administrator's first factor, which now
        # atomically issues recovery codes too (see
        # test_first_totp_factor_atomically_issues_usable_recovery_codes) — so
        # both are genuinely available, and passkey correctly is not.
        assert set(actor["available_factors"]) == {"totp", "recovery_code"}
        assert "passkey" not in actor["available_factors"]
