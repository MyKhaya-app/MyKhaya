"""Platform Control Centre endpoints for Phase 1 commercial entitlements:
granting/revoking complimentary Family access, and the subscription block on
GET /platform/homes/{id}. Authorization, IDOR, mass-assignment, audit and
data-safety coverage — service-level resolution logic is covered separately
in test_entitlements.py.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    Group,
    HomeSubscriptionEvent,
    PlatformAdministrator,
    PlatformRole,
    SubscriptionPlan,
    SubscriptionProvider,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token, password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ORIGIN = "http://localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"
USER_PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44100)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def household_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"operator-{suffix}@example.com",
                display_name="Test Operator",
                password_hash=password_hash.hash(ADMIN_PASSWORD),
                role=role,
                mfa_enrolled=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login",
        json={"email": admin.email, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf_cookie_name = "mk_admin_csrf" if "admin" in str(client.base_url) else "mk_csrf"
    csrf = client.cookies.get(csrf_cookie_name)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def make_household(client: AsyncClient, suffix: str) -> uuid.UUID:
    email = f"member-{suffix}@example.com"
    register = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Member", "password": USER_PASSWORD},
    )
    assert register.status_code == 202
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
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": USER_PASSWORD}
    )
    assert login.status_code == 200
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Test Home"})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


@pytest.mark.asyncio
async def test_grant_complimentary_requires_operator_role(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    support = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, support)
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "confirmed": True, "reason": "Beta access"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ordinary_household_user_cannot_reach_platform_subscription_endpoints(
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    response = await unsafe(
        household_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Self-granted", "confirmed": True, "reason": "Nice try"},
    )
    assert response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_household_user_cannot_mass_assign_plan_via_group_update(
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    response = await unsafe(
        household_client,
        "PATCH",
        f"/api/v1/groups/{home_id}",
        json={"name": "Renamed Home", "plan": "family", "provider": "complimentary"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_grant_complimentary_grants_family_access_and_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={
            "complimentary_reason": "Friends and family beta",
            "complimentary_note": "Internal note, never shown to the household",
            "confirmed": True,
            "reason": "Approved beta access",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"] == "family"
    assert payload["provider"] == "complimentary"
    assert payload["effective_plan"] == "family"
    assert payload["complimentary_reason"] == "Friends and family beta"

    detail = await admin_client.get(f"/api/v1/platform/homes/{home_id}")
    assert detail.status_code == 200
    assert detail.json()["subscription"]["plan"] == "family"
    assert detail.json()["subscription"]["provider"] == "complimentary"

    async with SessionFactory() as db:
        audit_event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == owner.id,
                AdministrativeAuditEvent.action == "home.complimentary_granted",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert audit_event is not None
        assert audit_event.reason == "Approved beta access"
        history = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(
                    HomeSubscriptionEvent.group_id == home_id,
                    HomeSubscriptionEvent.event_type == "complimentary_granted",
                )
            )
        ).all()
        assert len(history) == 1
        assert history[0].to_plan == SubscriptionPlan.family
        assert history[0].to_provider == SubscriptionProvider.complimentary


@pytest.mark.asyncio
async def test_grant_complimentary_requires_recent_auth_confirmation(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    unconfirmed = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "reason": "Beta access"},
    )
    assert unconfirmed.status_code == 422


@pytest.mark.asyncio
async def test_grant_complimentary_against_unknown_home_is_404(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{uuid.uuid4()}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "confirmed": True, "reason": "Beta access"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_complimentary_downgrades_to_free_without_deleting_the_home(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    granted = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "confirmed": True, "reason": "Beta access"},
    )
    assert granted.status_code == 200

    revoked = await unsafe(
        admin_client,
        "DELETE",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"confirmed": True, "reason": "Beta programme ended"},
    )
    assert revoked.status_code == 200
    payload = revoked.json()
    assert payload["plan"] == "free"
    assert payload["provider"] == "free"
    assert payload["complimentary_reason"] is None
    assert payload["effective_plan"] == "free"

    async with SessionFactory() as db:
        home = await db.get(Group, home_id)
        assert home is not None
        history = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(
                    HomeSubscriptionEvent.group_id == home_id,
                    HomeSubscriptionEvent.event_type == "downgraded",
                )
            )
        ).all()
        assert len(history) == 1


@pytest.mark.asyncio
async def test_revoke_complimentary_without_existing_complimentary_access_conflicts(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "DELETE",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"confirmed": True, "reason": "Nothing to revoke"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_new_home_defaults_to_free_in_platform_home_detail(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    detail = await admin_client.get(f"/api/v1/platform/homes/{home_id}")
    assert detail.status_code == 200
    subscription = detail.json()["subscription"]
    assert subscription["plan"] == "free"
    assert subscription["provider"] == "free"
    assert subscription["effective_plan"] == "free"


@pytest.mark.asyncio
async def test_complimentary_expiry_in_the_future_can_be_granted(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    expires_at = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={
            "complimentary_reason": "14-day trial extension",
            "expires_at": expires_at,
            "confirmed": True,
            "reason": "Time-limited beta extension",
        },
    )
    assert response.status_code == 200
    assert response.json()["complimentary_expires_at"] is not None
