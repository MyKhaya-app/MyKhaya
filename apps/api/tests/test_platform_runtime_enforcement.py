"""Runtime enforcement of Platform Control Centre settings.

Every setting that gates access, security or availability is exercised in both
its enabled and disabled state against the real API, with the value written the
way PCC writes it (a `platform_settings` row) and *no* application restart or
settings override in between — proving a change takes effect on the next
request. See apps/api/mykhaya/platform_runtime.py for the precedence rules.
"""

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from test_calendar import (  # noqa: F401
    PASSWORD,
    client,
    create_verified_user,
    unsafe,
)
from test_platform_control_centre import (  # noqa: F401
    admin_client,
    admin_factory,
    login,
)
from test_platform_control_centre import unsafe as admin_unsafe

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.founding_beta import FOUNDING_BETA_SLUG, invitation_token_hash
from mykhaya.main import app
from mykhaya.models import (
    BetaInvitation,
    BetaProgramme,
    Invitation,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    SubscriptionPlan,
    User,
)
from mykhaya.security import derived_token

CONTROLLED_KEYS = (
    "maintenance_mode",
    "registration_enabled",
    "invite_only_mode",
    "email_verification_required",
    "allowed_registration_domains",
    "invitation_expiry_days",
    "maximum_homes_per_user",
    "maximum_members_per_home",
)


async def set_setting(key: str, value: Any) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
        if row is None:
            db.add(PlatformSetting(key=key, value={"value": value}))
        else:
            row.value = {"value": value}
        await db.commit()


async def clear_setting(key: str) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(PlatformSetting).where(PlatformSetting.key == key))
        await db.commit()


@pytest.fixture(autouse=True)
async def _isolated_settings() -> AsyncIterator[None]:
    """Start and finish every test with the controlled keys unset and the
    signup_mode row (seeded by migration) put back exactly as found."""
    async with SessionFactory() as db:
        original = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "signup_mode")
        )
        original_value = dict(original.value) if original else None
    for key in CONTROLLED_KEYS:
        await clear_setting(key)
    yield
    for key in CONTROLLED_KEYS:
        await clear_setting(key)
    async with SessionFactory() as db:
        await db.execute(delete(PlatformSetting).where(PlatformSetting.key == "signup_mode"))
        if original_value is not None:
            db.add(PlatformSetting(key="signup_mode", value=original_value))
        await db.commit()


def _email(prefix: str, domain: str = "example.com") -> str:
    return f"{prefix}-{secrets.token_hex(6)}@{domain}"


async def register(client: AsyncClient, email: str, **extra: Any):
    return await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Runtime Test", "password": PASSWORD, **extra},
    )


async def issue_home_invitation(client: AsyncClient) -> tuple[str, str, str]:
    """A signed-in owner on a Family Home invites a fresh address. Returns
    (invitee_email, raw_registration_token, home_id)."""
    await create_verified_user(client, _email("owner"), "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Runtime Home"})
    assert group.status_code == 201, group.text
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    invitee = _email("invitee")
    sent = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": invitee, "role": "adult_member"},
    )
    assert sent.status_code == 201, sent.text
    async with SessionFactory() as db:
        row = await db.scalar(
            select(Invitation).where(
                Invitation.group_id == uuid.UUID(home_id), Invitation.email == invitee
            )
        )
        assert row is not None
        token = derived_token(row.id, "invitation", get_settings().secret_key.get_secret_value())
    return invitee, token, home_id


# ------------------------------------------------------------- maintenance_mode


@pytest.mark.asyncio
async def test_maintenance_mode_off_serves_normal_traffic(client: AsyncClient) -> None:
    # Off (unset): requests reach their handlers and fail on their own merits.
    assert (await client.get("/api/v1/groups")).status_code == 401
    rejected = await unsafe(
        client,
        "POST",
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert rejected.status_code == 401
    assert (await client.get("/api/v1/config/public")).json()["maintenance_mode"] is False


@pytest.mark.asyncio
async def test_maintenance_mode_on_blocks_consumers_but_not_pcc_and_is_live(
    client: AsyncClient,
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    async def put(value: bool):
        return await admin_unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/settings/maintenance_mode",
            json={"value": value, "reason": "Runtime enforcement test.", "confirmed": True},
        )

    assert (await put(True)).status_code == 200

    # Consumer API: HTTP 503 with the structured, retry-able maintenance error.
    for response in (
        await client.get("/api/v1/groups"),
        await client.get("/api/v1/users/me"),
        await unsafe(
            client,
            "POST",
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": PASSWORD},
        ),
        await register(client, _email("blocked")),
        await client.get("/api/v1/public/signup-state"),
    ):
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "maintenance_mode"
        assert response.headers["retry-after"]

    # Still reachable: the surfaces the maintenance screen and operators need.
    public = await client.get("/api/v1/config/public")
    assert public.status_code == 200 and public.json()["maintenance_mode"] is True
    assert (await client.get("/api/v1/health/live")).status_code == 200
    assert (await admin_client.get("/api/v1/platform/settings")).status_code == 200
    platform_signup = await admin_client.get("/api/v1/platform/signup-state")
    assert platform_signup.status_code == 200, platform_signup.text

    # Switching it off in PCC restores service on the very next request.
    assert (await put(False)).status_code == 200
    assert (await client.get("/api/v1/groups")).status_code == 401
    assert (await client.get("/api/v1/config/public")).json()["maintenance_mode"] is False


# ------------------------------------------------------------ registration_enabled


@pytest.mark.asyncio
async def test_registration_enabled_false_rejects_new_accounts_but_not_sign_in(
    client: AsyncClient,
) -> None:
    existing = _email("existing")
    await create_verified_user(client, existing, "Existing")

    await set_setting("registration_enabled", False)
    rejected = await register(client, _email("new"))
    assert rejected.status_code == 403
    assert "closed" in rejected.json()["detail"].lower()

    state = (await client.get("/api/v1/public/signup-state")).json()
    assert state["registration_open"] is False
    assert state["normal_signup_available"] is False
    assert state["beta_joining_available"] is False
    assert state["waitlist_available"] is False

    login_response = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": existing, "password": PASSWORD}
    )
    assert login_response.status_code == 200, login_response.text

    await set_setting("registration_enabled", True)
    assert (await register(client, _email("new"))).status_code == 202
    assert (await client.get("/api/v1/public/signup-state")).json()["registration_open"] is True


@pytest.mark.asyncio
async def test_registration_enabled_false_overrides_every_signup_mode(client: AsyncClient) -> None:
    await set_setting("registration_enabled", False)
    for mode in ("normal", "mixed", "beta_only"):
        await set_setting("signup_mode", mode)
        assert (await register(client, _email("m"))).status_code == 403
        beta = await register(
            client,
            _email("b"),
            beta_home_name="Beta Home",
            beta_terms_version="any",
        )
        assert beta.status_code == 403


@pytest.mark.asyncio
async def test_registration_enabled_false_blocks_beta_join_for_signed_in_users(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, _email("joiner"), "Joiner")
    await set_setting("signup_mode", "mixed")
    await set_setting("registration_enabled", False)
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        terms = programme.terms_version
    response = await unsafe(
        client, "POST", "/api/v1/beta/join", json={"home_name": "Beta Home", "terms_version": terms}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------- signup_mode


@pytest.mark.asyncio
async def test_signup_mode_closed_rejects_ordinary_registration(client: AsyncClient) -> None:
    # Regression: only the deployment-level "closed" used to stop ordinary
    # signup; PCC's own Closed mode left the password path open.
    await set_setting("signup_mode", "closed")
    assert (await register(client, _email("closed"))).status_code == 403
    await set_setting("signup_mode", "normal")
    assert (await register(client, _email("open"))).status_code == 202


@pytest.mark.asyncio
async def test_signup_mode_routes_normal_and_beta_paths(client: AsyncClient) -> None:
    beta = {"beta_home_name": "Beta Home", "beta_terms_version": "x"}
    await set_setting("signup_mode", "beta_only")
    assert (await register(client, _email("n"))).status_code == 403
    await set_setting("signup_mode", "normal")
    assert (await register(client, _email("b"), **beta)).status_code == 403


# ----------------------------------------------------------------- invite_only


@pytest.mark.asyncio
async def test_invite_only_requires_a_valid_home_invitation_server_side(
    client: AsyncClient,
) -> None:
    existing = _email("existing")
    await create_verified_user(client, existing, "Existing")
    invitee, token, _home = await issue_home_invitation(client)

    await set_setting("invite_only_mode", True)
    assert (await register(client, _email("walkin"))).status_code == 403
    forged = derived_token(uuid.uuid4(), "invitation", get_settings().secret_key.get_secret_value())
    assert (await register(client, invitee, invitation_token=forged)).status_code == 403
    # A valid token only works for the address it was issued to.
    assert (await register(client, _email("other"), invitation_token=token)).status_code == 403
    assert (await register(client, invitee, invitation_token=token)).status_code == 202

    # Existing users are unaffected.
    signed_in = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": existing, "password": PASSWORD}
    )
    assert signed_in.status_code == 200

    await set_setting("invite_only_mode", False)
    assert (await register(client, _email("walkin"))).status_code == 202


@pytest.mark.asyncio
async def test_invite_only_beta_path_requires_a_valid_beta_invitation(
    client: AsyncClient,
) -> None:
    await set_setting("signup_mode", "mixed")
    await set_setting("invite_only_mode", True)
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        terms, programme_id = programme.terms_version, programme.id
    beta = {"beta_home_name": "Beta Home", "beta_terms_version": terms}
    invitee = _email("betainvitee")
    raw = secrets.token_urlsafe(40)

    assert (await register(client, invitee, **beta)).status_code == 403
    assert (await register(client, invitee, beta_invitation_token=raw, **beta)).status_code == 403

    async with SessionFactory() as db:
        db.add(
            BetaInvitation(
                programme_id=programme_id,
                email=invitee,
                token_hash=invitation_token_hash(raw),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()
    # Issued to a different address: rejected. To this address: accepted.
    assert (
        await register(client, _email("thief"), beta_invitation_token=raw, **beta)
    ).status_code == 403
    assert (await register(client, invitee, beta_invitation_token=raw, **beta)).status_code == 202

    # An expired reservation is not a valid invitation.
    expired_email, expired_raw = _email("expired"), secrets.token_urlsafe(40)
    async with SessionFactory() as db:
        db.add(
            BetaInvitation(
                programme_id=programme_id,
                email=expired_email,
                token_hash=invitation_token_hash(expired_raw),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db.commit()
    assert (
        await register(client, expired_email, beta_invitation_token=expired_raw, **beta)
    ).status_code == 403


@pytest.mark.asyncio
async def test_invite_only_blocks_uninvited_beta_join_for_signed_in_users(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, _email("joiner"), "Joiner")
    await set_setting("signup_mode", "mixed")
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        terms = programme.terms_version
    await set_setting("invite_only_mode", True)
    response = await unsafe(
        client, "POST", "/api/v1/beta/join", json={"home_name": "Beta Home", "terms_version": terms}
    )
    assert response.status_code == 403
    assert "invitation" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invite_only_is_reported_by_public_signup_state(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/signup-state")).json()["invitation_required"] is False
    await set_setting("invite_only_mode", True)
    assert (await client.get("/api/v1/public/signup-state")).json()["invitation_required"] is True


@pytest.mark.asyncio
async def test_deployment_closed_wins_over_open_pcc_settings(client: AsyncClient) -> None:
    # Precedence: the environment hard limit can only be tightened by PCC.
    await set_setting("registration_enabled", True)
    await set_setting("signup_mode", "normal")
    closed = get_settings().model_copy(update={"registration_mode": "closed"})
    from mykhaya.config import get_settings as dependency

    app.dependency_overrides[dependency] = lambda: closed
    try:
        assert (await register(client, _email("hard"))).status_code == 403
    finally:
        app.dependency_overrides.pop(dependency, None)


# ----------------------------------------------------- allowed_registration_domains


@pytest.mark.asyncio
async def test_allowed_registration_domains_restrict_every_signup(client: AsyncClient) -> None:
    await set_setting("allowed_registration_domains", ["Example.ORG", "@partner.org"])
    denied = await register(client, _email("denied", "example.com"))
    assert denied.status_code == 403
    assert (await register(client, _email("ok", "example.org"))).status_code == 202
    assert (await register(client, _email("ok2", "PARTNER.org"))).status_code == 202
    # Exact domains only — a sub-domain or look-alike is not a match.
    assert (await register(client, _email("sub", "mail.example.org"))).status_code == 403
    assert (await register(client, _email("alike", "example.org.evil.net"))).status_code == 403

    await set_setting("allowed_registration_domains", [])
    assert (await register(client, _email("free", "example.com"))).status_code == 202


@pytest.mark.asyncio
async def test_allowed_registration_domains_apply_to_invited_users_too(
    client: AsyncClient,
) -> None:
    invitee, token, _home = await issue_home_invitation(client)
    await set_setting("allowed_registration_domains", ["example.org"])
    assert (await register(client, invitee, invitation_token=token)).status_code == 403


# ------------------------------------------------------ email_verification_required


@pytest.mark.asyncio
async def test_email_verification_required_is_live_for_registration_and_sign_in(
    client: AsyncClient,
) -> None:
    settings = get_settings()
    assert settings.environment != "production"

    await set_setting("email_verification_required", False)
    relaxed_email = _email("relaxed")
    relaxed = await register(client, relaxed_email)
    assert relaxed.status_code == 202
    assert relaxed.json()["verification_required"] is False
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == relaxed_email))
        assert user is not None and user.email_verified_at is not None

    await set_setting("email_verification_required", True)
    strict_email = _email("strict")
    strict = await register(client, strict_email)
    assert strict.json()["verification_required"] is True
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == strict_email))
        assert user is not None and user.email_verified_at is None
    blocked = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": strict_email, "password": PASSWORD}
    )
    assert blocked.status_code == 403

    # Flipping it back applies to sign-in immediately — no restart.
    await set_setting("email_verification_required", False)
    # (The unverified user is still unverified, but the gate is now off.)
    allowed = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": strict_email, "password": PASSWORD}
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_email_verification_cannot_be_disabled_from_pcc_in_production(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    from mykhaya.config import get_settings as dependency

    production = get_settings().model_copy(
        update={"environment": "production", "email_verification_enabled": True}
    )
    app.dependency_overrides[dependency] = lambda: production
    try:
        response = await admin_unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/settings/email_verification_required",
            json={"value": False, "reason": "Attempt to relax production.", "confirmed": True},
        )
        assert response.status_code == 422
        assert "production" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(dependency, None)


@pytest.mark.asyncio
async def test_a_stored_false_never_relaxes_production_verification() -> None:
    from mykhaya.platform_runtime import email_verification_required

    production = get_settings().model_copy(
        update={"environment": "production", "email_verification_enabled": True}
    )
    await set_setting("email_verification_required", False)
    async with SessionFactory() as db:
        assert await email_verification_required(db, production) is True


# -------------------------------------------------------- invitation_expiry_days


@pytest.mark.asyncio
async def test_invitation_expiry_days_controls_new_and_resent_invitations(
    client: AsyncClient,
) -> None:
    async def expiry_for(home_id: str, email: str) -> timedelta:
        async with SessionFactory() as db:
            row = await db.scalar(
                select(Invitation).where(
                    Invitation.group_id == uuid.UUID(home_id), Invitation.email == email
                )
            )
            assert row is not None
            return row.expires_at - datetime.now(UTC)

    # Default (unset): 7 days.
    invitee, _token, home_id = await issue_home_invitation(client)
    assert timedelta(days=6, hours=23) < await expiry_for(home_id, invitee) <= timedelta(days=7)

    await set_setting("invitation_expiry_days", 2)
    second = _email("second")
    sent = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": second, "role": "adult_member"},
    )
    assert sent.status_code == 201, sent.text
    assert timedelta(days=1, hours=23) < await expiry_for(home_id, second) <= timedelta(days=2)

    # Resend re-applies the *current* setting.
    await set_setting("invitation_expiry_days", 30)
    async with SessionFactory() as db:
        row = await db.scalar(
            select(Invitation).where(
                Invitation.group_id == uuid.UUID(home_id), Invitation.email == second
            )
        )
        assert row is not None
        invitation_id = str(row.id)
    resent = await unsafe(
        client, "POST", "/api/v1/invitations/resend", json={"invitation_id": invitation_id}
    )
    assert resent.status_code == 200, resent.text
    assert timedelta(days=29, hours=23) < await expiry_for(home_id, second) <= timedelta(days=30)


# ------------------------------------------------------------ maximum_homes_per_user


@pytest.mark.asyncio
async def test_maximum_homes_per_user_blocks_creating_another_home(client: AsyncClient) -> None:
    await create_verified_user(client, _email("homes"), "Homes")
    await set_setting("maximum_homes_per_user", 1)
    first = await unsafe(client, "POST", "/api/v1/groups", json={"name": "First"})
    assert first.status_code == 201, first.text
    second = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Second"})
    assert second.status_code == 409
    assert "maximum number of homes" in second.json()["detail"].lower()

    await set_setting("maximum_homes_per_user", 2)
    assert (
        await unsafe(client, "POST", "/api/v1/groups", json={"name": "Second"})
    ).status_code == 201
    await clear_setting("maximum_homes_per_user")
    assert (
        await unsafe(client, "POST", "/api/v1/groups", json={"name": "Third"})
    ).status_code == 201


@pytest.mark.asyncio
async def test_maximum_homes_per_user_blocks_accepting_an_invitation(
    client: AsyncClient,
) -> None:
    invitee, token, home_id = await issue_home_invitation(client)
    # Register the invitee, then sign in as them with a Home of their own.
    assert (await register(client, invitee, invitation_token=token)).status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == invitee))
        assert user is not None
        from mykhaya.models import ActionToken, TokenPurpose

        action = await db.scalar(
            select(ActionToken).where(
                ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email
            )
        )
        assert action is not None
        raw = derived_token(
            action.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    assert (
        await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    ).status_code == 200
    assert (
        await unsafe(
            client, "POST", "/api/v1/auth/login", json={"email": invitee, "password": PASSWORD}
        )
    ).status_code == 200
    assert (
        await unsafe(client, "POST", "/api/v1/groups", json={"name": "Mine"})
    ).status_code == 201

    await set_setting("maximum_homes_per_user", 1)
    refused = await unsafe(client, "POST", "/api/v1/invitations/accept", json={"token": token})
    assert refused.status_code == 409, refused.text

    await set_setting("maximum_homes_per_user", 5)
    accepted = await unsafe(client, "POST", "/api/v1/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    assert home_id


# --------------------------------------------------------- maximum_members_per_home


@pytest.mark.asyncio
async def test_maximum_members_per_home_lowers_but_never_raises_the_plan_limit(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, _email("members"), "Members")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Capped"})
    home_id = group.json()["id"]

    async def invite():
        return await unsafe(
            client,
            "POST",
            "/api/v1/invitations",
            json={"group_id": home_id, "email": _email("guest"), "role": "adult_member"},
        )

    # Free plan: one member already (the owner) — the plan limit blocks invites,
    # and no PCC value can raise it.
    await set_setting("maximum_members_per_home", 50)
    assert (await invite()).status_code == 403

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    # Family: unlimited by plan, so the PCC ceiling is what applies.
    assert (await invite()).status_code == 201
    await set_setting("maximum_members_per_home", 1)
    blocked = await invite()
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "plan_limit_reached"
    await clear_setting("maximum_members_per_home")
    assert (await invite()).status_code == 201


# ------------------------------------------------------------ Apple account creation


class _AppleHarness:
    """Drives apple_callback with the provider exchange stubbed out, so the
    signup-policy gate in front of account creation can be tested for real."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, email: str) -> None:
        from mykhaya.apple_auth import AppleFlowState
        from mykhaya.routers import auth as auth_router

        async def consume(_settings: Any, _state: str) -> AppleFlowState:
            return AppleFlowState(nonce="n", intent="login", user_id=None, return_path=None)

        async def exchange(_settings: Any, _code: str) -> str:
            return "id-token"

        async def verify(_settings: Any, _token: str, _nonce: str) -> dict[str, Any]:
            return {"sub": f"apple-{secrets.token_hex(8)}", "email": email, "email_verified": True}

        monkeypatch.setattr(auth_router, "consume_flow_state", consume)
        monkeypatch.setattr(auth_router, "exchange_code", exchange)
        monkeypatch.setattr(auth_router, "verify_identity_token", verify)

    async def call(self, client: AsyncClient):
        return await client.get("/api/v1/auth/apple/callback", params={"state": "s", "code": "c"})


async def _user_exists(email: str) -> bool:
    async with SessionFactory() as db:
        return await db.scalar(select(User.id).where(User.email == email)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("registration_enabled", False),
        ("invite_only_mode", True),
        ("signup_mode", "closed"),
        ("signup_mode", "beta_only"),
        ("allowed_registration_domains", ["example.org"]),
    ],
)
async def test_apple_sign_up_is_gated_by_the_signup_policy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, setting: str, value: Any
) -> None:
    email = _email("apple")
    harness = _AppleHarness(monkeypatch, email)
    await set_setting(setting, value)
    response = await harness.call(client)
    assert response.status_code == 303
    assert "apple=registration_unavailable" in response.headers["location"]
    assert not await _user_exists(email)


@pytest.mark.asyncio
async def test_apple_sign_up_works_when_signup_is_open(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email("apple-open")
    harness = _AppleHarness(monkeypatch, email)
    await set_setting("signup_mode", "normal")
    response = await harness.call(client)
    assert response.status_code == 303
    assert "registration_unavailable" not in response.headers["location"]
    assert await _user_exists(email)


@pytest.mark.asyncio
async def test_apple_sign_in_for_an_existing_account_ignores_the_signup_policy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email("apple-existing")
    harness = _AppleHarness(monkeypatch, email)
    await set_setting("signup_mode", "normal")
    assert "registration_unavailable" not in (await harness.call(client)).headers["location"]
    # The account now exists. With signup closed, the same email arriving
    # through Apple is handled as an existing account (link required), never
    # as a refused registration.
    await set_setting("registration_enabled", False)
    again = await harness.call(client)
    assert again.status_code == 303
    assert "apple=link_required" in again.headers["location"]


# ------------------------------------------------------------------ PCC contract


@pytest.mark.asyncio
async def test_pcc_reports_every_setting_as_enforced_or_informational(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    rows = (await admin_client.get("/api/v1/platform/settings")).json()["settings"]
    by_key = {row["key"]: row["runtime_effect"] for row in rows}
    # The only settings allowed to be disconnected are the two regional
    # defaults documented in platform-control-centre.md as not safely wireable
    # yet. A new disconnected setting must not slip in unnoticed.
    assert {key for key, effect in by_key.items() if effect == "not_enforced"} == {
        "default_locale",
        "default_timezone",
    }
    for key in CONTROLLED_KEYS:
        assert by_key[key] == "effective", key
