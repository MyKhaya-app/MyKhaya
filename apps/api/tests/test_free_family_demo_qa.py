"""Permanent regression coverage for the Free-vs-Family experience, run
against real Free Plan Demo / Family Demo managed fixtures created through
the real PCC API. Deliberately mirrors the FUNCTIONAL QA checklist from the
visual/manual QA task this originated in, rather than being general
entitlement coverage (that already exists in test_entitlements.py,
test_lists.py, test_wishlists.py, etc.) — this file exists to prove the two
managed-demo fixtures themselves exhibit the correct end-to-end behaviour a
real Free or Family Home would, via the real API, not database row counts.

Each test is self-contained: a fresh PlatformAdministrator and a
uniquely-keyed managed-demo Home are created per test (no shared/global
state, no ordering dependency), and both are deleted in fixture teardown via
the real ManagedDemoService/audit-cleanup paths — see admin_factory and
demo_keys below. No real credentials or customer data: passwords are
fixed test-only strings never used outside this file, and every seeded
email uses the mykhaya.app operator-owned domain (see
test_managed_demo_free_demo.py for why — EmailStr rejects the .invalid
convention seed_template's own fixture members use).
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
    ManagedDemoHome,
    PlatformAdministrator,
    PlatformRole,
)
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ORIGIN = "http://localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"
FIXTURE_PASSWORD = "QA fixture password!"


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.4", 44300)),
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
                email=f"qa-operator-{suffix}@example.com",
                display_name="QA Operator",
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


async def create_fixture(
    admin_client: AsyncClient,
    owner: PlatformAdministrator,
    demo_keys: list[str],
    *,
    fixture_type: str,
) -> dict:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    fixture_key = f"qa-{fixture_type.replace('_', '-')}-{suffix}"
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/demo-test-homes",
        json={
            "fixture_key": fixture_key,
            "display_name": (
                "QA Free Plan Demo" if fixture_type == "free_demo" else "QA Family Demo"
            ),
            "fixture_type": fixture_type,
            "email": f"qa-{fixture_type}-{suffix}@demo.mykhaya.app",
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


def _event_body(offset_days: int = 3) -> dict:
    start = datetime.now(UTC) + timedelta(days=offset_days, hours=1)
    end = start + timedelta(hours=1)
    return {
        "title": "QA test event",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "timezone": "Europe/London",
    }


# ---------------------------------------------------------------------------
# FREE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_functional_qa(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_fixture(admin_client, owner, demo_keys, fixture_type="free_demo")
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    # create event -> works on Personal Calendar (calendar_id omitted).
    event = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/events", json=_event_body()
    )
    assert event.status_code == 201, event.text
    calendars = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/calendars")
    personal_id = calendars.json()["personal_calendar"]["id"]
    assert event.json()["calendar_id"] == personal_id

    # create third List -> blocked correctly.
    third_list = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Third list"}
    )
    assert third_list.status_code == 403
    assert third_list.json()["detail"]["code"] == "plan_limit_reached"

    # Lists remain usable: create/edit/delete an item in an entitled list.
    lists = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/lists")
    list_id = lists.json()["items"][0]["id"]
    add_item = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "QA item"},
    )
    assert add_item.status_code == 201, add_item.text
    item_id = next(i["id"] for i in add_item.json()["items"] if i["text"] == "QA item")
    edit_item = await unsafe(
        household_client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/{item_id}",
        json={"is_checked": True},
    )
    assert edit_item.status_code == 200, edit_item.text
    delete_item = await unsafe(
        household_client,
        "DELETE",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/{item_id}",
    )
    assert delete_item.status_code in (200, 204), delete_item.text

    # direct /wish-lists -> blocked by plan (both create and list).
    wishlist_create = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "QA wishlist", "occasion": "birthday"},
    )
    assert wishlist_create.status_code == 403
    assert wishlist_create.json()["detail"]["code"] == "plan_feature_unavailable"
    wishlist_list = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/wishlists")
    assert wishlist_list.status_code == 403  # fails closed, never an empty-list leak

    # direct /meal-plans -> blocked by plan.
    meal_create = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/meals", json={"name": "QA meal"}
    )
    assert meal_create.status_code == 403
    assert meal_create.json()["detail"]["code"] == "plan_feature_unavailable"
    meal_list = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/meals")
    assert meal_list.status_code == 403

    # direct /settings/routines-reminders -> blocked by plan.
    routine_create = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "QA routine",
            "scope": "personal",
            "week_anchor_date": datetime.now(UTC).date().isoformat(),
            "start_date": datetime.now(UTC).date().isoformat(),
        },
    )
    assert routine_create.status_code == 403
    assert routine_create.json()["detail"]["code"] == "plan_feature_unavailable"
    routine_list = await unsafe(household_client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert routine_list.status_code == 403

    # second-member path blocked by limit.
    invite = await unsafe(
        household_client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": "second-member@demo.mykhaya.app"},
    )
    assert invite.status_code == 403
    assert invite.json()["detail"]["code"] == "plan_limit_reached"
    assert invite.json()["detail"]["entitlement"] == "home.max_members"


# ---------------------------------------------------------------------------
# FAMILY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_functional_qa(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    demo_keys: list[str],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await create_fixture(admin_client, owner, demo_keys, fixture_type="demo")
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    # create event -> works.
    event = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/events", json=_event_body()
    )
    assert event.status_code == 201, event.text

    # create third+ List -> works (Family Demo already seeds 3; a 4th should
    # still succeed, unlimited).
    fourth_list = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "QA extra list"}
    )
    assert fourth_list.status_code == 201, fourth_list.text

    # Nudges -> works.
    routine = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "QA routine",
            "scope": "household",
            "week_anchor_date": datetime.now(UTC).date().isoformat(),
            "start_date": datetime.now(UTC).date().isoformat(),
        },
    )
    assert routine.status_code == 201, routine.text

    # Meal Plans -> works.
    meal = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/meals", json={"name": "QA meal"}
    )
    assert meal.status_code == 201, meal.text

    # Wishlists -> works.
    wishlist = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "QA wishlist", "occasion": "birthday"},
    )
    assert wishlist.status_code == 201, wishlist.text

    # multiple-member features remain available: inviting another member is
    # not blocked by a member-count limit (Family Demo already has 3
    # members; unlimited on Family).
    invite = await unsafe(
        household_client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": "qa-fourth-member@demo.mykhaya.app"},
    )
    assert invite.status_code == 201, invite.text
