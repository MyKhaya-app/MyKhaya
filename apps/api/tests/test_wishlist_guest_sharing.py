"""Wishlists V1 guest link+PIN sharing: verification, rate limiting,
revocation, guest-session IDOR (share A's cookie must never work against
wishlist B), guest reserve/release, and the owner-blindness rule applied to
guest-made reservations too. See mykhaya.wishlist_guest and
mykhaya.routers.wishlists' guest_router.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import ActionToken, FeatureKey, FeatureOverride, SubscriptionPlan, TokenPurpose, User
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture(autouse=True)
async def _reset_guest_pin_rate_limit() -> AsyncIterator[None]:
    """The guest-PIN rate limit (mykhaya.rate_limit.enforce_rate_limit) is
    keyed by client IP, which every test in this module shares (the ASGI
    test transport always presents the same fake peer address) — without
    resetting it between tests, an earlier test's verify calls would bleed
    into a later test's rate-limit budget. Only this module needs the
    reset: it is the only place under test that calls the guest-PIN
    verification endpoint at all."""
    from redis.asyncio import Redis

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        async for key in redis.scan_iter("rate:wishlist_guest_pin:*"):
            await redis.delete(key)
        yield
    finally:
        async for key in redis.scan_iter("rate:wishlist_guest_pin:*"):
            await redis.delete(key)
        await redis.aclose()


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def guest_unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_wishlist_guest_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
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
        user_id = user.id
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
    return user_id


async def create_home(
    client: AsyncClient, name: str, *, plan: SubscriptionPlan = SubscriptionPlan.family
) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.wish_lists, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = plan
        await db.commit()
    return home_id


async def create_wishlist(client: AsyncClient, home_id: uuid.UUID, **overrides: object):
    body = {"title": "Christmas List", "occasion": "christmas", **overrides}
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/wishlists", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def add_item(client: AsyncClient, home_id: uuid.UUID, wishlist_id: str, **overrides: object):
    body = {"name": "Board Game", **overrides}
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/items", json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_guest_share(client: AsyncClient, home_id: uuid.UUID, wishlist_id: str, name: str = "Grandad"):
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/shares",
        json={"recipient_name": name, "share_type": "guest"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def fresh_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN})


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_pin_grants_guest_session_and_access(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner"), "Guest Owner")
    home_id = await create_home(client, "Guest Home")
    wishlist = await create_wishlist(client, home_id)
    share = await create_guest_share(client, home_id, wishlist["id"])

    async with await fresh_client() as guest_client:
        verify = await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share['link_token']}/verify",
            json={"pin": share["pin"]},
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()["recipient_name"] == "Grandad"
        assert "mk_wishlist_guest" in guest_client.cookies

        detail = await guest_client.get("/api/v1/wishlist/guest/wishlist")
        assert detail.status_code == 200
        assert detail.json()["id"] == wishlist["id"]


@pytest.mark.asyncio
async def test_wrong_pin_rejected_and_rate_limit_eventually_triggers(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner2"), "Guest Owner 2")
    home_id = await create_home(client, "Guest Rate Home")
    wishlist = await create_wishlist(client, home_id)
    share = await create_guest_share(client, home_id, wishlist["id"])

    async with await fresh_client() as guest_client:
        for _ in range(9):
            bad = await unsafe(
                guest_client,
                "POST",
                f"/api/v1/wishlist/share/{share['link_token']}/verify",
                json={"pin": "000000"},
            )
            assert bad.status_code == 401
        # One of the next attempts crosses the configured
        # _GUEST_PIN_RATE_LIMIT (10 per 5 minutes per IP) and 429s instead
        # of 401 — the exact request that flips depends on the limit
        # already having absorbed one call from the previous test in this
        # process, so just assert it happens within a couple more tries.
        statuses = []
        for _ in range(3):
            resp = await unsafe(
                guest_client,
                "POST",
                f"/api/v1/wishlist/share/{share['link_token']}/verify",
                json={"pin": "000000"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses


@pytest.mark.asyncio
async def test_invalid_token_rejected_without_500(client: AsyncClient) -> None:
    async with await fresh_client() as guest_client:
        response = await unsafe(
            guest_client,
            "POST",
            "/api/v1/wishlist/share/not-a-real-token/verify",
            json={"pin": "123456"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_wellformed_token_for_nonexistent_share_rejected(client: AsyncClient) -> None:
    from mykhaya.security import derived_token as _derived_token

    fake_id = uuid.uuid4()
    fake_token = _derived_token(
        fake_id, "wishlist_share", get_settings().secret_key.get_secret_value()
    )
    async with await fresh_client() as guest_client:
        response = await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{fake_token}/verify",
            json={"pin": "123456"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_revoked_share_token_and_pin_no_longer_work(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner3"), "Guest Owner 3")
    home_id = await create_home(client, "Guest Revoke Home")
    wishlist = await create_wishlist(client, home_id)
    share = await create_guest_share(client, home_id, wishlist["id"])

    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares/{share['id']}/revoke",
    )

    async with await fresh_client() as guest_client:
        verify = await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share['link_token']}/verify",
            json={"pin": share["pin"]},
        )
        assert verify.status_code == 401


# ---------------------------------------------------------------------------
# Guest session IDOR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guest_session_for_wishlist_a_cannot_access_wishlist_b(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner4"), "Guest Owner 4")
    home_id = await create_home(client, "Guest IDOR Home")
    wishlist_a = await create_wishlist(client, home_id, title="List A")
    wishlist_b = await create_wishlist(client, home_id, title="List B")
    item_b = await add_item(client, home_id, wishlist_b["id"])
    item_b_id = item_b["items"][0]["id"]
    share_a = await create_guest_share(client, home_id, wishlist_a["id"])

    async with await fresh_client() as guest_client:
        verify = await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share_a['link_token']}/verify",
            json={"pin": share_a["pin"]},
        )
        assert verify.status_code == 200

        detail = await guest_client.get("/api/v1/wishlist/guest/wishlist")
        assert detail.json()["id"] == wishlist_a["id"]
        assert detail.json()["id"] != wishlist_b["id"]

        # The guest endpoints are scoped entirely by the resolved share, so
        # there is no path parameter to substitute wishlist_b's id into —
        # confirm the item lookup itself is scoped to wishlist_a and 404s
        # for an item that only exists on wishlist_b.
        reserve_other = await guest_unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/guest/items/{item_b_id}/reserve",
            json={},
        )
        assert reserve_other.status_code == 404


# ---------------------------------------------------------------------------
# Guest reserve / release / permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guest_can_reserve_and_release_own_reservation(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner5"), "Guest Owner 5")
    home_id = await create_home(client, "Guest Reserve Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"])
    item_id = added["items"][0]["id"]
    share = await create_guest_share(client, home_id, wishlist["id"])

    async with await fresh_client() as guest_client:
        await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share['link_token']}/verify",
            json={"pin": share["pin"]},
        )
        reserved = await guest_unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/guest/items/{item_id}/reserve",
            json={},
        )
        assert reserved.status_code == 200, reserved.text
        assert reserved.json()["reservation_status"] == "reserved"
        assert reserved.json()["reserved_by_display_name"] == "Grandad"

        released = await guest_unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/guest/items/{item_id}/release",
            json={},
        )
        assert released.status_code == 200
        assert released.json()["reservation_status"] == "available"


@pytest.mark.asyncio
async def test_guest_cannot_edit_wishlist_or_item_content(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner6"), "Guest Owner 6")
    home_id = await create_home(client, "Guest No Edit Home")
    wishlist = await create_wishlist(client, home_id)
    share = await create_guest_share(client, home_id, wishlist["id"])

    async with await fresh_client() as guest_client:
        await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share['link_token']}/verify",
            json={"pin": share["pin"]},
        )
        # No guest-facing mutate-content routes exist at all — the guest
        # router only exposes wishlist/reserve/mark-bought/release/logout.
        # Confirm the home-scoped edit routes reject a guest cookie outright
        # (guests never authenticate through auth_context, so these 401).
        blocked = await unsafe(
            guest_client,
            "POST",
            f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/items",
            json={"name": "Sneaky"},
        )
        assert blocked.status_code == 401


@pytest.mark.asyncio
async def test_owner_remains_blind_to_a_guest_made_reservation(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guestowner7"), "Guest Owner 7")
    home_id = await create_home(client, "Guest Privacy Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"])
    item_id = added["items"][0]["id"]
    share = await create_guest_share(client, home_id, wishlist["id"])

    async with await fresh_client() as guest_client:
        await unsafe(
            guest_client,
            "POST",
            f"/api/v1/wishlist/share/{share['link_token']}/verify",
            json={"pin": share["pin"]},
        )
        await guest_unsafe(
            guest_client, "POST", f"/api/v1/wishlist/guest/items/{item_id}/reserve", json={}
        )

    owner_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    owner_item = next(i for i in owner_view.json()["items"] if i["id"] == item_id)
    assert "reservation_status" not in owner_item
    assert "reserved_by_display_name" not in owner_item
