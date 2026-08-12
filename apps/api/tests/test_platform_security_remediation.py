"""Regression tests for the PCC-SEC-* findings from the adversarial Platform
Control Centre security review, and their remediation:

- PCC-SEC-001: Security cannot reset an Owner's MFA (Owner still can).
- PCC-SEC-002: /auth/reauthenticate is rate limited and audits failures.
- PCC-SEC-003: the final-active-Owner invariant survives concurrent requests.
- PCC-SEC-004: recovery-code consumption is atomic under concurrency.
- PCC-SEC-005: an accepted TOTP code/time-step cannot be replayed.
- PCC-SEC-006: administrator security detail visibility matches the intended
  Owner (full) vs Administrator/Security (reduced, non-Owner-only) matrix.
- PCC-SEC-007: the rate limiter resolves identity via the same
  trusted-proxy-aware mechanism as the rest of the app, not the raw ASGI peer.
- PCC-SEC-011: the WebAuthn challenge store is atomically single-use.

Reuses the admin_client/admin_factory/login/unsafe/make_request fixtures and
helpers from test_platform_control_centre.py, and the
new_admin_client/_force_recent_auth/_enable_totp helpers from
test_platform_mfa.py, rather than re-declaring the admin-auth test harness a
third time.
"""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pyotp
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from test_platform_control_centre import (  # noqa: F401
    ADMIN_ORIGIN,
    admin_client,
    admin_factory,
    login,
    make_request,
    unsafe,
)
from test_platform_mfa import (  # noqa: F401
    PEER,
    _enable_totp,
    _force_recent_auth,
    new_admin_client,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import PlatformAdministrator, PlatformRole, PlatformSession, SecurityEvent
from mykhaya.platform_mfa import claim_totp_step, pop_webauthn_challenge, store_webauthn_challenge
from mykhaya.rate_limit import enforce_rate_limit


async def _reset_rate_limit(bucket: str) -> None:
    identity = hashlib.sha256(PEER.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


@pytest.fixture(autouse=True)
async def _reset_shared_rate_limits() -> AsyncIterator[None]:
    buckets = ("platform-login", "platform-mfa-setup", "platform-mfa-verify", "platform-reauth")
    for bucket in buckets:
        await _reset_rate_limit(bucket)
    yield


# ---------------------------------------------------------------------------
# PCC-SEC-001 — Security cannot reset an Owner's MFA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_role_cannot_reset_an_owners_mfa(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    security = await admin_factory(PlatformRole.security)
    async with new_admin_client() as owner_client, new_admin_client() as security_client:
        await login(owner_client, owner)
        await _enable_totp(owner_client)
        await login(security_client, security)
        await _force_recent_auth(security.id)

        denied = await unsafe(
            security_client,
            "POST",
            f"/api/v1/platform/administrators/{owner.id}/mfa/reset",
            json={"reason": "Attempting to reset an Owner's MFA", "confirmed": True},
        )
        assert denied.status_code == 403

    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, owner.id)
        assert row is not None
        assert row.totp_enabled is True
        active_sessions = await db.scalar(
            select(func.count())
            .select_from(PlatformSession)
            .where(
                PlatformSession.administrator_id == owner.id,
                PlatformSession.revoked_at.is_(None),
            )
        )
        assert active_sessions and active_sessions >= 1
        event = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.event_type == "administrator_mfa_reset_denied_role_escalation",
                SecurityEvent.administrator_id == security.id,
            )
        )
        assert event is not None
        assert event.severity == "high"
        assert event.outcome == "denied"


@pytest.mark.asyncio
async def test_administrator_role_cannot_reset_an_owners_mfa(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    plain_admin = await admin_factory(PlatformRole.administrator)
    async with new_admin_client() as admin_client_:
        await login(admin_client_, plain_admin)
        await _force_recent_auth(plain_admin.id)
        # The `administrator` role isn't even in require_roles for this
        # endpoint (owner, security only) — a plain 403 from the role gate
        # itself, before any target-role logic runs.
        denied = await unsafe(
            admin_client_,
            "POST",
            f"/api/v1/platform/administrators/{owner.id}/mfa/reset",
            json={"reason": "Attempting to reset an Owner's MFA", "confirmed": True},
        )
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_still_reset_a_security_operators_mfa(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    target = await admin_factory(PlatformRole.security)
    await login(admin_client, owner)
    await _force_recent_auth(owner.id)

    async with new_admin_client() as target_client:
        await login(target_client, target)
        await _enable_totp(target_client)

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


@pytest.mark.asyncio
async def test_security_role_can_still_reset_a_non_owner_administrators_mfa(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """The point of PCC-SEC-001 is a target-role check, not blanket
    Owner-only — Security retains its legitimate MFA-support capability for
    everyone except Owners."""
    security = await admin_factory(PlatformRole.security)
    target = await admin_factory(PlatformRole.support)
    async with new_admin_client() as security_client, new_admin_client() as target_client:
        await login(security_client, security)
        await _force_recent_auth(security.id)
        await login(target_client, target)
        await _enable_totp(target_client)

        reset = await unsafe(
            security_client,
            "POST",
            f"/api/v1/platform/administrators/{target.id}/mfa/reset",
            json={"reason": "Target lost their authenticator device", "confirmed": True},
        )
        assert reset.status_code == 204
    async with SessionFactory() as db:
        row = await db.get(PlatformAdministrator, target.id)
        assert row is not None
        assert row.totp_enabled is False


# ---------------------------------------------------------------------------
# PCC-SEC-002 — /auth/reauthenticate rate limiting and audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reauthenticate_succeeds_with_the_correct_password(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/reauthenticate",
        json={"password": "A separate operator password!"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reauthenticate_wrong_password_is_rejected_and_generates_a_security_event(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/reauthenticate",
        json={"password": "definitely the wrong password"},
    )
    assert response.status_code == 401
    assert "definitely the wrong password" not in response.text

    async with SessionFactory() as db:
        event = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.event_type == "administrator_reauthentication_failed",
                SecurityEvent.administrator_id == admin.id,
            )
        )
        assert event is not None
        assert event.outcome == "denied"
        assert "definitely the wrong password" not in (event.safe_detail or "")


@pytest.mark.asyncio
async def test_reauthenticate_is_throttled_after_repeated_failures(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    statuses = []
    for _ in range(12):
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/auth/reauthenticate",
            json={"password": "still the wrong password"},
        )
        statuses.append(response.status_code)
    assert 429 in statuses
    assert set(statuses) <= {401, 429}


# ---------------------------------------------------------------------------
# PCC-SEC-003 — the final-active-Owner invariant under concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_demotion_of_the_last_two_owners_cannot_both_succeed(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner_a = await admin_factory(PlatformRole.owner)
    owner_b = await admin_factory(PlatformRole.owner)

    async with SessionFactory() as db:
        other_owners = await db.scalars(
            select(PlatformAdministrator).where(
                PlatformAdministrator.role == PlatformRole.owner,
                PlatformAdministrator.is_active.is_(True),
                PlatformAdministrator.id.not_in([owner_a.id, owner_b.id]),
            )
        )
        ids = [row.id for row in other_owners]
        if ids:
            await db.execute(delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(ids)))
            await db.commit()

    async with new_admin_client() as client_a, new_admin_client() as client_b:
        await login(client_a, owner_a)
        await login(client_b, owner_b)
        await _force_recent_auth(owner_a.id)
        await _force_recent_auth(owner_b.id)

        response_a, response_b = await asyncio.gather(
            unsafe(
                client_a,
                "PATCH",
                f"/api/v1/platform/administrators/{owner_b.id}",
                json={
                    "is_active": False,
                    "reason": "Concurrency test — demoting owner B",
                    "confirmed": True,
                },
            ),
            unsafe(
                client_b,
                "PATCH",
                f"/api/v1/platform/administrators/{owner_a.id}",
                json={
                    "is_active": False,
                    "reason": "Concurrency test — demoting owner A",
                    "confirmed": True,
                },
            ),
        )

    statuses = {response_a.status_code, response_b.status_code}
    # One request wins the advisory lock and succeeds; the other must then
    # see the invariant already at its limit and be rejected — never both.
    assert 200 in statuses
    assert 409 in statuses

    async with SessionFactory() as db:
        remaining_active_owners = await db.scalar(
            select(func.count())
            .select_from(PlatformAdministrator)
            .where(
                PlatformAdministrator.role == PlatformRole.owner,
                PlatformAdministrator.is_active.is_(True),
            )
        )
        assert remaining_active_owners is not None
        assert remaining_active_owners >= 1


# ---------------------------------------------------------------------------
# PCC-SEC-004 — atomic recovery-code consumption under concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_code_two_concurrent_requests_only_one_succeeds(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_totp(admin_client)
    await _force_recent_auth(admin.id)
    generated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Set up recovery for a concurrency test", "confirmed": True},
    )
    code = generated.json()["codes"][0]

    async with new_admin_client() as first, new_admin_client() as second:
        await login(first, admin)
        await login(second, admin)
        response_1, response_2 = await asyncio.gather(
            unsafe(
                first, "POST", "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
                json={"code": code},
            ),
            unsafe(
                second, "POST", "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
                json={"code": code},
            ),
        )
    successes = [r for r in (response_1, response_2) if r.status_code == 200]
    failures = [r for r in (response_1, response_2) if r.status_code == 400]
    assert len(successes) == 1
    assert len(failures) == 1


@pytest.mark.asyncio
async def test_recovery_code_multi_way_concurrent_requests_exactly_one_succeeds(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_totp(admin_client)
    await _force_recent_auth(admin.id)
    generated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/mfa/recovery-codes",
        json={"reason": "Set up recovery for a concurrency test", "confirmed": True},
    )
    code = generated.json()["codes"][0]

    clients = [new_admin_client() for _ in range(8)]
    try:
        for client in clients:
            await login(client, admin)
        responses = await asyncio.gather(
            *[
                unsafe(
                    client,
                    "POST",
                    "/api/v1/platform/auth/mfa/recovery-codes/login-verify",
                    json={"code": code},
                )
                for client in clients
            ]
        )
    finally:
        for client in clients:
            await client.aclose()

    successes = [r for r in responses if r.status_code == 200]
    assert len(successes) == 1

    async with SessionFactory() as db:
        admin_row = await db.get(PlatformAdministrator, admin.id)
        assert admin_row is not None
    status = await admin_client.get("/api/v1/platform/auth/mfa/recovery-codes/status")
    assert status.json()["remaining"] == 9


# ---------------------------------------------------------------------------
# PCC-SEC-005 — TOTP replay protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_totp_step_can_only_be_claimed_once() -> None:
    settings = get_settings()
    admin_id = uuid.uuid4()
    assert await claim_totp_step(settings, "totp-login", admin_id, 424242) is True
    assert await claim_totp_step(settings, "totp-login", admin_id, 424242) is False


@pytest.mark.asyncio
async def test_totp_step_claim_is_scoped_per_administrator_and_purpose() -> None:
    settings = get_settings()
    admin_a, admin_b = uuid.uuid4(), uuid.uuid4()
    assert await claim_totp_step(settings, "totp-login", admin_a, 555) is True
    # A different administrator "using" the same step number is unaffected.
    assert await claim_totp_step(settings, "totp-login", admin_b, 555) is True
    # A different purpose for the same administrator/step is also unaffected
    # — setup and login are different ceremonies, not one shared namespace.
    assert await claim_totp_step(settings, "totp-setup", admin_a, 555) is True
    # The next time-step for the same administrator/purpose is unaffected —
    # only the exact (purpose, administrator, step) tuple is consumed.
    assert await claim_totp_step(settings, "totp-login", admin_a, 556) is True


@pytest.mark.asyncio
async def test_totp_login_code_cannot_be_replayed_against_a_fresh_session(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    secret = await _enable_totp(admin_client)

    async with new_admin_client() as second:
        await login(second, admin)
        code = pyotp.TOTP(secret).now()
        first = await unsafe(
            second, "POST", "/api/v1/platform/auth/mfa/totp/login-verify", json={"code": code}
        )
        assert first.status_code == 200

    async with new_admin_client() as third:
        await login(third, admin)
        replay = await unsafe(
            third, "POST", "/api/v1/platform/auth/mfa/totp/login-verify", json={"code": code}
        )
        assert replay.status_code == 400


# ---------------------------------------------------------------------------
# PCC-SEC-006 — administrator security detail authorization matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_administrator_security_detail_authorization_matrix(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    other_owner = await admin_factory(PlatformRole.owner)
    plain_admin = await admin_factory(PlatformRole.administrator)
    security = await admin_factory(PlatformRole.security)

    async with (
        new_admin_client() as owner_client,
        new_admin_client() as admin_client_,
        new_admin_client() as security_client,
    ):
        await login(owner_client, owner)
        await login(admin_client_, plain_admin)
        await login(security_client, security)

        # Owner: full detail for another Owner.
        full = await owner_client.get(f"/api/v1/platform/administrators/{other_owner.id}/security")
        assert full.status_code == 200
        full_body = full.json()
        assert "sessions" in full_body
        assert "webauthn_credentials" in full_body

        # Administrator/Security: no visibility into an Owner at all.
        assert (
            await admin_client_.get(f"/api/v1/platform/administrators/{owner.id}/security")
        ).status_code == 403
        assert (
            await security_client.get(f"/api/v1/platform/administrators/{owner.id}/security")
        ).status_code == 403

        # Administrator/Security: reduced summary for a non-Owner target.
        summary = await security_client.get(
            f"/api/v1/platform/administrators/{plain_admin.id}/security"
        )
        assert summary.status_code == 200
        summary_body = summary.json()
        assert "sessions" not in summary_body
        assert "webauthn_credentials" not in summary_body
        assert "webauthn_credential_count" in summary_body
        assert "active_session_count" in summary_body

        # Self-view always gets the full shape, regardless of the viewer's
        # own role — needed to manage your own passkeys/sessions.
        own = await admin_client_.get(f"/api/v1/platform/administrators/{plain_admin.id}/security")
        assert own.status_code == 200
        assert "sessions" in own.json()
        assert "webauthn_credentials" in own.json()


@pytest.mark.asyncio
async def test_security_role_can_see_owner_related_audit_events_but_not_full_detail_or_control(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """NEW-001 (Platform Control Centre security re-review): Security's
    audit/security-event visibility into an Owner's activity — including
    source_ip — is accepted by design, and deliberately narrower than any
    authority over the Owner's account. Proves all four boundaries in one
    test: visibility granted, full detail denied, MFA-reset denied, and that
    no role can revoke another administrator's individual session."""
    owner = await admin_factory(PlatformRole.owner)
    security = await admin_factory(PlatformRole.security)

    async with new_admin_client() as owner_client, new_admin_client() as security_client:
        await login(owner_client, owner)
        await login(security_client, security)
        await _force_recent_auth(owner.id)
        await _force_recent_auth(security.id)

        # Generate at least one auditable event for the Owner to look up.
        reauth = await unsafe(
            owner_client,
            "POST",
            "/api/v1/platform/auth/reauthenticate",
            json={"password": "A separate operator password!"},
        )
        assert reauth.status_code == 200

        # 1. Security CAN see the Owner's audit trail, including source_ip —
        #    accepted by design (NEW-001), not withheld like the detail
        #    endpoint below.
        audit = await security_client.get(
            f"/api/v1/platform/audit?administrator_id={owner.id}&page_size=5"
        )
        assert audit.status_code == 200
        audit_rows = audit.json()["items"]
        assert audit_rows, "expected at least one audit row for the Owner"
        assert any(row.get("source_ip") for row in audit_rows)

        security_log = await security_client.get("/api/v1/platform/security?page_size=25")
        assert security_log.status_code == 200

        # 2. Security CANNOT see the Owner's full security/session detail —
        #    the PCC-SEC-006 boundary still holds even though 1 is allowed.
        detail = await security_client.get(f"/api/v1/platform/administrators/{owner.id}/security")
        assert detail.status_code == 403

        # 3. Security CANNOT reset the Owner's MFA (PCC-SEC-001).
        reset = await unsafe(
            security_client,
            "POST",
            f"/api/v1/platform/administrators/{owner.id}/mfa/reset",
            json={"reason": "NEW-001 boundary test", "confirmed": True},
        )
        assert reset.status_code == 403

        # 4. No role can revoke another administrator's individual session —
        #    DELETE /auth/sessions/{id} is unconditionally scoped to the
        #    caller's own sessions regardless of role, so Security gets the
        #    same "not found" a household session or a plain Administrator
        #    would, not a role-specific 403 that would imply this is only
        #    sometimes reachable.
        async with SessionFactory() as db:
            owner_session_id = await db.scalar(
                select(PlatformSession.id).where(
                    PlatformSession.administrator_id == owner.id,
                    PlatformSession.revoked_at.is_(None),
                )
            )
        assert owner_session_id is not None
        revoke = await unsafe(
            security_client, "DELETE", f"/api/v1/platform/auth/sessions/{owner_session_id}"
        )
        assert revoke.status_code == 404

        async with SessionFactory() as db:
            still_active = await db.scalar(
                select(PlatformSession.id).where(
                    PlatformSession.id == owner_session_id,
                    PlatformSession.revoked_at.is_(None),
                )
            )
        assert still_active is not None


# ---------------------------------------------------------------------------
# PCC-SEC-007 — rate limiter uses the trusted-proxy-aware client identity
# ---------------------------------------------------------------------------


def test_rate_limiter_resolves_identity_through_the_trusted_proxy_chain() -> None:
    """enforce_rate_limit must key on resolve_client_ip's result (the same
    trusted-proxy-aware resolution used for the admin network allowlist), not
    the raw ASGI socket peer — otherwise two different raw peers that are
    actually the same forwarded client (or vice versa) would get separate
    (or shared) buckets incorrectly."""
    import mykhaya.rate_limit as rate_limit_module

    assert "resolve_client_ip" in rate_limit_module.__dict__
    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    # Two different raw peers behind the same trusted proxy, forwarding the
    # same real client IP, must resolve to the same identity.
    from mykhaya.security import resolve_client_ip

    resolved_one = resolve_client_ip(make_request("10.0.0.5", "203.0.113.50"), settings)
    resolved_two = resolve_client_ip(make_request("10.0.0.9", "203.0.113.50"), settings)
    assert resolved_one == resolved_two == "203.0.113.50"


@pytest.mark.asyncio
async def test_rate_limiter_bucket_is_shared_across_untrusted_raw_peers_behind_one_proxy() -> None:
    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    bucket = f"test-proxy-bucket-{uuid.uuid4()}"
    await enforce_rate_limit(make_request("10.0.0.5", "203.0.113.77"), settings, bucket, 2, 60)
    await enforce_rate_limit(make_request("10.0.0.9", "203.0.113.77"), settings, bucket, 2, 60)
    with pytest.raises(HTTPException) as excinfo:
        await enforce_rate_limit(make_request("10.0.0.1", "203.0.113.77"), settings, bucket, 2, 60)
    assert excinfo.value.status_code == 429


# ---------------------------------------------------------------------------
# PCC-SEC-011 — atomic, single-use WebAuthn challenge consumption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webauthn_challenge_pop_is_atomic_under_concurrency() -> None:
    settings = get_settings()
    session_id = uuid.uuid4()
    await store_webauthn_challenge(settings, "concurrency-test", session_id, b"a-fake-challenge")
    results = await asyncio.gather(
        *[pop_webauthn_challenge(settings, "concurrency-test", session_id) for _ in range(8)]
    )
    successes = [value for value in results if value is not None]
    assert len(successes) == 1
    assert successes[0] == b"a-fake-challenge"


@pytest.mark.asyncio
async def test_webauthn_challenge_pop_is_still_single_use_sequentially() -> None:
    settings = get_settings()
    session_id = uuid.uuid4()
    await store_webauthn_challenge(settings, "sequential-test", session_id, b"another-challenge")
    first = await pop_webauthn_challenge(settings, "sequential-test", session_id)
    second = await pop_webauthn_challenge(settings, "sequential-test", session_id)
    assert first == b"another-challenge"
    assert second is None
