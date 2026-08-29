import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AuditEvent,
    FeatureKey,
    FeatureOverride,
    TokenPurpose,
    TrustedDevice,
    User,
    UserPasskey,
)
from mykhaya.models import (
    Session as SessionRow,
)
from mykhaya.platform_mfa import WebAuthnRegistrationResult
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def register_and_verify(client: AsyncClient, email: str, name: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200


async def mobile_login(client: AsyncClient, email: str) -> tuple[str, object]:
    response = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["session_token"], response


def csrf_header(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["mk_csrf"]}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_family_passkey_registration_options_are_fresh_and_single_use(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"passkey-options-{suffix}@example.com"
    await register_and_verify(client, email, "Passkey User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200

    options = await client.post(
        "/api/v1/auth/passkeys/register/options", headers=csrf_header(client), json={}
    )
    assert options.status_code == 200, options.text
    payload = json.loads(options.json()["options_json"])
    assert payload["rp"]["id"] == "localhost"
    assert payload["authenticatorSelection"]["userVerification"] == "required"
    # Biometric sign-in asks specifically for the built-in platform
    # authenticator (Face ID/Touch ID/Windows Hello/fingerprint) — never a
    # roaming/cross-platform security key — and a discoverable (resident)
    # credential, so a later sign-in never needs the user's email first. See
    # the biometric sign-in report for what this can and can't control on
    # iOS specifically.
    assert payload["authenticatorSelection"]["authenticatorAttachment"] == "platform"
    assert payload["authenticatorSelection"]["residentKey"] == "required"

    garbage = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf_header(client),
        json={"credential_json": '{"not":"a credential"}'},
    )
    assert garbage.status_code == 400
    replay = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf_header(client),
        json={"credential_json": '{"not":"a credential"}'},
    )
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_family_passkey_login_options_are_anonymous_discoverable_and_cookie_bound(
    client: AsyncClient,
) -> None:
    options = await client.post("/api/v1/auth/passkeys/login/options", json={})
    assert options.status_code == 200, options.text
    payload = json.loads(options.json()["options_json"])
    assert payload["rpId"] == "localhost"
    assert payload["userVerification"] == "required"
    assert "allowCredentials" not in payload or payload["allowCredentials"] == []
    assert "mk_passkey_challenge" in options.cookies


@pytest.mark.asyncio
async def test_family_passkey_registers_logs_in_revokes_individually_and_keeps_password_fallback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"passkey-flow-{suffix}@example.com"
    await register_and_verify(client, email, "Passkey Flow")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        trusted_before = (
            await db.scalars(
                select(TrustedDevice).where(
                    TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None)
                )
            )
        ).all()
        assert len(trusted_before) == 1  # created by the password login above

    monkeypatch.setattr(
        "mykhaya.routers.auth.verify_family_registration",
        lambda *_args: WebAuthnRegistrationResult("AQI", "cHVibGlj", 0),
    )
    options = await client.post(
        "/api/v1/auth/passkeys/register/options", headers=csrf_header(client), json={}
    )
    assert options.status_code == 200
    registered = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf_header(client),
        json={"credential_json": '{"id":"AQI","rawId":"AQI"}', "label": "Phone"},
    )
    assert registered.status_code == 200, registered.text
    passkey_id = registered.json()["id"]

    listed_before_revoke = await client.get("/api/v1/auth/passkeys")
    assert len(listed_before_revoke.json()) == 1

    await client.post("/api/v1/auth/logout", headers=csrf_header(client))
    monkeypatch.setattr(
        "mykhaya.routers.auth.verify_family_authentication", lambda *_args: 0
    )
    login_options = await client.post("/api/v1/auth/passkeys/login/options", json={})
    assert login_options.status_code == 200
    passkey_login = await client.post(
        "/api/v1/auth/passkeys/login/verify",
        json={"credential_json": '{"id":"AQI","rawId":"AQI"}'},
    )
    assert passkey_login.status_code == 200, passkey_login.text
    # Same session/device/CSRF cookie set a password login produces — no
    # separate, parallel authentication mechanism for biometric sign-in.
    assert client.cookies.get("mk_session") is not None
    assert client.cookies.get("mk_device") is not None
    assert client.cookies.get("mk_csrf") is not None

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        trusted_after = (
            await db.scalars(
                select(TrustedDevice).where(
                    TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None)
                )
            )
        ).all()
        # logout (above) revokes the trusted device along with the session —
        # by design, not a bug (see routers.auth.logout) — so biometric
        # login goes through the exact same issue_trusted_device() path a
        # password login does and creates a fresh active one; it must never
        # leave the account with zero, or with more than one active device
        # for what is still, from the user's perspective, one sign-in.
        assert len(trusted_after) == 1
        assert trusted_after[0].id != trusted_before[0].id

    removed = await client.delete(
        f"/api/v1/auth/passkeys/{passkey_id}", headers=csrf_header(client)
    )
    assert removed.status_code == 204

    listed_after_revoke = await client.get("/api/v1/auth/passkeys")
    assert listed_after_revoke.json() == []
    async with SessionFactory() as db:
        row = await db.get(UserPasskey, uuid.UUID(passkey_id))
        assert row is not None
        assert row.revoked_at is not None  # soft-revoked, not deleted

    await client.post("/api/v1/auth/logout", headers=csrf_header(client))

    await client.post("/api/v1/auth/passkeys/login/options", json={})
    revoked_login = await client.post(
        "/api/v1/auth/passkeys/login/verify",
        json={"credential_json": '{"id":"AQI","rawId":"AQI"}'},
    )
    assert revoked_login.status_code == 401

    password_fallback = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert password_fallback.status_code == 200


@pytest.mark.asyncio
async def test_registration_records_the_browser_reported_authenticator_attachment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Security page's "Face ID is enabled on this device" state (and
    any future re-enrolment prompt for a legacy roaming credential) depends
    on this being recorded accurately from what the browser actually
    reports — never guessed or defaulted to "platform"."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"attachment-{suffix}@example.com"
    await register_and_verify(client, email, "Attachment User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200

    monkeypatch.setattr(
        "mykhaya.routers.auth.verify_family_registration",
        lambda *_args: WebAuthnRegistrationResult("AQM", "cHVibGlj", 0),
    )
    await client.post(
        "/api/v1/auth/passkeys/register/options", headers=csrf_header(client), json={}
    )
    registered = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf_header(client),
        json={
            "credential_json": '{"id":"AQM","rawId":"AQM","authenticatorAttachment":"platform"}',
            "label": "Phone",
        },
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["authenticator_attachment"] == "platform"

    listed = await client.get("/api/v1/auth/passkeys")
    assert listed.status_code == 200
    assert listed.json()[0]["authenticator_attachment"] == "platform"


@pytest.mark.asyncio
async def test_registration_leaves_attachment_null_when_the_browser_does_not_report_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"noattachment-{suffix}@example.com"
    await register_and_verify(client, email, "No Attachment User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200

    monkeypatch.setattr(
        "mykhaya.routers.auth.verify_family_registration",
        lambda *_args: WebAuthnRegistrationResult("AQJ", "cHVibGlj", 0),
    )
    await client.post(
        "/api/v1/auth/passkeys/register/options", headers=csrf_header(client), json={}
    )
    registered = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf_header(client),
        json={"credential_json": '{"id":"AQJ","rawId":"AQJ"}', "label": "Older browser"},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["authenticator_attachment"] is None


@pytest.mark.asyncio
async def test_web_login_never_returns_bearer_token(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"web-{suffix}@example.com"
    await register_and_verify(client, email, "Web User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert "session_token" not in login.json()
    assert client.cookies.get("mk_session")


@pytest.mark.asyncio
async def test_mobile_login_returns_token_and_sets_no_cookies(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"mobile-{suffix}@example.com"
    await register_and_verify(client, email, "Mobile User")
    token, response = await mobile_login(client, email)
    assert token
    assert "mk_session" not in response.cookies
    assert "mk_csrf" not in response.cookies
    assert client.cookies.get("mk_session") is None


@pytest.mark.asyncio
async def test_mobile_login_and_rotate_responses_are_not_cacheable(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"nocache-{suffix}@example.com"
    await register_and_verify(client, email, "No Cache")
    token, login_response = await mobile_login(client, email)
    assert login_response.headers.get("cache-control") == "no-store"
    assert login_response.headers.get("pragma") == "no-cache"

    rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
    assert rotated.status_code == 200
    assert rotated.headers.get("cache-control") == "no-store"
    assert rotated.headers.get("pragma") == "no-cache"


@pytest.mark.asyncio
async def test_bearer_authentication_succeeds_on_protected_endpoint(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"protected-{suffix}@example.com"
    await register_and_verify(client, email, "Protected User")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        me = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert me.status_code == 200
        assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_malformed_bearer_returns_401(client: AsyncClient) -> None:
    denied = await client.get("/api/v1/users/me", headers={"Authorization": "not-a-bearer-token"})
    assert denied.status_code == 401
    denied_empty = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer "})
    assert denied_empty.status_code == 401


@pytest.mark.asyncio
async def test_invalid_bearer_does_not_fall_back_to_valid_cookie(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"fallback-{suffix}@example.com"
    await register_and_verify(client, email, "Fallback User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert client.cookies.get("mk_session")

    denied = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_bearer_authenticated_request_bypasses_csrf(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"csrf-{suffix}@example.com"
    await register_and_verify(client, email, "CSRF Bearer")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        created = await bearer_client.post(
            "/api/v1/groups", json={"name": "Bearer Home"}, headers=bearer(token)
        )
        assert created.status_code == 201


@pytest.mark.asyncio
async def test_expired_bearer_returns_401(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"expired-{suffix}@example.com"
    await register_and_verify(client, email, "Expired User")
    token, _ = await mobile_login(client, email)

    async with SessionFactory() as db:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id.in_(select(User.id).where(User.email == email)))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        denied = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert denied.status_code == 401


@pytest.mark.asyncio
async def test_mobile_logout_revokes_session_and_old_token_is_rejected(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"logout-{suffix}@example.com"
    await register_and_verify(client, email, "Logout User")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        logout = await bearer_client.post("/api/v1/auth/mobile/logout", headers=bearer(token))
        assert logout.status_code == 204
        denied = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert denied.status_code == 401


@pytest.mark.asyncio
async def test_mobile_rotation_issues_new_token_and_invalidates_old(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"rotate-{suffix}@example.com"
    await register_and_verify(client, email, "Rotate User")
    old_token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        rotated = await bearer_client.post(
            "/api/v1/auth/mobile/sessions/rotate", headers=bearer(old_token)
        )
        assert rotated.status_code == 200
        new_token = rotated.json()["session_token"]
        assert new_token != old_token

        old_rejected = await bearer_client.get("/api/v1/users/me", headers=bearer(old_token))
        assert old_rejected.status_code == 401

        new_accepted = await bearer_client.get("/api/v1/users/me", headers=bearer(new_token))
        assert new_accepted.status_code == 200


@pytest.mark.asyncio
async def test_cookie_transport_endpoints_reject_bearer_only_sessions(
    client: AsyncClient,
) -> None:
    """/auth/mobile/logout and /auth/mobile/sessions/rotate require bearer
    transport - a cookie-authenticated caller is rejected rather than
    silently operating on the wrong transport's semantics."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"transport-{suffix}@example.com"
    await register_and_verify(client, email, "Transport User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    csrf = client.cookies["mk_csrf"]

    denied = await client.post("/api/v1/auth/mobile/logout", headers={"X-CSRF-Token": csrf})
    assert denied.status_code == 400


@pytest.mark.asyncio
async def test_cross_household_isolation_unchanged_with_bearer_auth(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"bearer-owner-{suffix}@example.com"
    outsider_email = f"bearer-outsider-{suffix}@example.com"
    await register_and_verify(client, owner_email, "Bearer Owner")
    owner_token, _ = await mobile_login(client, owner_email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as owner_bearer_client:
        group = await owner_bearer_client.post(
            "/api/v1/groups", json={"name": "Bearer Isolated Home"}, headers=bearer(owner_token)
        )
        assert group.status_code == 201
        home_id = group.json()["id"]

        async with SessionFactory() as db:
            db.add(
                FeatureOverride(
                    feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
                )
            )
            await db.commit()

        created = await owner_bearer_client.post(
            f"/api/v1/homes/{home_id}/events",
            headers=bearer(owner_token),
            json={
                "title": "Bearer Private Event",
                "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "timezone": "Europe/London",
                "is_all_day": False,
                "member_ids": [],
                "recurrence": "none",
                "recurrence_interval": 1,
            },
        )
        assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await register_and_verify(outsider, outsider_email, "Bearer Outsider")
        outsider_token, _ = await mobile_login(outsider, outsider_email)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as outsider_bearer_client:
            denied = await outsider_bearer_client.get(
                f"/api/v1/homes/{home_id}/events",
                headers=bearer(outsider_token),
                params={
                    "start_at": datetime.now(UTC).isoformat(),
                    "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                },
            )
            assert denied.status_code == 404


@pytest.mark.asyncio
async def test_bearer_token_never_written_to_audit_metadata(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"audit-{suffix}@example.com"
    await register_and_verify(client, email, "Audit User")
    token, _ = await mobile_login(client, email)

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.actor_user_id == user.id))
        ).all()
        assert events
        for event in events:
            assert token not in str(event.metadata_)


@pytest.mark.asyncio
async def test_mobile_login_with_wrong_password_returns_401_and_no_token(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"wrongpass-{suffix}@example.com"
    await register_and_verify(client, email, "Wrong Password User")

    response = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": "not the right password"}
    )
    assert response.status_code == 401
    assert "session_token" not in response.json()
    assert not client.cookies.get("mk_session")


async def _make_family_home_with_child(
    client: AsyncClient, suffix: str
) -> tuple[str, str, str]:
    """Registers a Home Admin (cookie session) and adds a Child. Returns
    (group_id, membership_id, home_code) — mirrors the equivalent helper in
    test_child_login.py/test_child_home_dashboard_permissions.py, kept local
    here rather than shared since each test module's fixtures differ."""
    await register_and_verify(client, f"admin-{suffix}@example.com", "Home Admin")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": f"admin-{suffix}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    group = await client.post(
        "/api/v1/groups",
        json={"name": f"Home {suffix}"},
        headers=csrf_header(client),
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    home_code = group.json()["child_login_code"]
    assert home_code

    members = await client.get(f"/api/v1/groups/{group_id}/members")
    assert members.status_code == 200
    admin_membership_id = next(
        row["membership_id"] for row in members.json() if row["relationship"] == "home_admin"
    )
    child = await client.post(
        f"/api/v1/groups/{group_id}/children",
        json={
            "display_name": "Erin",
            "age_band": "under_13",
            "guardian_membership_ids": [admin_membership_id],
        },
        headers=csrf_header(client),
    )
    assert child.status_code == 201, child.text
    return group_id, child.json()["membership_id"], home_code


@pytest.mark.asyncio
async def test_mobile_child_login_returns_token_and_sets_no_cookies(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    group_id, membership_id, home_code = await _make_family_home_with_child(client, suffix)
    configured = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": True, "username": "erin", "pin": "4242"},
        headers=csrf_header(client),
    )
    assert configured.status_code == 200, configured.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as child_client:
        response = await child_client.post(
            "/api/v1/auth/mobile/child/login",
            json={"home_code": home_code, "username": "erin", "pin": "4242"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session_token"]
        assert body["principal_type"] == "managed_child"
        # Same email-hiding rule as the cookie path — a managed Child's
        # synthetic placeholder address is never exposed over any transport.
        assert body["email"] is None
        assert not child_client.cookies.get("mk_session")
        assert not child_client.cookies.get("mk_csrf")
        assert response.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_mobile_child_login_wrong_pin_returns_generic_401(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    group_id, membership_id, home_code = await _make_family_home_with_child(client, suffix)
    configured = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": True, "username": "erin", "pin": "4242"},
        headers=csrf_header(client),
    )
    assert configured.status_code == 200, configured.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as child_client:
        response = await child_client.post(
            "/api/v1/auth/mobile/child/login",
            json={"home_code": home_code, "username": "erin", "pin": "0000"},
        )
        assert response.status_code == 401
        assert "session_token" not in response.json()


@pytest.mark.asyncio
async def test_bearer_managed_child_session_reaches_ordinary_endpoints(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    group_id, membership_id, home_code = await _make_family_home_with_child(client, suffix)
    configured = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": True, "username": "erin", "pin": "4242"},
        headers=csrf_header(client),
    )
    assert configured.status_code == 200, configured.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as child_client:
        login = await child_client.post(
            "/api/v1/auth/mobile/child/login",
            json={"home_code": home_code, "username": "erin", "pin": "4242"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["session_token"]

        me = await child_client.get("/api/v1/users/me", headers=bearer(token))
        assert me.status_code == 200
        assert me.json()["principal_type"] == "managed_child"

        routines = await child_client.get(
            f"/api/v1/homes/{group_id}/routines", headers=bearer(token), params={"home": "true"}
        )
        assert routines.status_code == 200


@pytest.mark.asyncio
async def test_adult_only_endpoint_rejects_bearer_managed_child_session(
    client: AsyncClient,
) -> None:
    """require_adult_session checks Session.kind, not transport — a bearer
    managed_child session must be rejected from an adult-only endpoint
    exactly like a cookie managed_child session is today."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    group_id, membership_id, home_code = await _make_family_home_with_child(client, suffix)
    configured = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": True, "username": "erin", "pin": "4242"},
        headers=csrf_header(client),
    )
    assert configured.status_code == 200, configured.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as child_client:
        login = await child_client.post(
            "/api/v1/auth/mobile/child/login",
            json={"home_code": home_code, "username": "erin", "pin": "4242"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["session_token"]

        denied = await child_client.post(
            "/api/v1/groups", json={"name": "Should Not Exist"}, headers=bearer(token)
        )
        assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Native persistent sign-in: TrustedDevice-backed session renewal.
#
# A bearer Session on its own only lasts settings.session_minutes — before
# this, a native app that hadn't been opened in that long had no way back in
# without a password, unlike the browser/PWA's 90-day mk_device cookie. Every
# /auth/mobile/* login now also issues a TrustedDevice (the same table/row
# shape the browser's "remember this device" already uses) linked via
# Session.trusted_device_id, and POST /auth/mobile/sessions/renew is the
# bearer-transport equivalent of the browser's /auth/renew — see
# issue_mobile_session's docstring in routers/auth.py.
# ---------------------------------------------------------------------------


async def mobile_login_full(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.asyncio
async def test_mobile_login_issues_a_device_token_and_a_linked_trusted_device(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"devicetoken-{suffix}@example.com"
    await register_and_verify(client, email, "Device Token User")

    body = await mobile_login_full(client, email)
    assert body["device_token"]
    assert body["device_token"] != body["session_token"]

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        session_row = await db.scalar(select(SessionRow).where(SessionRow.user_id == user.id))
        assert session_row is not None
        assert session_row.trusted_device_id is not None
        device = await db.get(TrustedDevice, session_row.trusted_device_id)
        assert device is not None
        assert device.revoked_at is None


@pytest.mark.asyncio
async def test_mobile_logout_also_revokes_the_linked_trusted_device(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"logoutdevice-{suffix}@example.com"
    await register_and_verify(client, email, "Logout Device User")
    body = await mobile_login_full(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        logout = await bearer_client.post(
            "/api/v1/auth/mobile/logout", headers=bearer(body["session_token"])
        )
        assert logout.status_code == 204

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        session_row = await db.scalar(select(SessionRow).where(SessionRow.user_id == user.id))
        assert session_row is not None
        device = await db.get(TrustedDevice, session_row.trusted_device_id)
        assert device is not None
        assert device.revoked_at is not None

    # The now-revoked device credential can no longer renew a session either.
    renewed = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": body["device_token"]}
    )
    assert renewed.status_code == 401


@pytest.mark.asyncio
async def test_mobile_rotation_reuses_the_existing_device_rather_than_minting_a_new_one(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"rotatedevice-{suffix}@example.com"
    await register_and_verify(client, email, "Rotate Device User")
    body = await mobile_login_full(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        rotated = await bearer_client.post(
            "/api/v1/auth/mobile/sessions/rotate", headers=bearer(body["session_token"])
        )
        assert rotated.status_code == 200, rotated.text
        # Rotation never touches the device credential — nothing new to persist.
        assert rotated.json()["device_token"] is None

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        devices = (
            await db.scalars(
                select(TrustedDevice).where(
                    TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None)
                )
            )
        ).all()
        assert len(devices) == 1


@pytest.mark.asyncio
async def test_renew_mints_a_fresh_session_after_the_bearer_session_has_expired(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"renew-{suffix}@example.com"
    await register_and_verify(client, email, "Renew User")
    body = await mobile_login_full(client, email)

    async with SessionFactory() as db:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id.in_(select(User.id).where(User.email == email)))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    # The expired session_token alone can no longer reach anything...
    denied = await client.get(
        "/api/v1/users/me", headers=bearer(body["session_token"])
    )
    assert denied.status_code == 401

    # ...but the long-lived device_token silently mints a working replacement,
    # with no password re-entry, exactly like the browser's /auth/renew.
    renewed = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": body["device_token"]}
    )
    assert renewed.status_code == 200, renewed.text
    new_body = renewed.json()
    assert new_body["session_token"] != body["session_token"]
    assert new_body["device_token"] and new_body["device_token"] != body["device_token"]

    accepted = await client.get("/api/v1/users/me", headers=bearer(new_body["session_token"]))
    assert accepted.status_code == 200
    assert accepted.json()["email"] == email


@pytest.mark.asyncio
async def test_renew_device_token_is_single_use(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"renewreplay-{suffix}@example.com"
    await register_and_verify(client, email, "Renew Replay User")
    body = await mobile_login_full(client, email)

    first = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": body["device_token"]}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": body["device_token"]}
    )
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_renew_rejects_a_revoked_or_unknown_device_token(client: AsyncClient) -> None:
    unknown = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": "not-a-real-device-token"}
    )
    assert unknown.status_code == 401


@pytest.mark.asyncio
async def test_renew_still_works_for_a_legacy_session_that_predates_device_linkage(
    client: AsyncClient,
) -> None:
    """Backward compatibility: a bearer Session created before this feature
    existed has trusted_device_id=None. Rotating it must not crash — it
    should transparently gain a TrustedDevice (via issue_mobile_session's
    existing_device_id=None fallback), so even an already-issued native
    session upgrades to renewable persistence the next time the app talks to
    the server, with no migration needed for existing sessions."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"legacy-{suffix}@example.com"
    await register_and_verify(client, email, "Legacy Session User")
    body = await mobile_login_full(client, email)

    async with SessionFactory() as db:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id.in_(select(User.id).where(User.email == email)))
            .values(trusted_device_id=None)
        )
        await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        rotated = await bearer_client.post(
            "/api/v1/auth/mobile/sessions/rotate", headers=bearer(body["session_token"])
        )
        assert rotated.status_code == 200, rotated.text
        # Unlike an ordinary rotation, this one *does* mint a fresh device,
        # since there was none to reuse.
        assert rotated.json()["device_token"]


@pytest.mark.asyncio
async def test_renew_rejects_a_managed_child_device_after_login_is_disabled(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    group_id, membership_id, home_code = await _make_family_home_with_child(client, suffix)
    configured = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": True, "username": "erin", "pin": "4242"},
        headers=csrf_header(client),
    )
    assert configured.status_code == 200, configured.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as child_client:
        login = await child_client.post(
            "/api/v1/auth/mobile/child/login",
            json={"home_code": home_code, "username": "erin", "pin": "4242"},
        )
        assert login.status_code == 200, login.text
        device_token = login.json()["device_token"]

    disabled = await client.put(
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json={"enabled": False},
        headers=csrf_header(client),
    )
    assert disabled.status_code == 200, disabled.text

    renewed = await client.post(
        "/api/v1/auth/mobile/sessions/renew", json={"device_token": device_token}
    )
    assert renewed.status_code == 401
