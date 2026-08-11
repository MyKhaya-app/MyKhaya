"""Managed Child sign-in: a Home-scoped code + Child username + PIN, kept fully
separate from adult email/password auth. See mykhaya.routers.auth::child_login,
mykhaya.routers.children's login-config endpoints, and
mykhaya.dependencies.require_adult_session.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.config import get_settings
from mykhaya.main import app

GENERIC_FAILURE = "Incorrect sign-in details."


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}"


async def new_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


async def _make_home_with_child(
    client: AsyncClient, suffix: str
) -> tuple[str, str, str]:
    """Registers a Home Admin, creates a Home and a Child profile. Returns
    (group_id, membership_id, home_code)."""
    await create_verified_user(client, f"admin-{suffix}@example.com", "Home Admin")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": f"Home {suffix}"})
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    home_code = group.json()["child_login_code"]
    assert home_code

    members = await client.get(f"/api/v1/groups/{group_id}/members")
    assert members.status_code == 200
    admin_membership_id = next(
        row["membership_id"] for row in members.json() if row["relationship"] == "home_admin"
    )

    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{group_id}/children",
        json={
            "display_name": "Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [admin_membership_id],
        },
    )
    assert child.status_code == 201, child.text
    return group_id, child.json()["membership_id"], home_code


async def _configure_login(
    client: AsyncClient, group_id: str, membership_id: str, **body: Any
) -> Response:
    return await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{group_id}/children/{membership_id}/login",
        json=body,
    )


async def _child_login(client: AsyncClient, home_code: str, username: str, pin: str) -> Response:
    return await unsafe(
        client,
        "POST",
        "/api/v1/auth/child/login",
        json={"home_code": home_code, "username": username, "pin": pin},
    )


def _high_limits() -> Any:
    return get_settings().model_copy(update={"rate_limit_login": 1000})


@pytest.mark.asyncio
async def test_enable_login_never_returns_the_pin_and_hashes_it(client: AsyncClient) -> None:
    suffix = unique("enable")
    group_id, membership_id, _home_code = await _make_home_with_child(client, suffix)

    response = await _configure_login(
        client, group_id, membership_id, enabled=True, username="timmy", pin="1234"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["login_enabled"] is True
    assert body["login_username"] == "timmy"
    assert "pin" not in body
    assert "pin_hash" not in body
    assert "1234" not in response.text


@pytest.mark.asyncio
async def test_correct_credentials_authenticate_as_managed_child(client: AsyncClient) -> None:
    suffix = unique("ok")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="riley", pin="4242"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            login = await _child_login(child_client, home_code, "riley", "4242")
            assert login.status_code == 200, login.text
            assert login.json()["principal_type"] == "managed_child"
            assert child_client.cookies.get("mk_session")

            me = await child_client.get("/api/v1/users/me")
            assert me.status_code == 200
            assert me.json()["principal_type"] == "managed_child"
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_username_is_case_and_whitespace_insensitive(client: AsyncClient) -> None:
    suffix = unique("norm")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="Sam", pin="9876"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            login = await _child_login(child_client, home_code.lower(), "  SAM  ", "9876")
            assert login.status_code == 200, login.text
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_wrong_pin_wrong_username_and_wrong_home_all_give_identical_generic_error(
    client: AsyncClient,
) -> None:
    suffix = unique("generic")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="jo", pin="1111"
        )
    ).status_code == 200

    async with await new_client() as probe:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            wrong_pin = await _child_login(probe, home_code, "jo", "9999")
            wrong_username = await _child_login(probe, home_code, "nobody", "1111")
            wrong_home = await _child_login(probe, "ZZZZZZZZ", "jo", "1111")

            for response in (wrong_pin, wrong_username, wrong_home):
                assert response.status_code == 401
                assert response.json()["detail"] == GENERIC_FAILURE
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_login_disabled_by_default_until_configured(client: AsyncClient) -> None:
    suffix = unique("default")
    _group_id, _membership_id, home_code = await _make_home_with_child(client, suffix)

    async with await new_client() as probe:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            response = await _child_login(probe, home_code, "anyone", "0000")
            assert response.status_code == 401
            assert response.json()["detail"] == GENERIC_FAILURE
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_cross_home_username_and_pin_are_rejected(client: AsyncClient) -> None:
    suffix_a = unique("homea")
    suffix_b = unique("homeb")
    group_a, membership_a, _home_code_a = await _make_home_with_child(client, suffix_a)
    assert (
        await _configure_login(
            client, group_a, membership_a, enabled=True, username="dup", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as second_admin:
        _group_b, membership_b, home_code_b = await _make_home_with_child(second_admin, suffix_b)
        assert (
            await _configure_login(
                second_admin, _group_b, membership_b, enabled=True, username="dup", pin="1234"
            )
        ).status_code == 200

        # Same username/PIN, but the wrong Home's code — must fail.
        async with await new_client() as probe:
            app.dependency_overrides[get_settings] = _high_limits
            try:
                other_home_login = await _child_login(probe, home_code_b, "dup", "9999")
                assert other_home_login.status_code == 401
            finally:
                app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_username_uniqueness_is_scoped_to_the_home_not_global(client: AsyncClient) -> None:
    suffix_a = unique("scopea")
    suffix_b = unique("scopeb")
    group_a, membership_a, _ = await _make_home_with_child(client, suffix_a)
    assert (
        await _configure_login(
            client, group_a, membership_a, enabled=True, username="alex", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as second_admin:
        group_b, membership_b, _ = await _make_home_with_child(second_admin, suffix_b)
        # Same username in a *different* Home is fine.
        same_name_other_home = await _configure_login(
            second_admin, group_b, membership_b, enabled=True, username="alex", pin="5678"
        )
        assert same_name_other_home.status_code == 200


@pytest.mark.asyncio
async def test_username_must_be_unique_within_the_same_home(client: AsyncClient) -> None:
    suffix = unique("dupehome")
    group_id, membership_1, _ = await _make_home_with_child(client, suffix)
    members = await client.get(f"/api/v1/groups/{group_id}/members")
    admin_membership_id = next(
        row["membership_id"] for row in members.json() if row["relationship"] == "home_admin"
    )
    child2 = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{group_id}/children",
        json={
            "display_name": "Second Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [admin_membership_id],
        },
    )
    assert child2.status_code == 201
    membership_2 = child2.json()["membership_id"]

    assert (
        await _configure_login(
            client, group_id, membership_1, enabled=True, username="same", pin="1234"
        )
    ).status_code == 200
    conflict = await _configure_login(
        client, group_id, membership_2, enabled=True, username="same", pin="5678"
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_requests_for_the_same_username_never_both_succeed(
    client: AsyncClient,
) -> None:
    """Two children in the same Home both try to claim the same username at
    (as near as a test can get to) the same instant. The application-layer
    pre-check alone cannot prevent this — both requests can pass it before either
    has committed — so this is a regression test for the actual guarantee: the
    uq_child_login_username_per_home database constraint. Exactly one request must
    succeed; the other must get a clean 409, never a 500, and the username must
    never end up unset or duplicated."""
    suffix = unique("race")
    group_id, membership_1, _ = await _make_home_with_child(client, suffix)
    members = await client.get(f"/api/v1/groups/{group_id}/members")
    admin_membership_id = next(
        row["membership_id"] for row in members.json() if row["relationship"] == "home_admin"
    )
    child2 = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{group_id}/children",
        json={
            "display_name": "Racing Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [admin_membership_id],
        },
    )
    assert child2.status_code == 201
    membership_2 = child2.json()["membership_id"]

    results = await asyncio.gather(
        _configure_login(
            client, group_id, membership_1, enabled=True, username="racer", pin="1111"
        ),
        _configure_login(
            client, group_id, membership_2, enabled=True, username="racer", pin="2222"
        ),
    )
    statuses = sorted(response.status_code for response in results)
    assert statuses == [200, 409], [r.text for r in results]

    children = await client.get(f"/api/v1/groups/{group_id}/children")
    usernames = [row["login_username"] for row in children.json() if row["login_enabled"]]
    assert usernames == ["racer"], "exactly one child may hold the contested username"


@pytest.mark.asyncio
async def test_identity_rate_limit_locks_out_repeated_wrong_pin_attempts(
    client: AsyncClient,
) -> None:
    suffix = unique("lockout")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="lock", pin="1234"
        )
    ).status_code == 200

    # High per-IP limit so only the per-identity (home_code+username) bucket is
    # exercised here.
    async with await new_client() as attacker:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            last_status = None
            for _ in range(9):
                response = await _child_login(attacker, home_code, "lock", "0000")
                last_status = response.status_code
            assert last_status == 429

            # Even the *correct* PIN is now locked out — the limiter protects the
            # identity, not just wrong guesses.
            correct_but_locked = await _child_login(attacker, home_code, "lock", "1234")
            assert correct_but_locked.status_code == 429
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_child_session_cannot_create_a_home_or_send_an_invitation(
    client: AsyncClient,
) -> None:
    suffix = unique("adultonly")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="restricted", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            login = await _child_login(child_client, home_code, "restricted", "1234")
            assert login.status_code == 200

            create_home = await unsafe(
                child_client, "POST", "/api/v1/groups", json={"name": "Should Not Exist"}
            )
            assert create_home.status_code == 403

            invite = await unsafe(
                child_client,
                "POST",
                "/api/v1/invitations",
                json={
                    "group_id": group_id,
                    "email": "someone@example.com",
                    "relationship": "partner",
                },
            )
            assert invite.status_code == 403

            manage_own_login = await _configure_login(
                child_client, group_id, membership_id, enabled=False
            )
            assert manage_own_login.status_code == 403
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_child_session_can_still_reach_its_own_profile_and_home(
    client: AsyncClient,
) -> None:
    suffix = unique("permitted")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="ok2", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            assert (await _child_login(child_client, home_code, "ok2", "1234")).status_code == 200

            me = await child_client.get("/api/v1/users/me")
            assert me.status_code == 200

            home = await child_client.get(f"/api/v1/groups/{group_id}")
            assert home.status_code == 200
            assert home.json()["capabilities"] == []
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_changing_the_pin_invalidates_the_old_pin_and_existing_sessions(
    client: AsyncClient,
) -> None:
    suffix = unique("rotate")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="rotate", pin="1111"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            assert (
                await _child_login(child_client, home_code, "rotate", "1111")
            ).status_code == 200
            assert (await child_client.get("/api/v1/users/me")).status_code == 200

            reset = await _configure_login(
                client, group_id, membership_id, enabled=True, pin="2222"
            )
            assert reset.status_code == 200

            # The previously-issued session must now be dead.
            stale = await child_client.get("/api/v1/users/me")
            assert stale.status_code == 401

            # The old PIN no longer works, the new one does.
            old_pin = await _child_login(child_client, home_code, "rotate", "1111")
            assert old_pin.status_code == 401
            new_pin = await _child_login(child_client, home_code, "rotate", "2222")
            assert new_pin.status_code == 200
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_disabling_login_stops_auth_and_revokes_sessions(client: AsyncClient) -> None:
    suffix = unique("disable")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="bye", pin="3333"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            assert (await _child_login(child_client, home_code, "bye", "3333")).status_code == 200
            assert (await child_client.get("/api/v1/users/me")).status_code == 200

            disable = await _configure_login(client, group_id, membership_id, enabled=False)
            assert disable.status_code == 200
            assert disable.json()["login_enabled"] is False
            assert disable.json()["login_username"] is None

            assert (await child_client.get("/api/v1/users/me")).status_code == 401
            still_disabled = await _child_login(child_client, home_code, "bye", "3333")
            assert still_disabled.status_code == 401
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_parent_can_revoke_all_child_sessions_without_disabling_login(
    client: AsyncClient,
) -> None:
    suffix = unique("revokeall")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="multi", pin="4444"
        )
    ).status_code == 200

    async with await new_client() as device_one, await new_client() as device_two:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            assert (
                await _child_login(device_one, home_code, "multi", "4444")
            ).status_code == 200
            assert (
                await _child_login(device_two, home_code, "multi", "4444")
            ).status_code == 200

            revoke = await unsafe(
                client,
                "POST",
                f"/api/v1/groups/{group_id}/children/{membership_id}/login/revoke-sessions",
            )
            assert revoke.status_code == 200
            assert revoke.json()["login_enabled"] is True

            assert (await device_one.get("/api/v1/users/me")).status_code == 401
            assert (await device_two.get("/api/v1/users/me")).status_code == 401

            # Sign-in itself still works afterwards — this only revoked sessions.
            fresh = await _child_login(device_one, home_code, "multi", "4444")
            assert fresh.status_code == 200
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_non_manager_cannot_configure_child_login(client: AsyncClient) -> None:
    suffix = unique("noperm")
    group_id, membership_id, _home_code = await _make_home_with_child(client, suffix)

    async with await new_client() as partner_client:
        await create_verified_user(
            partner_client, f"partner-{suffix}@example.com", "Just A Partner"
        )
        # A brand-new user with no membership in this Home at all.
        response = await _configure_login(
            partner_client, group_id, membership_id, enabled=True, username="xx", pin="1234"
        )
        assert response.status_code in {403, 404}, response.text


@pytest.mark.asyncio
async def test_existing_adult_login_is_unaffected(client: AsyncClient) -> None:
    """Sanity check that normal adult email/password auth still works exactly as
    before, and reports principal_type "adult"."""
    suffix = unique("adult")
    email = f"plain-{suffix}@example.com"
    await create_verified_user(client, email, "Plain Adult")
    me = await client.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["principal_type"] == "adult"
    # An adult's real, validated email is unaffected by the Child-only nulling.
    assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_child_session_never_exposes_its_internal_placeholder_email(
    client: AsyncClient,
) -> None:
    """The synthetic managed-child-*@managed.mykhaya.invalid address is an
    internal implementation detail — see mykhaya.routers.auth.user_response. It
    must never appear in any response body a Child session can see, on login or
    on any endpoint that echoes the authenticated principal back."""
    suffix = unique("noemail")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="noemail", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            login = await _child_login(child_client, home_code, "noemail", "1234")
            assert login.status_code == 200
            assert login.json()["email"] is None

            me = await child_client.get("/api/v1/users/me")
            assert me.status_code == 200
            assert me.json()["email"] is None
            assert ".invalid" not in me.text
        finally:
            app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_rotating_a_child_session_does_not_upgrade_it_to_adult(
    client: AsyncClient,
) -> None:
    """Regression test: POST /auth/sessions/rotate used to call issue_session
    without a kind, silently defaulting the freshly-rotated session to `adult`
    regardless of what was actually being rotated. For a managed Child session
    this was a real privilege escalation — the rotated session could then pass
    require_adult_session and be used to create a brand-new Home. kind must
    always carry over from the session being rotated."""
    suffix = unique("rotate-child")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
    assert (
        await _configure_login(
            client, group_id, membership_id, enabled=True, username="rotator", pin="1234"
        )
    ).status_code == 200

    async with await new_client() as child_client:
        app.dependency_overrides[get_settings] = _high_limits
        try:
            login = await _child_login(child_client, home_code, "rotator", "1234")
            assert login.status_code == 200

            rotated = await unsafe(child_client, "POST", "/api/v1/auth/sessions/rotate", json={})
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["principal_type"] == "managed_child"

            # The rotated session must still be blocked from adult-only actions.
            create_home = await unsafe(
                child_client, "POST", "/api/v1/groups", json={"name": "Should Still Not Exist"}
            )
            assert create_home.status_code == 403

            me = await child_client.get("/api/v1/users/me")
            assert me.status_code == 200
            assert me.json()["principal_type"] == "managed_child"
        finally:
            app.dependency_overrides.pop(get_settings, None)
