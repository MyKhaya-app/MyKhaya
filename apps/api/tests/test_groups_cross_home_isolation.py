"""Regression coverage for groups.py's member-mutation endpoints: the BOLA/IDOR
audit (docs/security/MYKHAYA_SECURITY_AUDIT_2026-10.md) found these correctly
scoped via require_capability(group_id, ...) + a (group_id, user_id)-filtered
Membership lookup, but no existing test proved a Home Admin of one Home cannot
act on a *different* Home's membership by supplying its id directly.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_home_admin_cannot_update_a_members_relationship_in_another_home(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")

    # Home A: its own admin.
    await create_verified_user(client, f"groups-iso-a-{suffix}@example.com", "Admin A")
    home_a = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Home A"})
    assert home_a.status_code == 201
    home_a_id = home_a.json()["id"]

    # Home B: a different admin, who is the member Home A's admin will try to mutate.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client_b:
        await create_verified_user(client_b, f"groups-iso-b-{suffix}@example.com", "Admin B")
        home_b = await unsafe(client_b, "POST", "/api/v1/groups", json={"name": "Home B"})
        assert home_b.status_code == 201
        home_b_id = home_b.json()["id"]
        me_b = await client_b.get("/api/v1/users/me")
        assert me_b.status_code == 200
        admin_b_user_id = me_b.json()["id"]

    # Home A's admin attempts to change Home B's own admin's relationship by
    # supplying Home B's group_id and its member's user_id directly.
    cross_home_attempt = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_b_id}/members/{admin_b_user_id}",
        json={"relationship": "partner", "confirmed": True},
    )
    assert cross_home_attempt.status_code == 404, (
        "A caller with no membership in Home B must be denied before the target "
        "membership is even looked up — identical 404 whether the Home or the "
        "membership doesn't exist, per dependencies.membership_for's no-enumeration rule."
    )

    # Home A's own admin membership is untouched and still manageable within Home A.
    me_a = await client.get("/api/v1/users/me")
    assert me_a.status_code == 200
    admin_a_user_id = me_a.json()["id"]
    same_home_attempt = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_a_id}/members/{admin_a_user_id}",
        json={"relationship": "home_admin", "confirmed": True},
    )
    assert same_home_attempt.status_code == 200
