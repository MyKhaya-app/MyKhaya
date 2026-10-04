"""Tests for the Phase 3 consumer/native legal wiring: signup acceptance
recording, the guardian-authorisation gate on enabling a managed child's
sign-in, and the identity/security boundaries between adult, guardian and
managed-child actions — see mykhaya.legal, mykhaya.routers.auth.register,
mykhaya.routers.children.configure_child_login, mykhaya.routers.legal.
"""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_child_login import _child_login, _configure_login, _high_limits, _make_home_with_child
from test_journey import ORIGIN, PASSWORD, latest_token, unsafe
from test_legal import (
    _archive_adult_legal_documents_after_test,
    admin_client,
    admin_factory,
    admin_login,
    admin_unsafe,
    client,
    create_and_publish_document,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import PlatformRole, TokenPurpose, User

__all__ = [
    "admin_factory",
    "admin_client",
    "client",
    "_archive_adult_legal_documents_after_test",
]  # re-exported fixtures


def unique(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}"


async def register(client: AsyncClient, email: str, name: str, **extra: object):
    return await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD, **extra},
    )


async def archive_document(admin: AsyncClient, document_id: str) -> None:
    """Cleans up a test-created child-audience document so it doesn't keep
    counting as "acceptance_required" for the guardian-authorisation gate
    in later test runs against this same shared database — see
    guardian_authorisation_satisfied, which only ever considers
    non-archived documents."""
    response = await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/archive",
        json={"reason": "Automated test cleanup"},
    )
    assert response.status_code == 200, response.text


async def verify_and_login(client: AsyncClient, email: str) -> None:
    token = await latest_token(email, TokenPurpose.verify_email)
    assert (
        await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_signup_with_no_required_documents_is_unaffected(client: AsyncClient) -> None:
    """No adult document is configured as acceptance_required in a typical
    test run — signup must behave exactly as it always has."""
    email = f"{unique('plain')}@example.com"
    response = await register(client, email, "Plain Signup")
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_signup_records_exact_displayed_version_with_correct_record_types(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    terms_key = unique("terms")
    privacy_key = unique("privacy")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    terms = await create_and_publish_document(admin_client, terms_key, "Terms", "adult", "accept")
    privacy = await create_and_publish_document(
        admin_client, privacy_key, "Privacy Policy", "adult", "acknowledge"
    )

    email = f"{unique('signup')}@example.com"
    response = await register(
        client,
        email,
        "Signup Adult",
        legal_acceptances=[
            {"document_key": terms_key, "document_version_id": terms["version"]["id"]},
            {"document_key": privacy_key, "document_version_id": privacy["version"]["id"]},
        ],
        platform="ios",
    )
    assert response.status_code == 202, response.text
    await verify_and_login(client, email)

    status_response = await unsafe(client, "GET", "/api/v1/legal/status")
    by_key = {d["document_key"]: d for d in status_response.json()["documents"]}
    assert by_key[terms_key]["satisfied"] is True
    assert by_key[terms_key]["action_verb"] == "accept"
    assert by_key[privacy_key]["satisfied"] is True
    assert by_key[privacy_key]["action_verb"] == "acknowledge"


@pytest.mark.asyncio
async def test_signup_missing_required_acceptance_is_rejected(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    terms_key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    await create_and_publish_document(admin_client, terms_key, "Terms", "adult", "accept")

    email = f"{unique('missing')}@example.com"
    response = await register(client, email, "Missing Acceptance")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "legal_acceptance_required"

    # No user should have been created.
    async with SessionFactory() as db:
        assert await db.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_signup_fails_safely_when_policy_changes_mid_signup(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    """Scenario 6 from the brief: the client submits the version it actually
    displayed; if that's gone stale by the time the account is created,
    fail rather than silently re-resolving to whatever is current now."""
    terms_key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    v1 = await create_and_publish_document(admin_client, terms_key, "Terms", "adult", "accept")

    # Republish a v2 while "signup" still holds the v1 id.
    draft2 = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{v1['document']['id']}/versions",
        json={"content_markdown": "v2 content.", "version": "2.0"},
    )
    await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{v1['document']['id']}/versions/{draft2.json()['id']}/publish",
        json={"reacceptance_scope": "new_users_only", "reason": "Publishing for test coverage"},
    )

    email = f"{unique('stale')}@example.com"
    response = await register(
        client,
        email,
        "Stale Signup",
        legal_acceptances=[{"document_key": terms_key, "document_version_id": v1["version"]["id"]}],
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "legal_document_changed"
    async with SessionFactory() as db:
        assert await db.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_signup_fails_safely_when_required_document_has_no_published_version(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    created = await admin_unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/legal/documents",
        json={"key": key, "display_name": "Terms", "audience": "adult", "action_verb": "accept"},
    )
    assert created.status_code == 201  # acceptance_required=True by default, never published

    email = f"{unique('misconfig')}@example.com"
    response = await register(client, email, "Misconfigured Signup")
    assert response.status_code == 503
    async with SessionFactory() as db:
        assert await db.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_authenticated_user_can_read_current_exact_version_before_reaccepting(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    first = await create_and_publish_document(admin_client, key, "Terms", "adult", "accept")
    email = f"{unique('current-version')}@example.com"
    registered = await register(
        client,
        email,
        "Current Version Reader",
        legal_acceptances=[{"document_key": key, "document_version_id": first["version"]["id"]}],
    )
    assert registered.status_code == 202
    await verify_and_login(client, email)

    draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{first['document']['id']}/versions",
        json={"content_markdown": "# Updated Terms", "version": "2.0"},
    )
    published = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{first['document']['id']}/versions/{draft.json()['id']}/publish",
        json={"reacceptance_scope": "all_existing_users", "reason": "Updated policy test"},
    )
    assert published.status_code == 200
    current = await unsafe(client, "GET", f"/api/v1/legal/versions/{published.json()['id']}")
    assert current.status_code == 200
    assert current.json()["version"] == "2.0"


@pytest.mark.asyncio
async def test_managed_child_cannot_record_adult_acceptance(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    adult = await create_and_publish_document(
        admin_client, unique("terms"), "Terms", "adult", "accept"
    )
    group_id, membership_id, home_code = await _make_home_with_child(
        client,
        unique("child-legal"),
        legal_acceptances=[
            {
                "document_key": adult["document"]["key"],
                "document_version_id": adult["version"]["id"],
            }
        ],
    )
    configured = await _configure_login(
        client, group_id, membership_id, enabled=True, username="kiddo", pin="1234"
    )
    assert configured.status_code == 200
    app.dependency_overrides[get_settings] = _high_limits
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as child_client:
            login = await _child_login(child_client, home_code, "kiddo", "1234")
            assert login.status_code == 200
            attempt = await unsafe(
                child_client,
                "POST",
                "/api/v1/legal/acceptances",
                json={
                    "document_key": adult["document"]["key"],
                    "document_version_id": adult["version"]["id"],
                    "context": "settings",
                    "platform": "web",
                },
            )
            assert attempt.status_code == 403
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_enabling_child_login_requires_guardian_authorisation_when_configured(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("children-privacy")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    doc = await create_and_publish_document(
        admin_client, key, "Family & Children's Privacy Notice", "child", "accept"
    )

    try:
        suffix = unique("guard")
        group_id, membership_id, _home_code = await _make_home_with_child(client, suffix)

        # Enabling without prior guardian authorisation is refused.
        blocked = await _configure_login(
            client, group_id, membership_id, enabled=True, username="kiddo", pin="1234"
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "guardian_authorisation_required"

        authorise = await unsafe(
            client,
            "POST",
            "/api/v1/legal/guardian-authorisations",
            json={
                "child_membership_id": membership_id,
                "document_version_id": doc["version"]["id"],
                "context": "guardian_child_login_setup",
                "platform": "web",
            },
        )
        assert authorise.status_code == 201, authorise.text

        allowed = await _configure_login(
            client, group_id, membership_id, enabled=True, username="kiddo", pin="1234"
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        await archive_document(admin_client, doc["document"]["id"])


@pytest.mark.asyncio
async def test_managed_child_session_cannot_submit_guardian_authorisation(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("children-privacy")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    doc = await create_and_publish_document(
        admin_client, key, "Family & Children's Privacy Notice", "child", "accept"
    )
    try:
        suffix = unique("imp")
        group_id, membership_id, home_code = await _make_home_with_child(client, suffix)
        # Guardian authorises first (deterministically, regardless of any
        # other required child document left over elsewhere) so the child's
        # login is guaranteed to succeed below.
        authorise = await unsafe(
            client,
            "POST",
            "/api/v1/legal/guardian-authorisations",
            json={
                "child_membership_id": membership_id,
                "document_version_id": doc["version"]["id"],
                "context": "guardian_child_login_setup",
                "platform": "web",
            },
        )
        assert authorise.status_code == 201, authorise.text
        configured = await _configure_login(
            client, group_id, membership_id, enabled=True, username="kiddo", pin="5678"
        )
        assert configured.status_code == 200, configured.text

        app.dependency_overrides[get_settings] = _high_limits
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
            ) as child_client:
                login = await _child_login(child_client, home_code, "kiddo", "5678")
                assert login.status_code == 200, login.text
                attempt = await unsafe(
                    child_client,
                    "POST",
                    "/api/v1/legal/guardian-authorisations",
                    json={
                        "child_membership_id": membership_id,
                        "document_version_id": doc["version"]["id"],
                        "context": "guardian_child_login_setup",
                        "platform": "web",
                    },
                )
                assert attempt.status_code == 403
        finally:
            app.dependency_overrides.pop(get_settings, None)
    finally:
        await archive_document(admin_client, doc["document"]["id"])


@pytest.mark.asyncio
async def test_adult_session_cannot_submit_child_acknowledgement(client: AsyncClient) -> None:
    email = f"{unique('adultack')}@example.com"
    registered = await register(client, email, "Adult Only")
    assert registered.status_code == 202
    await verify_and_login(client, email)
    attempt = await unsafe(
        client,
        "POST",
        "/api/v1/legal/child-acknowledgements",
        json={"document_version_id": "00000000-0000-0000-0000-000000000000", "platform": "web"},
    )
    assert attempt.status_code == 403


@pytest.mark.asyncio
async def test_unrelated_adult_cannot_authorise_a_child_they_do_not_guard(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("children-privacy")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    doc = await create_and_publish_document(
        admin_client, key, "Family & Children's Privacy Notice", "child", "accept"
    )
    suffix = unique("stranger")
    _group_id, membership_id, _home_code = await _make_home_with_child(client, suffix)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_email = f"{unique('outsider')}@example.com"
        registered = await register(other_client, other_email, "Outsider")
        assert registered.status_code == 202
        await verify_and_login(other_client, other_email)
        attempt = await unsafe(
            other_client,
            "POST",
            "/api/v1/legal/guardian-authorisations",
            json={
                "child_membership_id": membership_id,
                "document_version_id": doc["version"]["id"],
                "context": "guardian_child_login_setup",
                "platform": "web",
            },
        )
        assert attempt.status_code == 403


@pytest.mark.asyncio
async def test_historical_version_visible_to_the_user_who_accepted_it_only(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    v1 = await create_and_publish_document(admin_client, key, "Terms", "adult", "accept")

    email = f"{unique('history')}@example.com"
    registered = await register(
        client,
        email,
        "History Adult",
        legal_acceptances=[{"document_key": key, "document_version_id": v1["version"]["id"]}],
    )
    assert registered.status_code == 202
    await verify_and_login(client, email)

    # Publish v2 so "current" no longer matches what this user accepted.
    draft2 = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{v1['document']['id']}/versions",
        json={"content_markdown": "v2 content.", "version": "2.0"},
    )
    publish2 = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{v1['document']['id']}/versions/{draft2.json()['id']}/publish",
        json={"reacceptance_scope": "none", "reason": "Publishing for test coverage"},
    )
    v2_id = publish2.json()["id"]

    historical = await unsafe(client, "GET", f"/api/v1/legal/versions/{v1['version']['id']}")
    assert historical.status_code == 200
    assert historical.json()["version"] == "1.0"
    assert historical.json()["content_markdown"] == "# Terms\n\nInitial content."

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_email = f"{unique('nohistory')}@example.com"
        # Must accept the now-current v2 to register at all (Terms is still
        # required) — the point being tested is that accepting v2 does not
        # grant them access to v1's content, not that Terms stops applying.
        registered_other = await register(
            other_client,
            other_email,
            "No History",
            legal_acceptances=[{"document_key": key, "document_version_id": v2_id}],
        )
        assert registered_other.status_code == 202
        await verify_and_login(other_client, other_email)
        denied = await unsafe(other_client, "GET", f"/api/v1/legal/versions/{v1['version']['id']}")
        assert denied.status_code == 404
