"""Phase 2: Platform Control Centre subscription management — the read-only
summary/list/detail endpoints built on top of Phase 1's entitlement service
and complimentary grant/revoke endpoints (covered separately in
test_platform_subscriptions.py). Covers access control, listing/filtering/
pagination, the entitlement viewer, and commercial event history.
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
    PlatformAdministrator,
    PlatformRole,
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
        transport=ASGITransport(app=app, client=("127.0.0.1", 44200)),
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


async def make_household(client: AsyncClient, suffix: str, name: str = "Test Home") -> uuid.UUID:
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
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


async def grant_complimentary(
    admin_client: AsyncClient, home_id: uuid.UUID, expires_at: str | None = None
) -> None:
    payload: dict[str, object] = {
        "complimentary_reason": "Beta tester",
        "confirmed": True,
        "reason": "Approved beta access",
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json=payload,
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_client_cannot_reach_subscription_endpoints() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ADMIN_ORIGIN, headers={"Origin": ADMIN_ORIGIN}
    ) as client:
        summary = await client.get("/api/v1/platform/subscriptions/summary")
        listing = await client.get("/api/v1/platform/subscriptions")
        assert summary.status_code in (401, 403)
        assert listing.status_code in (401, 403)


@pytest.mark.asyncio
async def test_household_user_cannot_reach_subscription_endpoints(
    household_client: AsyncClient,
) -> None:
    await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    response = await household_client.get("/api/v1/platform/subscriptions/summary")
    assert response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_any_support_level_platform_role_can_view_listing_and_summary(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    support = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, support)
    summary = await admin_client.get("/api/v1/platform/subscriptions/summary")
    listing = await admin_client.get("/api/v1/platform/subscriptions")
    assert summary.status_code == 200
    assert listing.status_code == 200


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_counts_reflect_actual_backend_state(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    before = (await admin_client.get("/api/v1/platform/subscriptions/summary")).json()

    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    free_home = await make_household(household_client, f"free-{suffix}")
    complimentary_home = await make_household(household_client, f"comp-{suffix}")
    expired_home = await make_household(household_client, f"expired-{suffix}")

    await grant_complimentary(admin_client, complimentary_home)
    await grant_complimentary(
        admin_client, expired_home, expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat()
    )

    after = (await admin_client.get("/api/v1/platform/subscriptions/summary")).json()
    assert after["total_homes"] == before["total_homes"] + 3
    assert after["free"] == before["free"] + 2  # the plain Free home + the expired one
    assert after["family"] == before["family"] + 1
    assert after["complimentary"] == before["complimentary"] + 2  # provider, regardless of expiry
    assert after["complimentary_expired"] == before["complimentary_expired"] + 1
    assert free_home is not None


def test_summary_has_no_revenue_fields() -> None:
    # Static shape check — documents the contract that no revenue/MRR/ARR
    # figure can appear before a real payment provider exists (Phase 3).
    from mykhaya.platform_schemas import SubscriptionSummaryResponse

    fields = set(SubscriptionSummaryResponse.model_fields)
    assert "revenue" not in fields
    assert "mrr" not in fields
    assert "arr" not in fields


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_shows_free_and_complimentary_homes_with_effective_state(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    free_home = await make_household(household_client, suffix, name=f"Free Home {suffix}")
    listing = await admin_client.get("/api/v1/platform/subscriptions", params={"q": suffix})
    assert listing.status_code == 200
    items = listing.json()["items"]
    match = next(item for item in items if item["id"] == str(free_home))
    assert match["stored_plan"] == "free"
    assert match["effective_plan"] == "free"
    assert match["effective_status_reason"] is None


@pytest.mark.asyncio
async def test_expired_complimentary_home_lists_stored_family_but_effective_free(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await make_household(household_client, suffix, name=f"Expired Home {suffix}")
    await grant_complimentary(
        admin_client, home_id, expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat()
    )
    listing = await admin_client.get("/api/v1/platform/subscriptions", params={"q": suffix})
    match = next(item for item in listing.json()["items"] if item["id"] == str(home_id))
    assert match["stored_plan"] == "family"
    assert match["provider"] == "complimentary"
    assert match["effective_plan"] == "free"
    assert match["effective_status_reason"] == "Complimentary access expired"


@pytest.mark.asyncio
async def test_listing_filters_by_effective_plan_and_provider(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await make_household(household_client, suffix, name=f"Filter Home {suffix}")
    await grant_complimentary(admin_client, home_id)

    by_effective = await admin_client.get(
        "/api/v1/platform/subscriptions", params={"q": suffix, "effective": "family"}
    )
    assert any(item["id"] == str(home_id) for item in by_effective.json()["items"])

    by_wrong_effective = await admin_client.get(
        "/api/v1/platform/subscriptions", params={"q": suffix, "effective": "free"}
    )
    assert not any(item["id"] == str(home_id) for item in by_wrong_effective.json()["items"])

    by_provider = await admin_client.get(
        "/api/v1/platform/subscriptions", params={"q": suffix, "provider": "complimentary"}
    )
    assert any(item["id"] == str(home_id) for item in by_provider.json()["items"])


@pytest.mark.asyncio
async def test_listing_pagination_respects_page_size(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    for i in range(3):
        await make_household(household_client, f"{suffix}-{i}", name=f"Page Home {suffix}-{i}")
    page_one = await admin_client.get(
        "/api/v1/platform/subscriptions", params={"q": suffix, "page": 1, "page_size": 2}
    )
    payload = page_one.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) == 2
    assert payload["total"] == 3


# ---------------------------------------------------------------------------
# Detail / entitlement viewer / history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_resolves_free_entitlements_correctly(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    response = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["entitlements"]["plan"] == "free"
    assert payload["entitlements"]["limits"]["calendar.max_calendars"] == 1
    assert payload["entitlements"]["booleans"]["lists.enabled"] is False
    assert payload["subscription"]["effective_plan"] == "free"
    assert payload["member_count"] >= 1


@pytest.mark.asyncio
async def test_detail_resolves_family_entitlements_correctly(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    await grant_complimentary(admin_client, home_id)
    response = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    payload = response.json()
    assert payload["entitlements"]["plan"] == "family"
    assert payload["entitlements"]["limits"]["calendar.max_calendars"] is None
    assert payload["entitlements"]["booleans"]["lists.enabled"] is True
    assert payload["subscription"]["complimentary_granted_by_display_name"] == "Test Operator"


@pytest.mark.asyncio
async def test_detail_shows_expired_complimentary_as_effective_free_with_reason(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    await grant_complimentary(
        admin_client, home_id, expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat()
    )
    response = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    payload = response.json()
    assert payload["subscription"]["plan"] == "family"
    assert payload["subscription"]["effective_plan"] == "free"
    assert payload["subscription"]["effective_status_reason"] == "Complimentary access expired"
    assert payload["entitlements"]["plan"] == "free"


@pytest.mark.asyncio
async def test_detail_history_records_created_and_granted_events_only_when_they_happened(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    before = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    before_types = {event["event_type"] for event in before.json()["history"]}
    assert before_types == {"created"}
    assert "expired" not in before_types  # never fabricated — expiry is resolved dynamically

    await grant_complimentary(admin_client, home_id)
    after = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    history = after.json()["history"]
    granted = next(event for event in history if event["event_type"] == "complimentary_granted")
    assert granted["to_plan"] == "family"
    assert granted["to_provider"] == "complimentary"
    assert granted["actor_display_name"] == "Test Operator"
    assert granted["reason"] == "Approved beta access"


@pytest.mark.asyncio
async def test_detail_against_unknown_home_is_404(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await admin_client.get(f"/api/v1/platform/subscriptions/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_note_reaches_platform_admin_but_not_household_endpoints(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    home_id = await make_household(household_client, datetime.now(UTC).strftime("%H%M%S%f"))
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={
            "complimentary_reason": "Beta tester",
            "complimentary_note": "Internal-only note about this Home",
            "confirmed": True,
            "reason": "Approved beta access",
        },
    )
    assert response.status_code == 200

    detail = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    note = detail.json()["subscription"]["complimentary_note"]
    assert note == "Internal-only note about this Home"

    household_group = await household_client.get(f"/api/v1/groups/{home_id}")
    assert household_group.status_code == 200
    assert "complimentary_note" not in household_group.text
    assert "Internal-only note" not in household_group.text
