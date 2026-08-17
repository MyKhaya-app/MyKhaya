"""Phase 6: calendar.max_categories enforced against a real endpoint for the
first time — see docs/architecture/commercial-entitlements.md
"Calendar as proof of architecture". Covers: Free's one-calendar limit,
Family's unlimited calendars, race-safe creation, safe downgrade (no data
deleted, deterministic retained calendar, excess calendars read-only),
re-upgrade restoring full access, every commercial-state variant behaving
by *effective* plan rather than raw provider/status, feature-flag/permission
separation, and the structured commercial-restriction error shape.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import PLAN_DEFINITIONS, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def create_verified_user(client: AsyncClient, email: str, name: str) -> User:
    response = await unsafe(
        client,
        "POST",
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
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user


async def _home_with_calendar(client: AsyncClient, name: str) -> str:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
            )
        )
        await db.commit()
    return home_id


async def _set_subscription(home_id: str, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


async def _add_member(home_id: str, user_id: uuid.UUID, profile: PermissionProfile) -> None:
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=uuid.UUID(home_id),
                user_id=user_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=profile,
            )
        )
        await db.commit()


async def _calendar_rows(home_id: str) -> list[HomeCalendar]:
    # Shared/Home calendars only — the resource this test file's
    # calendar.max_categories assertions are about. Every Home now also
    # carries its creating owner's Personal Calendar (owner_user_id set),
    # which is a separate, never-entitlement-gated resource — see
    # test_personal_calendar.py for that behaviour.
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(HomeCalendar)
                    .where(
                        HomeCalendar.group_id == uuid.UUID(home_id),
                        HomeCalendar.owner_user_id.is_(None),
                    )
                    .order_by(HomeCalendar.created_at.asc())
                )
            ).all()
        )


def _event_body(**overrides: object) -> dict:
    body = {
        "title": "Family dinner",
        "start_at": "2026-09-01T18:00:00Z",
        "end_at": "2026-09-01T19:00:00Z",
        "timezone": "Europe/London",
        "is_all_day": False,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Free: one calendar, fully usable, second blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_home_has_exactly_one_calendar_and_it_is_fully_usable(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"free-{suffix}@example.com", "Free Owner")
    home_id = await _home_with_calendar(client, "Free Home")

    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")
    assert listing.status_code == 200
    body = listing.json()
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["is_primary"] is True
    assert body["items"][0]["commercial_access"] == "normal"

    event = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/events", json=_event_body())
    assert event.status_code == 201


@pytest.mark.asyncio
async def test_free_home_second_calendar_is_blocked_with_a_structured_error(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"freeblock-{suffix}@example.com", "Free Owner")
    home_id = await _home_with_calendar(client, "Free Limit Home")

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendars",
        json={"name": "Second calendar"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "calendar.max_categories"
    assert detail["limit"] == 1
    # Never leaks provider/subscription internals.
    assert "stripe" not in str(detail).lower()
    assert "complimentary" not in str(detail).lower()


@pytest.mark.asyncio
async def test_free_home_owner_can_recolour_the_home_calendar_without_touching_entitlement(
    client: AsyncClient,
) -> None:
    """Recolouring the existing (only) Home calendar is a mutation on that
    one row, not the creation of a new calendar/category — it must succeed
    on Free and must never be mistaken for consuming
    calendar.max_categories. See routers.calendar.update_calendar."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"freecolour-{suffix}@example.com", "Free Colour Owner")
    home_id = await _home_with_calendar(client, "Free Colour Home")

    before = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")
    assert before.status_code == 200
    assert before.json()["limit"] == 1
    assert len(before.json()["items"]) == 1
    primary = before.json()["items"][0]
    assert primary["commercial_access"] == "normal"

    recoloured = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/calendars/{primary['id']}",
        json={"color": "amber"},
    )
    assert recoloured.status_code == 200, recoloured.text
    assert recoloured.json()["color"] == "amber"
    assert recoloured.json()["commercial_access"] == "normal"

    # Still exactly one calendar, same limit — a colour change never creates
    # a new calendar/category or otherwise moves the entitlement count.
    after = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")
    assert after.status_code == 200
    assert after.json()["limit"] == 1
    assert len(after.json()["items"]) == 1
    assert after.json()["items"][0]["id"] == primary["id"]
    assert after.json()["items"][0]["color"] == "amber"

    # The Free one-calendar limit is still enforced exactly as before.
    blocked = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendars",
        json={"name": "Second calendar"},
    )
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "calendar.max_categories"


# ---------------------------------------------------------------------------
# Family: multiple calendars, normal editing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_home_can_create_multiple_calendars(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"family-{suffix}@example.com", "Family Owner")
    home_id = await _home_with_calendar(client, "Family Home")
    await _set_subscription(home_id, plan=SubscriptionPlan.family)

    for name in ("Work", "Kids"):
        response = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": name}
        )
        assert response.status_code == 201
        assert response.json()["commercial_access"] == "normal"

    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")
    assert listing.json()["limit"] is None
    assert len(listing.json()["items"]) == 3
    assert all(item["commercial_access"] == "normal" for item in listing.json()["items"])


# ---------------------------------------------------------------------------
# Downgrade safety: no deletion, deterministic retained calendar, excess
# calendars read-only, re-upgrade restores full access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_downgrade_preserves_all_calendars_and_restricts_the_excess_ones(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"downgrade-{suffix}@example.com", "Downgrade Owner")
    home_id = await _home_with_calendar(client, "Downgrade Home")
    await _set_subscription(home_id, plan=SubscriptionPlan.family)

    calendar_b = (
        await unsafe(client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "B"})
    ).json()
    calendar_c = (
        await unsafe(client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "C"})
    ).json()

    rows_before = await _calendar_rows(home_id)
    assert len(rows_before) == 3

    # Subscription ends -> effective plan resolves Free.
    await _set_subscription(home_id, plan=SubscriptionPlan.free, provider=SubscriptionProvider.free)

    rows_after = await _calendar_rows(home_id)
    assert {row.id for row in rows_after} == {row.id for row in rows_before}, (
        "downgrade must never delete a calendar row"
    )

    listing = (await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")).json()
    access = {item["id"]: item["commercial_access"] for item in listing["items"]}
    primary_id = next(item["id"] for item in listing["items"] if item["is_primary"])
    assert access[primary_id] == "normal"
    assert access[calendar_b["id"]] == "read_only_due_to_plan"
    assert access[calendar_c["id"]] == "read_only_due_to_plan"

    # The retained calendar remains fully usable.
    normal_event = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=primary_id),
    )
    assert normal_event.status_code == 201

    # Creating a new event in an excess calendar is blocked...
    blocked = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=calendar_b["id"]),
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "resource_restricted_by_plan"

    # ...creating a third calendar is blocked...
    blocked_calendar = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "D"}
    )
    assert blocked_calendar.status_code == 403
    assert blocked_calendar.json()["detail"]["code"] == "plan_limit_reached"

    # ...but the customer can still voluntarily delete an excess calendar to
    # reduce usage.
    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/calendars/{calendar_c['id']}",
        json={"confirmed": True},
    )
    assert deleted.status_code == 204
    remaining = await _calendar_rows(home_id)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_reupgrade_restores_full_access_to_preserved_calendars(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"reupgrade-{suffix}@example.com", "Reupgrade Owner")
    home_id = await _home_with_calendar(client, "Reupgrade Home")
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    calendar_b = (
        await unsafe(client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "B"})
    ).json()

    await _set_subscription(home_id, plan=SubscriptionPlan.free, provider=SubscriptionProvider.free)
    still_blocked = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=calendar_b["id"]),
    )
    assert still_blocked.status_code == 403

    # Back to Family — no manual support action, no data restoration job.
    await _set_subscription(home_id, plan=SubscriptionPlan.family)

    listing = (await unsafe(client, "GET", f"/api/v1/homes/{home_id}/calendars")).json()
    assert all(item["commercial_access"] == "normal" for item in listing["items"])

    restored = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=calendar_b["id"]),
    )
    assert restored.status_code == 201


# ---------------------------------------------------------------------------
# Commercial-state matrix: enforcement follows *effective* plan, never raw
# provider/status — no Stripe/Complimentary-specific branching in Calendar.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complimentary_active_behaves_as_family(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"complimentary-{suffix}@example.com", "Comp Owner")
    home_id = await _home_with_calendar(client, "Complimentary Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        complimentary_expires_at=None,
    )
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_complimentary_expired_behaves_as_free_with_data_preserved(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"compexpired-{suffix}@example.com", "Comp Owner")
    home_id = await _home_with_calendar(client, "Expired Complimentary Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        complimentary_expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "plan_limit_reached"


@pytest.mark.asyncio
async def test_stripe_active_behaves_as_family(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"stripeactive-{suffix}@example.com", "Stripe Owner")
    home_id = await _home_with_calendar(client, "Stripe Active Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.active,
    )
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_stripe_past_due_still_behaves_as_family(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"pastdue-{suffix}@example.com", "Past Due Owner")
    home_id = await _home_with_calendar(client, "Past Due Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.past_due,
    )
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_stripe_cancel_at_period_end_still_behaves_as_family(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"cancelling-{suffix}@example.com", "Cancelling Owner")
    home_id = await _home_with_calendar(client, "Cancelling Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.cancel_at_period_end,
    )
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_stripe_ended_becomes_free_with_data_preserved(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"ended-{suffix}@example.com", "Ended Owner")
    home_id = await _home_with_calendar(client, "Ended Home")
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.cancelled,
    )
    rows_before = await _calendar_rows(home_id)
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 403
    rows_after = await _calendar_rows(home_id)
    assert len(rows_after) == len(rows_before)


# ---------------------------------------------------------------------------
# Feature flag vs entitlement vs permission separation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_calendar_feature_blocks_access_even_on_family(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"flagoff-{suffix}@example.com", "Flag Owner")
    home_id = await _home_with_calendar(client, "Flag Off Home")
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    async with SessionFactory() as db:
        override = await db.scalar(
            select(FeatureOverride).where(
                FeatureOverride.group_id == uuid.UUID(home_id),
                FeatureOverride.feature_key == FeatureKey.calendar,
            )
        )
        assert override is not None
        override.enabled = False
        await db.commit()

    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_family_entitlement_does_not_grant_permission_to_an_unauthorised_member(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    home_id = await _home_with_calendar(client, "Permissions Home")
    await _set_subscription(home_id, plan=SubscriptionPlan.family)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as guest_client:
        guest = await create_verified_user(
            guest_client, f"guest-{suffix}@example.com", "Review Guest"
        )
        await _add_member(home_id, guest.id, PermissionProfile.review_required)
        response = await unsafe(
            guest_client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "You do not have permission to perform that action."


@pytest.mark.asyncio
async def test_free_home_admin_still_cannot_exceed_the_limit(client: AsyncClient) -> None:
    """Being Home Admin (full permission) never overrides a commercial
    restriction — permission and entitlement are independently enforced."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"admin-{suffix}@example.com", "Home Admin")
    home_id = await _home_with_calendar(client, "Admin Limit Home")
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Race-safe creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_calendar_creation_cannot_exceed_the_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demonstrates the pg_advisory_xact_lock protection with genuine
    concurrent requests against the real test database — not just a
    sequential count assertion. The Free/Family split only offers limits of
    1 and unlimited, neither of which has an observable race window (Free
    starts already at its limit; Family has none), so this temporarily
    widens Free's limit to 3 to create a real "2 taken, 1 slot, N racing
    requests" window, then restores it."""
    original_limits = PLAN_DEFINITIONS[SubscriptionPlan.free].limits
    monkeypatch.setitem(
        PLAN_DEFINITIONS,
        SubscriptionPlan.free,
        PLAN_DEFINITIONS[SubscriptionPlan.free].__class__(
            plan=SubscriptionPlan.free,
            booleans=PLAN_DEFINITIONS[SubscriptionPlan.free].booleans,
            limits={**original_limits, "calendar.max_categories": 3},
        ),
    )

    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"race-{suffix}@example.com", "Race Owner")
    home_id = await _home_with_calendar(client, "Race Home")
    second = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second"}
    )
    assert second.status_code == 201
    # Two calendars exist now (primary + Second); the limit is 3, so exactly
    # one of the following concurrent requests may succeed.

    async def attempt(name: str) -> int:
        response = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": name}
        )
        return response.status_code

    results = await asyncio.gather(*(attempt(f"Racer {i}") for i in range(5)))
    assert results.count(201) == 1, f"expected exactly one winner, got {results}"
    assert results.count(403) == 4

    rows = await _calendar_rows(home_id)
    assert len(rows) == 3, "the advisory lock must prevent the limit being exceeded"
