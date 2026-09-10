"""Free Plan Demo managed-demo template ("free_demo"): a single-person Free
Home fixture for manual QA, browser/mobile validation and entitlement
regression — see docs/operations/apple-testflight-review-fixture.md.

Deliberately exercises the real household API/entitlement surface (login as
the fixture owner, call the same endpoints a real Free Home's browser would)
rather than asserting database row counts directly — the fixture inserts
rows directly for deterministic creation, but the product claim under test
is that the resulting Home resolves through the *real* entitlement system
exactly like an organic Free signup would. Apple Review/Family Demo
regression lives alongside this (see the two `*_regression` tests) so a
future change to shared lifecycle code can't silently break either.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.managed_demo_homes import ManagedDemoError, ManagedDemoService
from mykhaya.models import (
    AdministrativeAuditEvent,
    HouseholdRoutine,
    ManagedDemoHome,
    Meal,
    Membership,
    PlatformAdministrator,
    PlatformRole,
    Reminder,
)
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ORIGIN = "http://localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"
FIXTURE_PASSWORD = "Free demo fixture password!"


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.3", 44200)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": "127.0.0.1"},
    ) as value:
        yield value


@pytest.fixture
async def household_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> (
    AsyncIterator[Callable[[PlatformRole], Awaitable[PlatformAdministrator]]]
):
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"free-demo-operator-{suffix}@example.com",
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


@pytest.fixture
async def demo_keys() -> AsyncIterator[list[str]]:
    """Registers fixture_keys created during a test for teardown via the
    real service delete path — never a raw DELETE FROM, so the same safety
    checks (owner has no other memberships, etc.) apply here as in
    production."""
    keys: list[str] = []
    yield keys
    if not keys:
        return
    async with SessionFactory() as db:
        for key in keys:
            row = await db.scalar(select(ManagedDemoHome).where(ManagedDemoHome.fixture_key == key))
            if row is None:
                continue
            try:
                await ManagedDemoService.delete(db, row)
                await db.commit()
            except ManagedDemoError:
                await db.rollback()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login",
        json={"email": admin.email, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))  # type: ignore[arg-type]
    csrf_cookie_name = "mk_admin_csrf" if "admin" in str(client.base_url) else "mk_csrf"
    csrf = client.cookies.get(csrf_cookie_name)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


async def create_free_demo(
    admin_client: AsyncClient,
    owner: PlatformAdministrator,
    demo_keys: list[str],
    *,
    fixture_type: str = "free_demo",
) -> dict:
    suffix = _suffix()
    fixture_key = f"free-demo-test-{suffix}"
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/demo-test-homes",
        json={
            "fixture_key": fixture_key,
            "display_name": "Free Plan Demo",
            "fixture_type": fixture_type,
            # Fictional demo data only. The owner account itself goes
            # through EmailStr validation (which rejects the .invalid TLD
            # used by seed_template's own member fixtures as a reserved/
            # special-use domain) — mykhaya.app is the same operator-owned
            # domain Apple Review's own fixture account already uses.
            "email": f"free-demo-{suffix}@demo.mykhaya.app",
            "password": FIXTURE_PASSWORD,
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    demo_keys.append(fixture_key)
    return response.json()


async def login_as_owner(household_client: AsyncClient, email: str) -> None:
    login = await unsafe(
        household_client,
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": FIXTURE_PASSWORD},
    )
    assert login.status_code == 200, login.text


def _event_window() -> tuple[str, str]:
    now = datetime.now(UTC)
    start = (now - timedelta(days=2)).isoformat()
    end = (now + timedelta(days=10)).isoformat()
    return start, end


@pytest.mark.asyncio
async def test_free_demo_template_can_be_created(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    assert created["fixture_type"] == "free_demo"
    assert created["access"] == "free"  # never the hardcoded "family" default


@pytest.mark.asyncio
async def test_free_demo_resolves_single_member_free_home_with_correct_limits(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    billing = await unsafe(household_client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert billing.status_code == 200, billing.text
    payload = billing.json()

    # Tests 3, 4: effective plan is Free, home.max_members = 1.
    assert payload["stored_plan"] == "free"
    assert payload["effective_plan"] == "free"
    assert payload["member_usage"]["count"] == 1
    assert payload["member_usage"]["limit"] == 1

    # Tests 5, 9: Calendar and Lists are both included on Free.
    assert payload["lists_enabled"] is True

    # Tests 10, 11: exactly two Lists, at the Free lists.max_lists=2 limit.
    assert payload["list_usage"]["count"] == 2
    assert payload["list_usage"]["limit"] == 2
    assert payload["list_usage"]["over_limit"] is False

    # Tests 13, 14, 15, 16: Nudges/Meal Plans/Wishlists/External Sharing are
    # plan-blocked on Free — Nudges is entirely Family-only, never restored
    # to the old "3 personal routines on Free" behaviour.
    assert payload["nudges_enabled"] is False
    assert payload["meals_enabled"] is False
    assert payload["wishlists_enabled"] is False
    assert payload["external_invites_enabled"] is False


@pytest.mark.asyncio
async def test_free_demo_calendar_is_one_writable_personal_calendar_with_personal_events(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    calendars = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/calendars")
    assert calendars.status_code == 200, calendars.text
    payload = calendars.json()

    # Test 6: exactly one Personal Calendar, and it is writable ("normal").
    assert payload["personal_calendar"] is not None
    assert payload["personal_calendar"]["commercial_access"] == "normal"
    assert payload["personal_calendar"]["owner_user_id"] is not None

    # Test 7: the platform's own automatically-provisioned shared "Home
    # Calendar" still exists (never hacked away) but classifies exactly as
    # a real Free Home's would — read_only_due_to_plan, since the Personal
    # Calendar already occupies the Free plan's one calendar.max_calendars
    # slot. No shared/collaborative calendar is usable.
    assert len(payload["items"]) == 1
    assert payload["items"][0]["commercial_access"] == "read_only_due_to_plan"
    assert payload["items"][0]["owner_user_id"] is None

    # Test 8: personal events are present, and they're clearly personal
    # (single attendee — the owner — never a shared/household event).
    start_at, end_at = _event_window()
    events = await unsafe(
        household_client,
        "GET",
        f"/api/v1/homes/{home_id}/events",
        params={"start_at": start_at, "end_at": end_at},
    )
    assert events.status_code == 200, events.text
    items = events.json()["items"]
    assert len(items) == 4
    for occurrence in items:
        assert occurrence["calendar_id"] == payload["personal_calendar"]["id"]
        # Clearly personal — never a shared/household event with multiple
        # attendees.
        assert occurrence["member_ids"] == [created["owner_user_id"]]


@pytest.mark.asyncio
async def test_free_demo_has_exactly_two_lists_and_a_third_is_denied_by_the_real_api(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    lists = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/lists")
    assert lists.status_code == 200, lists.text
    items = lists.json()["items"]
    names = sorted(item["name"] for item in items)
    assert names == ["Groceries", "Weekend jobs"]
    for item in items:
        assert item["item_count"] >= 3

    # Test 12: a third List is denied by the real numeric-limit enforcement,
    # not merely omitted from the fixture — never bypass lists.max_lists.
    third = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/lists",
        json={"name": "Third list"},
    )
    assert third.status_code == 403
    assert third.json()["detail"]["code"] == "plan_limit_reached"


@pytest.mark.asyncio
async def test_free_demo_module_management_reflects_free_state(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    # Test 18/19: the same module_state()-backed source of truth the More
    # menu/Home dashboard already read from resolves this fixture correctly.
    modules = await unsafe(
        household_client, "GET", f"/api/v1/features/{home_id}/modules/management"
    )
    assert modules.status_code == 200, modules.text
    by_id = {row["id"]: row for row in modules.json()}

    assert by_id["shopping"]["entitled"] is True
    assert by_id["shopping"]["enabled"] is True

    for blocked in ("nudges", "meals", "wish_lists"):
        assert by_id[blocked]["entitled"] is False, blocked
        assert by_id[blocked]["enabled"] is False, blocked
        assert by_id[blocked]["blocked_by"] == "plan", blocked


@pytest.mark.asyncio
async def test_free_demo_seeds_no_family_only_fixture_rows(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = uuid.UUID(created["home_id"])

    # Test 2, 17: exactly one Home member, and none of Routines/Reminders/
    # Meals (Meal Plans)/second member/managed child were seeded.
    async with SessionFactory() as db:
        members = (
            await db.scalars(select(Membership.id).where(Membership.group_id == home_id))
        ).all()
        assert len(members) == 1
        routines = (
            await db.scalars(
                select(HouseholdRoutine.id).where(HouseholdRoutine.group_id == home_id)
            )
        ).all()
        assert routines == []
        reminders = (
            await db.scalars(select(Reminder.id).where(Reminder.group_id == home_id))
        ).all()
        assert reminders == []
        meals = (await db.scalars(select(Meal.id).where(Meal.group_id == home_id))).all()
        assert meals == []


@pytest.mark.asyncio
async def test_free_demo_refresh_restores_the_fixture_deterministically(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    home_id = created["home_id"]
    fixture_id = created["id"]

    await login_as_owner(household_client, created["account_email"])

    refreshed = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{fixture_id}/refresh",
        json={"reason": "Deterministic refresh test", "confirmed": True},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access"] == "free"

    lists = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/lists")
    names = sorted(item["name"] for item in lists.json()["items"])
    assert names == ["Groceries", "Weekend jobs"]

    # Same owner identity/password preserved — no re-login needed as a
    # different account.
    billing = await unsafe(household_client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert billing.status_code == 200
    assert billing.json()["stored_plan"] == "free"


@pytest.mark.asyncio
async def test_free_demo_reset_password_enable_disable_expiry_and_delete_work_unchanged(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys)
    fixture_id = created["id"]

    # Test 21: reset password.
    reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{fixture_id}/password",
        json={"password": "Another fixture password!"},
    )
    assert reset.status_code == 204, reset.text

    # Test 22: disable/enable.
    disabled = await unsafe(
        admin_client, "POST", f"/api/v1/platform/demo-test-homes/{fixture_id}/disable"
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    enabled = await unsafe(
        admin_client, "POST", f"/api/v1/platform/demo-test-homes/{fixture_id}/enable"
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "enabled"

    # Test 23: expiry.
    expiry = await unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/demo-test-homes/{fixture_id}/expiry",
        json={"expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    )
    assert expiry.status_code == 200
    assert expiry.json()["expires_at"] is not None

    # Test 24: delete (via the real endpoint this time, not the teardown
    # helper) — remove from demo_keys so the fixture teardown doesn't try
    # to delete it again.
    deleted = await unsafe(
        admin_client,
        "DELETE",
        f"/api/v1/platform/demo-test-homes/{fixture_id}",
        json={"reason": "End of lifecycle test", "confirmed": True},
    )
    assert deleted.status_code == 204, deleted.text
    demo_keys.remove(created["fixture_key"])

    listing = await unsafe(admin_client, "GET", "/api/v1/platform/demo-test-homes")
    assert all(row["id"] != fixture_id for row in listing.json())


@pytest.mark.asyncio
async def test_apple_review_fixture_regression_still_resolves_family_access(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys, fixture_type="apple_review")
    assert created["fixture_type"] == "apple_review"
    assert created["access"] == "family"


@pytest.mark.asyncio
async def test_family_demo_fixture_regression_still_resolves_family_access(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_free_demo(admin_client, owner, demo_keys, fixture_type="demo")
    assert created["fixture_type"] == "demo"
    assert created["access"] == "family"
