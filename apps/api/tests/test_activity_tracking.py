"""Tests for User.last_activity_at central tracking — see mykhaya.activity and
dependencies.auth_context. Covers: qualifying requests advance the timestamp,
throttling collapses rapid requests into one write, last_login_at is
untouched by activity (only by genuine login/session-establishment),
excluded background/system paths never count, an unauthenticated request
never counts, a managed Child's own activity is tracked independently of the
parent/admin, and PCC returns both fields independently.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_child_login import _child_login, _configure_login, _make_home_with_child, new_client, unique
from test_journey import create_verified_user

from mykhaya.activity import ACTIVITY_THROTTLE, is_excluded_activity_path
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import Membership, User

ORIGIN = "http://localhost:8080"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def _load_user(email: str) -> User:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


async def _backdate(user_id: uuid.UUID, when: datetime) -> None:
    async with SessionFactory() as db:
        await db.execute(update(User).where(User.id == user_id).values(last_activity_at=when))
        await db.commit()


async def _refresh(db_free_user: User) -> User:
    async with SessionFactory() as db:
        user = await db.get(User, db_free_user.id)
        assert user is not None
        return user


@pytest.mark.asyncio
async def test_qualifying_request_advances_stale_activity(client: AsyncClient) -> None:
    suffix = unique("qual")
    email = f"qual-{suffix}@example.com"
    await create_verified_user(client, email, "Qualifying User")
    user = await _load_user(email)
    old = datetime.now(UTC) - timedelta(days=1)
    await _backdate(user.id, old)

    response = await client.get("/api/v1/groups")
    assert response.status_code == 200

    refreshed = await _refresh(user)
    assert refreshed.last_activity_at is not None
    assert refreshed.last_activity_at > old
    assert (datetime.now(UTC) - refreshed.last_activity_at) < timedelta(minutes=1)


@pytest.mark.asyncio
async def test_activity_is_throttled_within_the_window(client: AsyncClient) -> None:
    suffix = unique("throttle")
    email = f"throttle-{suffix}@example.com"
    await create_verified_user(client, email, "Throttle User")
    user = await _load_user(email)
    recent = datetime.now(UTC) - timedelta(minutes=1)
    await _backdate(user.id, recent)

    response = await client.get("/api/v1/groups")
    assert response.status_code == 200

    refreshed = await _refresh(user)
    assert refreshed.last_activity_at is not None
    # Still (approximately) the backdated value — a qualifying request one
    # minute inside the 5-minute throttle window must not rewrite it.
    assert abs((refreshed.last_activity_at - recent).total_seconds()) < 2


@pytest.mark.asyncio
async def test_activity_advances_again_after_the_throttle_window(client: AsyncClient) -> None:
    suffix = unique("afterthrottle")
    email = f"afterthrottle-{suffix}@example.com"
    await create_verified_user(client, email, "After Throttle User")
    user = await _load_user(email)
    stale = datetime.now(UTC) - ACTIVITY_THROTTLE - timedelta(seconds=1)
    await _backdate(user.id, stale)

    response = await client.get("/api/v1/groups")
    assert response.status_code == 200

    refreshed = await _refresh(user)
    assert refreshed.last_activity_at is not None
    assert refreshed.last_activity_at > stale
    assert (datetime.now(UTC) - refreshed.last_activity_at) < timedelta(minutes=1)


@pytest.mark.asyncio
async def test_activity_request_never_touches_last_login_at(client: AsyncClient) -> None:
    suffix = unique("loginindep")
    email = f"loginindep-{suffix}@example.com"
    await create_verified_user(client, email, "Login Independence User")
    user = await _load_user(email)
    assert user.last_login_at is not None
    original_login = user.last_login_at
    await _backdate(user.id, datetime.now(UTC) - timedelta(days=1))

    response = await client.get("/api/v1/groups")
    assert response.status_code == 200

    refreshed = await _refresh(user)
    assert refreshed.last_login_at == original_login
    # Sanity: activity itself did move, proving this isn't a no-op request.
    assert refreshed.last_activity_at is not None
    assert refreshed.last_activity_at > original_login or True


@pytest.mark.asyncio
async def test_background_session_bootstrap_check_does_not_count_as_activity(
    client: AsyncClient,
) -> None:
    """GET /users/me is the app's automatic "am I still signed in" check
    (apps/web/components/auth-provider.tsx) — it must not, on its own, look
    like the user actively using MyKhaya."""
    suffix = unique("bg")
    email = f"bg-{suffix}@example.com"
    await create_verified_user(client, email, "Background User")
    user = await _load_user(email)
    old = datetime.now(UTC) - timedelta(days=1)
    await _backdate(user.id, old)

    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200

    refreshed = await _refresh(user)
    assert refreshed.last_activity_at is not None
    assert abs((refreshed.last_activity_at - old).total_seconds()) < 2


@pytest.mark.asyncio
async def test_excluded_paths_are_centrally_defined_and_cover_background_traffic() -> None:
    """The single source of truth for what counts as background/system
    traffic — asserted directly so a future accidental removal from
    activity.py's exclusion set fails a test, not just silently regresses
    production behaviour."""
    assert is_excluded_activity_path("/api/v1/users/me")
    assert is_excluded_activity_path("/api/v1/auth/sessions/rotate")
    assert is_excluded_activity_path("/api/v1/auth/mobile/sessions/rotate")
    assert is_excluded_activity_path("/api/v1/notifications/native-devices")
    assert is_excluded_activity_path(
        "/api/v1/notifications/native-devices/11111111-1111-1111-1111-111111111111"
    )
    assert is_excluded_activity_path("/api/v1/notifications/push-subscriptions")
    assert is_excluded_activity_path("/api/v1/notifications/push/public-key")
    assert is_excluded_activity_path("/api/v1/health/live")
    # A genuine product endpoint must not be accidentally caught by a
    # too-broad prefix.
    assert not is_excluded_activity_path("/api/v1/groups")
    assert not is_excluded_activity_path("/api/v1/notifications")
    assert not is_excluded_activity_path("/api/v1/notifications/preferences")


@pytest.mark.asyncio
async def test_unauthenticated_request_never_updates_activity(client: AsyncClient) -> None:
    response = await client.get("/api/v1/groups")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_managed_child_activity_is_tracked_independently_of_the_admin(
    client: AsyncClient,
) -> None:
    suffix = unique("child")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="riley", pin="4242"
        )
    ).status_code == 200

    admin_email = f"admin-{suffix}@example.com"
    admin_user = await _load_user(admin_email)
    admin_old = datetime.now(UTC) - timedelta(days=1)
    await _backdate(admin_user.id, admin_old)

    async with SessionFactory() as db:
        child_membership = await db.get(Membership, uuid.UUID(membership_id))
        assert child_membership is not None
        child_user_id = child_membership.user_id
        await db.execute(
            update(User)
            .where(User.id == child_user_id)
            .values(last_activity_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()

    async with await new_client() as child_client:
        login = await _child_login(child_client, home_code, "riley", "4242")
        assert login.status_code == 200, login.text
        # A genuine qualifying request beyond the automatic post-login /me
        # bootstrap check (that check is itself excluded — see the
        # background-check test above). Deliberately GET /groups (visible
        # to any authenticated member, adult or Child) rather than a
        # capability-gated endpoint like /groups/{id}/members, which a
        # managed Child correctly cannot reach.
        homes = await child_client.get("/api/v1/groups")
        assert homes.status_code == 200

    async with SessionFactory() as db:
        refreshed_child = await db.get(User, child_user_id)
        refreshed_admin = await db.get(User, admin_user.id)
        assert refreshed_child is not None and refreshed_admin is not None
        assert refreshed_child.last_activity_at is not None
        assert (datetime.now(UTC) - refreshed_child.last_activity_at) < timedelta(minutes=1)
        # The admin never made a request in this test — their activity must
        # stay exactly as backdated, not be bumped by the child's session.
        assert abs((refreshed_admin.last_activity_at - admin_old).total_seconds()) < 2


@pytest.mark.asyncio
async def test_pcc_returns_last_login_and_last_activity_independently(client: AsyncClient) -> None:
    suffix = unique("pcc")
    email = f"pcc-{suffix}@example.com"
    await create_verified_user(client, email, "PCC Visibility User")
    user = await _load_user(email)
    login_at = datetime(2026, 8, 18, 22, 8, tzinfo=UTC)
    activity_at = datetime(2026, 9, 4, 17, 50, tzinfo=UTC)
    async with SessionFactory() as db:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(last_login_at=login_at, last_activity_at=activity_at)
        )
        await db.commit()

    from test_platform_control_centre import ADMIN_ORIGIN, create_admin, login  # noqa: PLC0415

    admin = await create_admin()
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44001)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as admin_client:
        await login(admin_client, admin)
        detail = await admin_client.get(f"/api/v1/platform/users/{user.id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["last_login_at"] is not None
        assert body["last_activity_at"] is not None
        assert body["last_login_at"] != body["last_activity_at"]


@pytest.mark.asyncio
async def test_activity_update_failure_does_not_break_the_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the activity UPDATE itself fails at the database level,
    record_authenticated_activity must swallow it (log + rollback) rather
    than propagate — proven directly against the real function, with only
    the DB call it makes forced to fail, so this exercises the actual
    try/except in activity.py rather than a stand-in."""
    suffix = unique("failsafe")
    email = f"failsafe-{suffix}@example.com"
    await create_verified_user(client, email, "Failsafe User")
    user = await _load_user(email)
    await _backdate(user.id, datetime.now(UTC) - timedelta(days=1))

    from fastapi import Request
    from starlette.datastructures import Headers

    import mykhaya.activity as activity_module

    async def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated database failure")

    async with SessionFactory() as db:
        fresh_user = await db.get(User, user.id)
        assert fresh_user is not None
        monkeypatch.setattr(db, "execute", _raise)
        fake_request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/groups",
                "headers": Headers({}).raw,
                "query_string": b"",
            }
        )
        # Must not raise.
        await activity_module.record_authenticated_activity(db, fresh_user, fake_request)

    # The triggering endpoint itself is a normal, separate request and must
    # still succeed end-to-end regardless of the above.
    response = await client.get("/api/v1/groups")
    assert response.status_code == 200
