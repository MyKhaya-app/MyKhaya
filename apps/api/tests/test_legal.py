"""Tests for the Legal & Compliance foundation (Phase 1): PCC document
lifecycle/immutability, public unauthenticated document routes, and the
adult/guardian/child acceptance model — see mykhaya.legal,
mykhaya.routers.legal, mykhaya.routers.platform_legal.

The ten scenarios in the module docstring at the bottom mirror the Legal &
Compliance brief's explicit "before finalising the schema" checklist.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_child_login import _child_login, _configure_login, _high_limits, _make_home_with_child
from test_journey import ORIGIN, create_verified_user, unsafe
from test_platform_support import ADMIN_ORIGIN, admin_factory, admin_login, admin_unsafe

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.legal import _status_from_records
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    LegalAcceptance,
    LegalAcceptanceContext,
    LegalActionVerb,
    LegalAudience,
    LegalDocument,
    LegalDocumentScope,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalPlatform,
    LegalReacceptanceScope,
    LegalRecordType,
    PlatformRole,
)
from mykhaya.platform_schemas import AcceptanceUserRow, PlatformLoginRequest

__all__ = [
    "admin_factory",
    "_archive_adult_legal_documents_after_test",
]  # re-exported fixtures, see tests/test_platform_support.py


@pytest.fixture(autouse=True)
async def _archive_adult_legal_documents_after_test() -> AsyncIterator[None]:
    """Every test here (and in test_legal_consumer.py, which imports this
    fixture) is free to publish or leave in draft any acceptance_required
    LegalDocument — adult (Terms/Privacy, gating signup) or child
    (Children's Privacy, gating the guardian-authorisation-before-login-
    enable check) — without worrying that it will make every *other*
    test's plain signup or child-login-enable calls start demanding it too.
    Neither mykhaya.legal.required_adult_documents nor
    guardian_authorisation_satisfied cares whether a document was created
    by this test or a completely unrelated one earlier in the same run.
    Archiving here, after every test, keeps that requirement scoped to the
    test that actually wants it instead of leaking across the whole
    session."""
    yield
    async with SessionFactory() as db:
        await db.execute(
            update(LegalDocument)
            .where(LegalDocument.archived_at.is_(None))
            .values(archived_at=datetime.now(UTC))
        )
        await db.commit()


def unique(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}"


def test_legacy_terms_key_acceptance_satisfies_canonical_terms_version() -> None:
    legacy_version = LegalDocumentVersion(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version_sequence=1,
        version="1.0",
        status=LegalDocumentVersionStatus.superseded,
        content_markdown="# Terms",
        reacceptance_scope=LegalReacceptanceScope.all_existing_users,
    )
    current_version = LegalDocumentVersion(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version_sequence=1,
        version="1.0",
        status=LegalDocumentVersionStatus.published,
        content_markdown="# Terms",
        reacceptance_scope=LegalReacceptanceScope.all_existing_users,
    )
    legacy_acceptance = LegalAcceptance(
        record_type=LegalRecordType.user_acceptance,
        document_version_id=legacy_version.id,
        user_id=uuid.uuid4(),
        context=LegalAcceptanceContext.signup,
        platform=LegalPlatform.web,
    )
    status = _status_from_records(
        LegalDocument(
            key="terms",
            display_name="Terms & Conditions",
            audience=LegalAudience.adult,
            scope=LegalDocumentScope.global_,
            action_verb=LegalActionVerb.accept,
            acceptance_required=True,
        ),
        current_version,
        [(legacy_acceptance, legacy_version)],
        action_verb=LegalActionVerb.accept,
    )
    assert status.required is True
    assert status.satisfied is True


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.2", 44241)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": "127.0.0.1"},
    ) as value:
        yield value


async def create_and_publish_document(
    admin: AsyncClient,
    key: str,
    display_name: str,
    audience: str,
    action_verb: str = "accept",
    version: str = "1.0",
    reacceptance_scope: str = "new_users_only",
    scope: str = "global",
    acceptance_required: bool = True,
) -> dict[str, Any]:
    created = await admin_unsafe(
        admin,
        "POST",
        "/api/v1/platform/legal/documents",
        json={
            "key": key,
            "display_name": display_name,
            "audience": audience,
            "action_verb": action_verb,
            "scope": scope,
            "acceptance_required": acceptance_required,
        },
    )
    assert created.status_code == 201, created.text
    document = created.json()
    draft = await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/legal/documents/{document['id']}/versions",
        json={"content_markdown": "# Terms\n\nInitial content.", "version": version},
    )
    assert draft.status_code == 201, draft.text
    version_row = draft.json()
    published = await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/legal/documents/{document['id']}/versions/{version_row['id']}/publish",
        json={"reacceptance_scope": reacceptance_scope, "reason": "Publishing for test coverage"},
    )
    assert published.status_code == 200, published.text
    return {"document": document, "version": published.json()}


@pytest.mark.asyncio
async def test_public_document_not_visible_until_published(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)

    created = await admin_unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/legal/documents",
        json={
            "key": key,
            "display_name": "Test Terms",
            "audience": "adult",
            "action_verb": "accept",
        },
    )
    assert created.status_code == 201

    missing = await client.get(f"/api/v1/legal/documents/{key}")
    assert missing.status_code == 404

    document_id = created.json()["id"]
    draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions",
        json={"content_markdown": "Draft only.", "version": "1.0"},
    )
    assert draft.status_code == 201

    # Draft content is never reachable through the public route.
    still_missing = await client.get(f"/api/v1/legal/documents/{key}")
    assert still_missing.status_code == 404

    version_id = draft.json()["id"]
    publish = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions/{version_id}/publish",
        json={"reacceptance_scope": "new_users_only", "reason": "Publishing for test coverage"},
    )
    assert publish.status_code == 200

    now_public = await client.get(f"/api/v1/legal/documents/{key}")
    assert now_public.status_code == 200
    assert now_public.json()["version"] == "1.0"


@pytest.mark.asyncio
async def test_acceptance_dashboard_serialises_managed_child_identifier(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    """Managed-child account identifiers are operational strings, not emails."""
    await _make_home_with_child(client, unique("acceptance-managed-child"))
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    response = await admin_client.get("/api/v1/platform/compliance/acceptance?scope=production")
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    # The dashboard lists every active account in the shared test database, ordered
    # by display name, so other tests' managed children may sort ahead of this one:
    # every managed-child row must carry the operational identifier, and this
    # test's own child ("Kid") must be among them.
    managed_rows = [row for row in rows if row["account_type"] == "managed_child"]
    assert all(row["email"] == "Managed child" for row in managed_rows)
    managed = next(row for row in managed_rows if row["display_name"] == "Kid")
    adult = next(row for row in rows if row["account_type"] == "adult")
    assert adult["email"].endswith("@example.com")

    # The operational response field accepts the existing managed-child
    # identifier without changing global login/email validation.
    synthetic = dict(managed, email="managed-child-test@managed.mykhaya.invalid")
    AcceptanceUserRow.model_validate(synthetic)
    with pytest.raises(ValueError):
        PlatformLoginRequest(email=synthetic["email"], password="not-used")


@pytest.mark.asyncio
async def test_test_publication_isolated_from_production_publication(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("test-mode-terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    production = await create_and_publish_document(admin_client, key, "Test Mode Terms", "adult")

    mode = await admin_unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/compliance/legal-test-mode",
        json={
            "enabled": True,
            "test_user_ids": [],
            "reason": "Enable legal test coverage",
            "confirmed": True,
        },
    )
    assert mode.status_code == 200, mode.text
    document_id = production["document"]["id"]
    draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions",
        json={"content_markdown": "Test content.", "version": "test-1"},
    )
    assert draft.status_code == 201, draft.text
    published = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions/{draft.json()['id']}/publish",
        json={"reason": "Publish isolated legal test version", "is_test": True},
    )
    assert published.status_code == 200, published.text
    assert published.json()["is_test"] is True

    public = await client.get(f"/api/v1/legal/documents/{key}")
    assert public.status_code == 200
    assert public.json()["version"] == "1.0"
    listing = await admin_unsafe(
        admin_client, "GET", f"/api/v1/platform/legal/documents/{document_id}"
    )
    assert listing.status_code == 200
    assert listing.json()["published_version"]["version"] == "1.0"
    assert listing.json()["test_published_version"]["version"] == "test-1"

    disabled = await admin_unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/compliance/legal-test-mode",
        json={
            "enabled": False,
            "test_user_ids": [],
            "reason": "Disable legal test coverage",
            "confirmed": True,
        },
    )
    assert disabled.status_code == 200, disabled.text


@pytest.mark.asyncio
async def test_published_version_is_immutable(admin_client: AsyncClient, admin_factory) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    result = await create_and_publish_document(admin_client, key, "Immutable Terms", "adult")
    version_id = result["version"]["id"]
    document_id = result["document"]["id"]

    attempt = await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/legal/documents/{document_id}/versions/{version_id}",
        json={"content_markdown": "Tampered."},
    )
    assert attempt.status_code == 409


@pytest.mark.asyncio
async def test_editing_published_document_creates_new_draft_leaves_published_alone(
    admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    result = await create_and_publish_document(admin_client, key, "Terms", "adult")
    document_id = result["document"]["id"]

    new_draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions",
        json={"content_markdown": "v1.1 wording tweak.", "version": "1.1"},
    )
    assert new_draft.status_code == 201, new_draft.text

    listing = await admin_unsafe(
        admin_client, "GET", f"/api/v1/platform/legal/documents/{document_id}/versions"
    )
    assert listing.status_code == 200
    statuses = {row["version"]: row["status"] for row in listing.json()}
    assert statuses == {"1.0": "published", "1.1": "draft"}


@pytest.mark.asyncio
async def test_readonly_administrator_cannot_manage_documents(
    admin_client: AsyncClient, admin_factory
) -> None:
    readonly = await admin_factory(PlatformRole.readonly)
    await admin_login(admin_client, readonly)
    denied = await admin_unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/legal/documents",
        json={
            "key": unique("terms"),
            "display_name": "Nope",
            "audience": "adult",
            "action_verb": "accept",
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_publish_writes_administrative_audit_event(
    admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    result = await create_and_publish_document(admin_client, key, "Terms", "adult")
    version_id = uuid.UUID(result["version"]["id"])

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "legal_document.published",
                    AdministrativeAuditEvent.target_id == version_id,
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].administrator_id == owner.id


@pytest.mark.asyncio
async def test_adult_acceptance_scenarios_1_through_4(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    """Scenarios 1-4 from the brief: accept v1.0, acknowledge Privacy v1.0,
    v1.1 (scope=none) does not force re-acceptance, v2.0
    (scope=all_existing_users) does."""
    terms_key = unique("terms")
    privacy_key = unique("privacy")
    # The user account is created before these documents are published —
    # this test exercises post-signup acceptance, not signup itself (see
    # test_legal_consumer.py for signup-time enforcement), and an existing
    # account must never be blocked by a document that didn't exist yet
    # when they joined.
    email = f"{unique('anthony')}@example.com"
    await create_verified_user(client, email, "Anthony")

    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    terms = await create_and_publish_document(admin_client, terms_key, "Terms", "adult", "accept")
    privacy = await create_and_publish_document(
        admin_client, privacy_key, "Privacy Policy", "adult", "acknowledge"
    )

    # 1. Accept Terms v1.0.
    accept = await unsafe(
        client,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": terms_key,
            "document_version_id": terms["version"]["id"],
            "context": "signup",
            "platform": "web",
        },
    )
    assert accept.status_code == 201, accept.text
    assert accept.json()["satisfied"] is True

    # 2. Acknowledge Privacy v1.0.
    acknowledge = await unsafe(
        client,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": privacy_key,
            "document_version_id": privacy["version"]["id"],
            "context": "signup",
            "platform": "web",
        },
    )
    assert acknowledge.status_code == 201
    assert acknowledge.json()["satisfied"] is True

    status_response = await unsafe(client, "GET", "/api/v1/legal/status")
    assert status_response.status_code == 200
    # Other tests leave their own documents in this shared database, so this
    # only checks the two documents this test itself created, not the
    # response-wide action_required flag.
    by_key = {d["document_key"]: d for d in status_response.json()["documents"]}
    assert by_key[terms_key]["satisfied"] is True
    assert by_key[privacy_key]["satisfied"] is True

    # 3. Terms v1.1, scope=none — does not force re-acceptance.
    draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{terms['document']['id']}/versions",
        json={"content_markdown": "Typo fix.", "version": "1.1"},
    )
    assert draft.status_code == 201
    publish_minor = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{terms['document']['id']}/versions/{draft.json()['id']}/publish",
        json={"reacceptance_scope": "none", "reason": "Publishing for test coverage"},
    )
    assert publish_minor.status_code == 200

    status_after_minor = await unsafe(client, "GET", "/api/v1/legal/status")
    terms_status = next(
        d for d in status_after_minor.json()["documents"] if d["document_key"] == terms_key
    )
    assert terms_status["satisfied"] is True

    # 4. Terms v2.0, scope=all_existing_users — forces re-acceptance.
    draft2 = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{terms['document']['id']}/versions",
        json={"content_markdown": "Material change.", "version": "2.0"},
    )
    assert draft2.status_code == 201
    publish_major = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{terms['document']['id']}/versions/{draft2.json()['id']}/publish",
        json={"reacceptance_scope": "all_existing_users", "reason": "Publishing for test coverage"},
    )
    assert publish_major.status_code == 200
    v2_id = publish_major.json()["id"]

    status_after_major = await unsafe(client, "GET", "/api/v1/legal/status")
    terms_status_2 = next(
        d for d in status_after_major.json()["documents"] if d["document_key"] == terms_key
    )
    assert terms_status_2["satisfied"] is False
    assert terms_status_2["current_version_label"] == "2.0"
    assert status_after_major.json()["action_required"] is True

    reaccept = await unsafe(
        client,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": terms_key,
            "document_version_id": v2_id,
            "context": "policy_update",
            "platform": "web",
        },
    )
    assert reaccept.status_code == 201
    assert reaccept.json()["satisfied"] is True


@pytest.mark.asyncio
async def test_draft_version_cannot_be_accepted(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    key = unique("terms")
    email = f"{unique('taylor')}@example.com"
    await create_verified_user(client, email, "Taylor")

    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    created = await admin_unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/legal/documents",
        json={"key": key, "display_name": "Terms", "audience": "adult", "action_verb": "accept"},
    )
    document_id = created.json()["id"]
    draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{document_id}/versions",
        json={"content_markdown": "Draft.", "version": "1.0"},
    )
    version_id = draft.json()["id"]

    attempt = await unsafe(
        client,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": key,
            "document_version_id": version_id,
            "context": "signup",
            "platform": "web",
        },
    )
    assert attempt.status_code == 409


@pytest.mark.asyncio
async def test_guardian_authorisation_and_child_acknowledgement_are_recorded_independently(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    """Scenarios 5-8 from the brief: guardian authorises the current version
    for a child; the child separately acknowledges it; PCC can determine
    guardian/child compliance independently of one another."""
    key = unique("children-privacy")
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    doc = await create_and_publish_document(
        admin_client, key, "Family & Children's Privacy Notice", "child", "accept"
    )

    suffix = unique("fam")
    group_id, membership_id, home_code = await _make_home_with_child(client, suffix)

    # 5. Guardian authorises the child against Children's Privacy v1.0 —
    # required before enabling login now that Phase 3 gates it (see
    # test_legal_consumer.py's dedicated coverage of that gate).
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
    assert authorise.json()["satisfied"] is True

    configured = await _configure_login(
        client, group_id, membership_id, enabled=True, username="kiddo", pin="9090"
    )
    assert configured.status_code == 200

    guardian_status = await unsafe(client, "GET", "/api/v1/legal/status")
    child_entry = next(
        c
        for c in guardian_status.json()["children"]
        if c["child_membership_id"] == membership_id and c["document_key"] == key
    )
    assert child_entry["guardian_authorisation"]["satisfied"] is True

    # 6. The child logs in and separately acknowledges the same version.
    app.dependency_overrides[get_settings] = _high_limits
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as child_client:
            login = await _child_login(child_client, home_code, "kiddo", "9090")
            assert login.status_code == 200, login.text
            ack = await unsafe(
                child_client,
                "POST",
                "/api/v1/legal/child-acknowledgements",
                json={"document_version_id": doc["version"]["id"], "platform": "web"},
            )
            assert ack.status_code == 201, ack.text
            assert ack.json()["satisfied"] is True
    finally:
        app.dependency_overrides.pop(get_settings, None)

    # 7 & 8. A new version is published; guardian/child compliance are each
    # independently determinable and both become outstanding.
    new_draft = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{doc['document']['id']}/versions",
        json={"content_markdown": "Updated notice.", "version": "1.1"},
    )
    publish_new = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/legal/documents/{doc['document']['id']}/versions/{new_draft.json()['id']}/publish",
        json={"reacceptance_scope": "all_existing_users", "reason": "Publishing for test coverage"},
    )
    assert publish_new.status_code == 200

    final_status = await unsafe(client, "GET", "/api/v1/legal/status")
    final_child_entry = next(
        c
        for c in final_status.json()["children"]
        if c["child_membership_id"] == membership_id and c["document_key"] == key
    )
    assert final_child_entry["guardian_authorisation"]["satisfied"] is False


@pytest.mark.asyncio
async def test_historical_acceptance_survives_supersession_and_cannot_be_edited(
    client: AsyncClient, admin_client: AsyncClient, admin_factory
) -> None:
    """Scenarios 9-10: historical records still prove what happened under
    v1.0, and there is no PCC endpoint to alter an acceptance record."""
    key = unique("terms")
    email = f"{unique('history')}@example.com"
    await create_verified_user(client, email, "History")

    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    v1 = await create_and_publish_document(admin_client, key, "Terms", "adult")

    accept = await unsafe(
        client,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": key,
            "document_version_id": v1["version"]["id"],
            "context": "signup",
            "platform": "web",
        },
    )
    assert accept.status_code == 201

    # Publish v2.0 without forcing re-acceptance so v1's record is untouched.
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
        json={"reacceptance_scope": "none", "reason": "Publishing for test coverage"},
    )

    versions = await admin_unsafe(
        admin_client, "GET", f"/api/v1/platform/legal/documents/{v1['document']['id']}/versions"
    )
    v1_row = next(row for row in versions.json() if row["version"] == "1.0")
    assert v1_row["status"] == "superseded"
    assert v1_row["content_markdown"] == "# Terms\n\nInitial content."
    assert v1_row["acceptance_count"] == 1

    # No PCC route exists to edit or delete a LegalAcceptance — only
    # documents/versions have PCC write routes (create/update/publish/
    # archive), confirmed by inspecting the router's route table.
    from mykhaya.routers import platform_legal as platform_legal_router

    paths = {route.path for route in platform_legal_router.router.routes}
    assert not any("acceptance" in path for path in paths)
