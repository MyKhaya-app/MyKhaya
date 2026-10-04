"""Commercial plan cleanup: Free vs Family capability matrix enforcement for
the two new numeric/boolean entitlements that gained a real endpoint in this
task — home.max_members (invitation creation) and
routines.personal.max_active / routines.household.enabled (routine
creation/update). See docs/architecture/commercial-entitlements.md
"Commercial plan cleanup". Calendar's calendar.max_categories rename and its
full enforcement matrix remain covered by test_calendar_entitlements.py
(only its key string changed, not its behaviour).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import PLAN_DEFINITIONS, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    HouseholdRoutine,
    Membership,
    RoutineScope,
    SubscriptionPlan,
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


async def _make_home(client: AsyncClient, suffix: str) -> uuid.UUID:
    await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Test Home"})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


async def _enable_notifications(home_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        await db.commit()


async def _set_subscription(home_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


async def _member_rows(home_id: uuid.UUID) -> list[Membership]:
    async with SessionFactory() as db:
        return list(
            (await db.scalars(select(Membership).where(Membership.group_id == home_id))).all()
        )


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


def _routine_body(**overrides: object) -> dict:
    anchor = date(2026, 9, 7)
    body = {
        "title": "Water plants",
        "scope": "personal",
        "interval_weeks": 1,
        "week_anchor_date": anchor.isoformat(),
        "reminder_timing": "evening_before",
        "is_critical": False,
        "pinned": False,
        "start_date": anchor.isoformat(),
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# home.max_members — invitation creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_home_cannot_invite_a_second_member(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": f"guest-{_suffix()}@example.com"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "home.max_members"
    assert detail["limit"] == 1


@pytest.mark.asyncio
async def test_family_home_can_invite_members(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": f"guest-{_suffix()}@example.com"},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_downgrade_preserves_existing_members_but_blocks_new_invites(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    for _ in range(2):
        response = await unsafe(
            client,
            "POST",
            "/api/v1/invitations",
            json={"group_id": str(home_id), "email": f"guest-{uuid.uuid4().hex[:10]}@example.com"},
        )
        assert response.status_code == 201

    # Downgrade — nobody is evicted.
    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    members_after = await _member_rows(home_id)
    assert len(members_after) == 1  # only the owner ever accepted; invites don't add members

    blocked = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": f"guest-{uuid.uuid4().hex[:10]}@example.com"},
    )
    assert blocked.status_code == 403


# ---------------------------------------------------------------------------
# routines.personal.max_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_home_cannot_create_any_personal_routines(client: AsyncClient) -> None:
    """Phase 2B: Nudges (Routines + Reminders + To-dos) became Family-only
    (nudges.enabled) — a Free Home is now blocked at that boolean module
    gate before routines.personal.max_active is ever reached, superseding
    the earlier "up to 3 personal routines on Free" rule. See
    docs/architecture/commercial-entitlements.md and
    mykhaya.routers.household_routines' require_feature/require_entitlement
    pair. routines.personal.max_active remains declared in
    PLAN_DEFINITIONS (data only, matching this repo's established pattern
    for a superseded-but-not-deleted key) and its underlying numeric-limit
    mechanism is still exercised directly below, on a Family Home with a
    temporarily narrowed limit — see
    test_disabling_a_personal_routine_frees_up_the_limit and
    test_concurrent_personal_routine_creation_cannot_exceed_the_limit."""
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(title="Routine 1"),
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "nudges.enabled"


@pytest.mark.asyncio
async def test_family_home_personal_routines_are_unlimited(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    for index in range(5):
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/routines",
            json=_routine_body(title=f"Routine {index}"),
        )
        assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_disabling_a_personal_routine_frees_up_the_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """routines.personal.max_active is unreachable in practice now (Free is
    blocked earlier by nudges.enabled; Family is unlimited) — see
    test_free_home_cannot_create_any_personal_routines. This temporarily
    narrows Family's limit to 3, mirroring
    test_concurrent_calendar_creation_cannot_exceed_the_limit's identical
    technique, so the underlying "disabling frees a slot" mechanism (still
    real code) keeps direct coverage."""
    monkeypatch.setitem(
        PLAN_DEFINITIONS,
        SubscriptionPlan.family,
        PLAN_DEFINITIONS[SubscriptionPlan.family].__class__(
            plan=SubscriptionPlan.family,
            booleans=PLAN_DEFINITIONS[SubscriptionPlan.family].booleans,
            limits={
                **PLAN_DEFINITIONS[SubscriptionPlan.family].limits,
                "routines.personal.max_active": 3,
            },
        ),
    )
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created_ids = []
    for index in range(3):
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/routines",
            json=_routine_body(title=f"Routine {index}"),
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    first = next(item for item in listing.json()["items"] if item["id"] == created_ids[0])

    disable = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{created_ids[0]}",
        json=_routine_body(
            title="Routine 0", enabled=False, expected_updated_at=first["updated_at"]
        ),
    )
    assert disable.status_code == 200

    fourth = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/routines", json=_routine_body(title="Routine 4")
    )
    assert fourth.status_code == 201


# ---------------------------------------------------------------------------
# routines.household.enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_home_cannot_create_a_household_routine(client: AsyncClient) -> None:
    """A rejected Household create must never silently fall back to
    persisting the routine as Personal instead — see the live-verification
    investigation in the Routines & Reminders consolidation task, which
    confirmed this rejection path (not a silent scope downgrade) is what
    actually happens here."""
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="household"),
    )
    # Phase 2B: blocked at the earlier, blanket nudges.enabled gate now
    # (Family-only), before the endpoint body ever reaches its own
    # routines.household.enabled check — see
    # test_editing_a_routine_to_household_without_entitlement_is_rejected
    # for direct coverage of that specific, still-real check.
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "nudges.enabled"

    # Confirm nothing was persisted — the whole module is inaccessible, not
    # just silently empty.
    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert listing.status_code == 403


@pytest.mark.asyncio
async def test_family_home_can_create_a_household_routine(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="household"),
    )
    assert response.status_code == 201
    body = response.json()
    # The persisted value, not just the status code — a Household create
    # must round-trip as scope=household with no owner, both in the create
    # response and on a fresh refetch (proves it wasn't just an in-memory
    # response quirk).
    assert body["scope"] == "household"
    assert body["owner_user_id"] is None

    refetched = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    items = refetched.json()["items"]
    assert len(items) == 1
    assert items[0]["scope"] == "household"
    assert items[0]["owner_user_id"] is None


@pytest.mark.asyncio
async def test_family_home_household_routine_visible_to_other_member(
    client: AsyncClient,
) -> None:
    """Household scope must actually mean household-visible, not just
    'not rejected' — a second adult member of the same Home should see it
    too, unlike a Personal routine (see
    test_household_routines.test_list_routines_excludes_other_members_personal_routines
    for the Personal-stays-private side of this contract)."""
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="household", title="Put bins out"),
    )
    assert created.status_code == 201

    invitee_email = f"member-{_suffix()}@example.com"
    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": invitee_email},
    )
    assert invitation.status_code == 201
    raw_invitation = derived_token(
        uuid.UUID(invitation.json()["id"]),
        "invitation",
        get_settings().secret_key.get_secret_value(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as member:
        await create_verified_user(member, invitee_email, "Second Adult")
        accepted = await unsafe(
            member, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
        )
        assert accepted.status_code == 200
        listing = await unsafe(member, "GET", f"/api/v1/homes/{home_id}/routines")
        titles = [item["title"] for item in listing.json()["items"]]
        assert "Put bins out" in titles


@pytest.mark.asyncio
async def test_editing_a_routine_from_personal_to_household_persists(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="personal", title="Water plants"),
    )
    assert created.status_code == 201
    assert created.json()["scope"] == "personal"

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{created.json()['id']}",
        json=_routine_body(
            scope="household",
            title="Water plants",
            expected_updated_at=created.json()["updated_at"],
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["scope"] == "household"
    assert updated.json()["owner_user_id"] is None

    refetched = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert refetched.json()["items"][0]["scope"] == "household"


@pytest.mark.asyncio
async def test_editing_a_routine_from_household_to_personal_persists(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="household", title="Put bins out"),
    )
    assert created.status_code == 201
    assert created.json()["scope"] == "household"

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{created.json()['id']}",
        json=_routine_body(
            scope="personal",
            title="Put bins out",
            expected_updated_at=created.json()["updated_at"],
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["scope"] == "personal"
    assert updated.json()["owner_user_id"] is not None

    refetched = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert refetched.json()["items"][0]["scope"] == "personal"


@pytest.mark.asyncio
async def test_editing_a_routine_to_household_without_entitlement_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same silent-downgrade guard as create, but on the edit path — a Home
    without routines.household.enabled must not be able to flip an existing
    Personal routine to Household by PATCH either. routines.household.
    enabled and nudges.enabled are both True together on every real Family
    Home today (and both False together on Free), so this temporarily
    decouples them — Family plus a monkeypatched
    routines.household.enabled=False — to keep this specific, still-real
    check under direct test, the same technique used for
    routines.personal.max_active above."""
    monkeypatch.setitem(
        PLAN_DEFINITIONS,
        SubscriptionPlan.family,
        PLAN_DEFINITIONS[SubscriptionPlan.family].__class__(
            plan=SubscriptionPlan.family,
            booleans={
                **PLAN_DEFINITIONS[SubscriptionPlan.family].booleans,
                "routines.household.enabled": False,
            },
            limits=PLAN_DEFINITIONS[SubscriptionPlan.family].limits,
        ),
    )
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="personal", title="Water plants"),
    )
    assert created.status_code == 201

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{created.json()['id']}",
        json=_routine_body(
            scope="household",
            title="Water plants",
            expected_updated_at=created.json()["updated_at"],
        ),
    )
    assert updated.status_code == 403
    assert updated.json()["detail"]["entitlement"] == "routines.household.enabled"

    refetched = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert refetched.json()["items"][0]["scope"] == "personal"


@pytest.mark.asyncio
async def test_downgrade_preserves_existing_household_routine_and_allows_ordinary_edits(
    client: AsyncClient,
) -> None:
    """Phase 2B: nudges.enabled becoming Family-only means a downgrade to
    Free now denies *all* Nudges API access, not just new household-scope
    commitments — see docs/architecture/commercial-entitlements.md 'Safe
    downgrade principle'. The routine itself is never deleted (verified
    directly against the database, since the ordinary GET is now also
    blocked); re-upgrading restores full access and the same, unmodified
    row, including the "ordinary edit" that downgrade-safety always
    intended to protect."""
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json=_routine_body(scope="household"),
    )
    assert created.status_code == 201
    routine_id = created.json()["id"]

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    # The whole module is denied now — not silently empty.
    denied = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert denied.status_code == 403

    # Never deleted by the downgrade — still there, untouched, in the
    # database.
    async with SessionFactory() as db:
        row = await db.get(HouseholdRoutine, uuid.UUID(routine_id))
        assert row is not None
        assert row.scope == RoutineScope.household

    # Re-upgrading restores full access to the exact same row, and an
    # ordinary edit (still household-scoped) succeeds normally again.
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert listing.status_code == 200
    current = next(item for item in listing.json()["items"] if item["id"] == routine_id)
    edit = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{routine_id}",
        json=_routine_body(
            scope="household", title="Renamed", expected_updated_at=current["updated_at"]
        ),
    )
    assert edit.status_code == 200
    assert edit.json()["title"] == "Renamed"


@pytest.mark.asyncio
async def test_free_home_cannot_edit_any_routine(client: AsyncClient) -> None:
    """Phase 2B: a Free Home cannot even attempt to convert a routine's
    scope — PATCH is blocked at the same blanket nudges.enabled gate as
    POST/GET, before the endpoint ever looks the routine up (a
    non-existent id is enough to prove this — see
    test_editing_a_routine_to_household_without_entitlement_is_rejected for
    the routines.household.enabled-specific check on a Home that *does*
    have Nudges access)."""
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)

    switch = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{uuid.uuid4()}",
        json=_routine_body(scope="household", expected_updated_at="2026-01-01T00:00:00+00:00"),
    )
    assert switch.status_code == 403
    detail = switch.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "nudges.enabled"


# ---------------------------------------------------------------------------
# Race-safe personal-routine creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_personal_routine_creation_cannot_exceed_the_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """routines.personal.max_active is unreachable in practice now (Free is
    blocked earlier by nudges.enabled, Family is unlimited) — see
    test_free_home_cannot_create_any_personal_routines. This temporarily
    narrows Family's limit to 3 (mirroring
    test_concurrent_calendar_creation_cannot_exceed_the_limit's identical
    technique) to create a genuine concurrent race window, so the advisory
    lock protecting this numeric-limit mechanism keeps direct coverage."""
    monkeypatch.setitem(
        PLAN_DEFINITIONS,
        SubscriptionPlan.family,
        PLAN_DEFINITIONS[SubscriptionPlan.family].__class__(
            plan=SubscriptionPlan.family,
            booleans=PLAN_DEFINITIONS[SubscriptionPlan.family].booleans,
            limits={
                **PLAN_DEFINITIONS[SubscriptionPlan.family].limits,
                "routines.personal.max_active": 3,
            },
        ),
    )
    home_id = await _make_home(client, _suffix())
    await _enable_notifications(home_id)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)

    async def attempt(index: int) -> int:
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/routines",
            json=_routine_body(title=f"Racer {index}"),
        )
        return response.status_code

    results = await asyncio.gather(*(attempt(index) for index in range(6)))
    assert results.count(201) == 3, f"expected exactly 3 winners, got {results}"
    assert results.count(403) == 3

    async with SessionFactory() as db:
        total = await db.scalar(
            select(func.count(HouseholdRoutine.id)).where(
                HouseholdRoutine.group_id == home_id,
                HouseholdRoutine.scope == RoutineScope.personal,
                HouseholdRoutine.enabled.is_(True),
            )
        )
        assert total == 3, "the advisory lock must prevent the limit being exceeded"
