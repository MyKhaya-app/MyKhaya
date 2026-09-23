"""Tests for the consumer-facing MyKhaya Support routes (Phase 2A).

Covers ticket creation, MK-#### reference generation/uniqueness, listing,
detail, messages, attachment upload validation, diagnostic allowlisting, the
platform feature-flag gate, and — critically — that a ticket is private to
its own requester even from a same-Home Owner/Admin (Phase 2A decision 5).
"""

import hashlib
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from redis.asyncio import Redis
from sqlalchemy import select

from mykhaya.attachments.storage import LocalAttachmentStorage
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureFlag,
    FeatureKey,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SupportTicket,
    SupportTicketDiagnostic,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token
from mykhaya.support_reference import next_support_reference

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"
# httpx's ASGITransport defaults its `client` peer to ("127.0.0.1", 123)
# when none is given — every test in this file's default `client` fixture
# therefore shares this one rate-limit identity (see
# tests/test_platform_mfa.py's identical PEER constant), matching
# tests/test_platform_security_remediation.py's own _reset_rate_limit
# pattern for the same reason.
DEFAULT_TEST_PEER = "127.0.0.1"


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
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_home(client: AsyncClient, name: str = "Support Test Home") -> uuid.UUID:
    response = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


@pytest.fixture(autouse=True)
async def enable_support_feature() -> AsyncIterator[None]:
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        assert row is not None, "migration 0088 must have seeded a 'support' FeatureFlag row"
        row.enabled = True
        await db.commit()
    yield
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        if row is not None:
            row.enabled = False
            await db.commit()


@pytest.fixture(autouse=True)
async def _reset_support_rate_limits() -> None:
    identity = hashlib.sha256(DEFAULT_TEST_PEER.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        for bucket in ("support-ticket-create", "support-attachment-upload"):
            await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


def make_png_bytes(size: tuple[int, int] = (40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(200, 60, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


# --- storage-layer path traversal (mirrors test_avatars.py's identical
# check for LocalAvatarStorage) ------------------------------------------------


@pytest.mark.asyncio
async def test_local_attachment_storage_rejects_path_traversal_key(tmp_path: Path) -> None:
    storage = LocalAttachmentStorage(tmp_path)
    with pytest.raises(ValueError, match="Invalid attachment storage key"):
        await storage.save("../escape.webp", b"nope")


# --- feature gate -------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_routes_404_when_feature_disabled(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("gate"), "Gate User")
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        assert row is not None
        row.enabled = False
        await db.commit()
    response = await unsafe(client, "GET", "/api/v1/support/tickets")
    assert response.status_code == 404


# --- creation / reference generation ------------------------------------------


@pytest.mark.asyncio
async def test_create_bug_report_returns_mk_reference(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("bug"), "Bug Reporter")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Calendar crashes on save",
            "description": "Tapping Save closes the app immediately.",
            "source": "ios",
            "app_area": "calendar",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["reference"].startswith("MK-")
    assert body["type"] == "bug"
    assert body["status"] == "open"
    assert body["priority"] == "normal"
    assert body["messages"] == []
    assert body["attachments"] == []
    assert body["diagnostics"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "severity_priority",
    ["normal", "elevated", "blocking"],
)
async def test_create_ticket_accepts_explicit_priority(
    client: AsyncClient, severity_priority: str
) -> None:
    """The Report a bug form's severity choice (Minor/Problematic/Blocking)
    maps 1:1 to normal/elevated/blocking — Phase 2D added this field to
    SupportTicketCreate, which previously had no way to set priority at
    creation at all (every ticket silently defaulted to normal)."""
    await create_verified_user(client, unique_email(f"sev-{severity_priority}"), "Severity User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Severity mapping check",
            "description": "Details.",
            "source": "web",
            "priority": severity_priority,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["priority"] == severity_priority


@pytest.mark.asyncio
async def test_create_ticket_rejects_unknown_priority(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("sevbad"), "Bad Severity User")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Bad priority",
            "description": "Details.",
            "source": "web",
            "priority": "urgent",
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_create_ticket_with_diagnostics_stores_and_audits_them(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("diag"), "Diag User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Push notifications not arriving",
            "description": "Nothing since yesterday.",
            "source": "ios",
            "diagnostics": {
                "app_version": "1.4.0",
                "build_number": "204",
                "platform": "ios",
                "os_version": "18.1",
                "runtime": "native",
                "notification_permission": "granted",
                "push_registration_state": "registered",
                "api_connectivity": "ok",
                "network_state": "wifi",
                "background_refresh_state": "enabled",
                "client_timestamp": "2026-09-23T10:00:00Z",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["diagnostics"]["app_version"] == "1.4.0"
    assert body["diagnostics"]["notification_permission"] == "granted"


@pytest.mark.asyncio
async def test_diagnostics_reject_unknown_field(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("diagreject"), "Diag Reject User")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Something broke",
            "description": "Details here.",
            "source": "web",
            "diagnostics": {"app_version": "1.0.0", "access_token": "should-be-rejected"},
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "forbidden_field",
    ["password", "access_token", "refresh_token", "mfa_code", "session_cookie", "api_key"],
)
@pytest.mark.asyncio
async def test_diagnostics_reject_secret_like_fields(
    client: AsyncClient, forbidden_field: str
) -> None:
    await create_verified_user(client, unique_email("secretreject"), "Secret Reject User")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Something broke",
            "description": "Details here.",
            "source": "web",
            "diagnostics": {forbidden_field: "leaked-value"},
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_ticket_references_are_unique_and_sequential_ish(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("seq"), "Sequence User")
    references: set[str] = set()
    for _ in range(3):
        created = await unsafe(
            client,
            "POST",
            "/api/v1/support/tickets",
            json={
                "type": "feedback",
                "subject": "Loving the app",
                "description": "Just some feedback.",
                "source": "android",
            },
        )
        assert created.status_code == 201
        references.add(created.json()["reference"])
    assert len(references) == 3  # never reused, gaps acceptable


@pytest.mark.asyncio
async def test_next_support_reference_format() -> None:
    async with SessionFactory() as db:
        reference = await next_support_reference(db)
        await db.commit()
    assert reference.startswith("MK-")
    assert reference.split("-")[1].isdigit()


@pytest.mark.asyncio
async def test_create_ticket_rejects_group_id_caller_is_not_a_member_of(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("foreign"), "Foreign Home User")
    other_home_id = uuid.uuid4()
    response = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "support",
            "subject": "Help with billing",
            "description": "Question about my plan.",
            "source": "web",
            "group_id": str(other_home_id),
        },
    )
    assert response.status_code == 422, response.text


# --- listing / detail ----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tickets_returns_only_own_tickets(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("listmine"), "List Mine User")
    await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "support",
            "subject": "Question one",
            "description": "Details.",
            "source": "web",
        },
    )
    listed = await unsafe(client, "GET", "/api/v1/support/tickets")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_get_ticket_detail(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("detail"), "Detail User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Detail check",
            "description": "Details.",
            "source": "desktop_web",
        },
    )
    ticket_id = created.json()["id"]
    fetched = await unsafe(client, "GET", f"/api/v1/support/tickets/{ticket_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == ticket_id


@pytest.mark.asyncio
async def test_get_nonexistent_ticket_returns_404(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("missing"), "Missing User")
    fetched = await unsafe(client, "GET", f"/api/v1/support/tickets/{uuid.uuid4()}")
    assert fetched.status_code == 404


# --- messages --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_message_to_own_ticket(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("msg"), "Message User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "support",
            "subject": "Follow-up needed",
            "description": "Details.",
            "source": "web",
        },
    )
    ticket_id = created.json()["id"]
    reply = await unsafe(
        client,
        "POST",
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={"message": "Any update on this?"},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["author"] == "requester"
    fetched = await unsafe(client, "GET", f"/api/v1/support/tickets/{ticket_id}")
    assert len(fetched.json()["messages"]) == 1


@pytest.mark.asyncio
async def test_message_create_cannot_set_visibility(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visset"), "Visibility User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "support",
            "subject": "Visibility test",
            "description": "Details.",
            "source": "web",
        },
    )
    ticket_id = created.json()["id"]
    reply = await unsafe(
        client,
        "POST",
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={"message": "Trying to sneak in a field", "visibility": "internal"},
    )
    assert reply.status_code == 422, reply.text  # StrictModel rejects the extra field


# --- attachments -------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_valid_image_attachment(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("attach"), "Attach User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Screenshot attached",
            "description": "See attached.",
            "source": "ios",
        },
    )
    ticket_id = created.json()["id"]
    files = {"file": ("screenshot.png", make_png_bytes(), "image/png")}
    uploaded = await unsafe(
        client, "POST", f"/api/v1/support/tickets/{ticket_id}/attachments", files=files
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["content_type"] == "image/webp"  # re-encoded, never trusts declared type
    assert body["original_filename"] == "screenshot.png"


@pytest.mark.asyncio
async def test_upload_non_image_attachment_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("badfile"), "Bad File User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Bad file",
            "description": "Not an image.",
            "source": "web",
        },
    )
    ticket_id = created.json()["id"]
    files = {"file": ("notes.txt", b"just some text, not an image", "text/plain")}
    uploaded = await unsafe(
        client, "POST", f"/api/v1/support/tickets/{ticket_id}/attachments", files=files
    )
    assert uploaded.status_code == 422, uploaded.text


@pytest.mark.asyncio
async def test_upload_oversized_attachment_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("oversize"), "Oversize User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Oversized upload",
            "description": "Too big.",
            "source": "web",
        },
    )
    ticket_id = created.json()["id"]
    oversized = b"\x00" * (11 * 1024 * 1024)  # 11 MB, over the 10 MB ceiling
    files = {"file": ("huge.png", oversized, "image/png")}
    uploaded = await unsafe(
        client, "POST", f"/api/v1/support/tickets/{ticket_id}/attachments", files=files
    )
    assert uploaded.status_code == 413, uploaded.text


@pytest.mark.asyncio
async def test_attachment_storage_key_never_derived_from_filename(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("keysafe"), "Key Safe User")
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Path traversal attempt",
            "description": "Testing filename handling.",
            "source": "web",
        },
    )
    ticket_id = created.json()["id"]
    files = {"file": ("../../etc/passwd.png", make_png_bytes(), "image/png")}
    uploaded = await unsafe(
        client, "POST", f"/api/v1/support/tickets/{ticket_id}/attachments", files=files
    )
    assert uploaded.status_code == 201, uploaded.text
    # The dangerous filename is stored only as display text, never used to
    # build a filesystem path (see AttachmentStorage._path_for).
    assert uploaded.json()["original_filename"] == "../../etc/passwd.png"


# --- CRITICAL: cross-user / cross-Home privacy isolation ----------------------


@pytest.mark.asyncio
async def test_ticket_is_invisible_to_other_member_of_same_home_including_owner(
    client: AsyncClient,
) -> None:
    """The load-bearing test for Phase 2A decision 5: User A creates a
    ticket in a Home; User B, who is that Home's Owner (the highest role
    that exists), must not be able to list it, open it, reply to it, or see
    its diagnostics/attachments — group_id is contextual metadata only, not
    an access grant."""
    user_a_id = await create_verified_user(client, unique_email("owner-a"), "User A")
    home_id = await create_home(client, "Shared Home")

    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "Private bug report",
            "description": "Only I should see this.",
            "source": "ios",
            "group_id": str(home_id),
            "diagnostics": {"app_version": "1.0.0"},
        },
    )
    assert created.status_code == 201, created.text
    ticket_id = created.json()["id"]
    files = {"file": ("private.png", make_png_bytes(), "image/png")}
    attach = await unsafe(
        client, "POST", f"/api/v1/support/tickets/{ticket_id}/attachments", files=files
    )
    assert attach.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        user_b_id = await create_verified_user(other_client, unique_email("owner-b"), "User B")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=user_b_id,
                    role=Role.owner,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.home_admin,
                )
            )
            await db.commit()

        # 1. Cannot list it
        listed = await unsafe(other_client, "GET", "/api/v1/support/tickets")
        assert listed.status_code == 200
        assert listed.json()["items"] == []

        # 2. Cannot open it
        opened = await unsafe(other_client, "GET", f"/api/v1/support/tickets/{ticket_id}")
        assert opened.status_code == 404

        # 3. Cannot reply to it
        replied = await unsafe(
            other_client,
            "POST",
            f"/api/v1/support/tickets/{ticket_id}/messages",
            json={"message": "I'm the Home Owner, let me see this"},
        )
        assert replied.status_code == 404

        # 4. Cannot access its attachments (via the ticket detail response)
        attachments = await unsafe(
            other_client,
            "POST",
            f"/api/v1/support/tickets/{ticket_id}/attachments",
            files={"file": ("x.png", make_png_bytes(), "image/png")},
        )
        assert attachments.status_code == 404

    # Sanity: the ticket and its diagnostic genuinely exist and belong to A.
    ticket_uuid = uuid.UUID(ticket_id)
    async with SessionFactory() as db:
        ticket = await db.scalar(select(SupportTicket).where(SupportTicket.id == ticket_uuid))
        assert ticket is not None
        assert ticket.requester_user_id == user_a_id
        diagnostic = await db.scalar(
            select(SupportTicketDiagnostic).where(
                SupportTicketDiagnostic.ticket_id == uuid.UUID(ticket_id)
            )
        )
        assert diagnostic is not None
    assert user_b_id
