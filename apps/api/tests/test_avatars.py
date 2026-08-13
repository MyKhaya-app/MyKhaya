"""Tests for profile avatar upload/replace/remove: image validation and processing
(mykhaya/avatars/processing.py), storage (mykhaya/avatars/storage.py), and the
/users/me/avatar routes — authentication, size limits, format rejection, safe
replace-then-cleanup, and removal.
"""

import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from mykhaya.avatars.processing import (
    AVATAR_SIZE,
    OUTPUT_CONTENT_TYPE,
    UnsupportedImageError,
    process_avatar_upload,
)
from mykhaya.avatars.storage import LocalAvatarStorage
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


def make_jpeg(
    size: tuple[int, int] = (800, 600), colour: tuple[int, int, int] = (200, 50, 50)
) -> bytes:
    image = Image.new("RGB", size, colour)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def make_jpeg_with_orientation_exif() -> bytes:
    image = Image.new("RGB", (800, 600), (10, 200, 30))
    exif = image.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def make_png(size: tuple[int, int] = (400, 900)) -> bytes:
    image = Image.new("RGB", size, (30, 80, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
    suffix = uuid.uuid4().hex[:12]
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


# --- processing unit tests --------------------------------------------------


def test_process_avatar_upload_crops_resizes_and_strips_metadata() -> None:
    processed = process_avatar_upload(make_jpeg_with_orientation_exif())
    image = Image.open(io.BytesIO(processed))
    assert image.format == "WEBP"
    assert image.size == (AVATAR_SIZE, AVATAR_SIZE)
    assert not image.getexif()  # metadata was not carried over into the re-encode


def test_process_avatar_upload_accepts_png_and_produces_square_output() -> None:
    processed = process_avatar_upload(make_png((400, 900)))
    image = Image.open(io.BytesIO(processed))
    assert image.size == (AVATAR_SIZE, AVATAR_SIZE)


def test_process_avatar_upload_rejects_non_image_bytes() -> None:
    with pytest.raises(UnsupportedImageError):
        process_avatar_upload(b"not an image, just some bytes pretending to be one")


def test_process_avatar_upload_rejects_svg_masquerading_as_image() -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    with pytest.raises(UnsupportedImageError):
        process_avatar_upload(svg)


# --- storage unit tests ------------------------------------------------------


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    await storage.save("one.webp", b"hello")
    assert await storage.load("one.webp") == b"hello"
    await storage.delete("one.webp")
    assert await storage.load("one.webp") is None


@pytest.mark.asyncio
async def test_local_storage_load_missing_key_returns_none(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    assert await storage.load("missing.webp") is None


@pytest.mark.asyncio
async def test_local_storage_rejects_path_traversal_key(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    with pytest.raises(ValueError, match="Invalid avatar storage key"):
        await storage.save("../escape.webp", b"nope")


# --- API: authentication -----------------------------------------------------


@pytest.mark.asyncio
async def test_upload_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users/me/avatar", files={"file": ("photo.jpg", make_jpeg(), "image/jpeg")}
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_avatar_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/users/{uuid.uuid4()}/avatar")
    assert response.status_code in (401, 403)


# --- API: upload validation ---------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_non_image_and_svg_and_oversized(client: AsyncClient) -> None:
    """One registered user, three distinct rejection paths — the server never trusts
    the client's Content-Type (SVG is sent as image/svg+xml but still rejected)."""
    await create_verified_user(client, unique_email("badupload"), "Bad Upload")

    not_an_image = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", b"definitely not an image", "image/jpeg")},
    )
    assert not_an_image.status_code == 422
    assert "image" in not_an_image.json()["detail"].lower()

    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    svg_response = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.svg", svg, "image/svg+xml")},
    )
    assert svg_response.status_code == 422

    settings = get_settings()
    oversized = b"\x00" * (settings.avatar_max_upload_bytes + 1)
    oversized_response = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", oversized, "image/jpeg")},
    )
    assert oversized_response.status_code == 413


# --- API: successful upload, persistence, generated filename ------------------


@pytest.mark.asyncio
async def test_successful_upload_persists_and_serves_processed_image(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("goodupload"), "Good Upload")

    before = await client.get(f"/api/v1/users/{user_id}/avatar")
    assert before.status_code == 404

    upload = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("my-holiday-photo.jpg", make_jpeg(), "image/jpeg")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["avatar_version"]
    # The stored reference is a server-generated UUID-based filename, never the
    # client's original filename.
    assert "my-holiday-photo" not in body["avatar_version"]
    uuid.UUID(body["avatar_version"].removesuffix(".webp"))  # does not raise

    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        assert user.avatar_key == body["avatar_version"]
        assert user.avatar_updated_at is not None

    fetched = await client.get(f"/api/v1/users/{user_id}/avatar")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == OUTPUT_CONTENT_TYPE
    image = Image.open(io.BytesIO(fetched.content))
    assert image.size == (AVATAR_SIZE, AVATAR_SIZE)


@pytest.mark.asyncio
async def test_user_can_always_view_their_own_avatar(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("selfview"), "Self View")
    await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )
    response = await client.get(f"/api/v1/users/{user_id}/avatar")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_household_member_can_view_shared_avatar(client: AsyncClient) -> None:
    """Avatar visibility follows the same rule as GET /groups/{id}/members
    (Capability.members_view) — the target's UUID being unguessable is not treated
    as the access control."""
    owner_id = await create_verified_user(client, unique_email("ownerav"), "Owner Av")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Avatar Home"})
    home_id = uuid.UUID(home.json()["id"])
    await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as member_client:
        member_id = await create_verified_user(
            member_client, unique_email("member"), "Household Member"
        )
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=member_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        response = await member_client.get(f"/api/v1/users/{owner_id}/avatar")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_unrelated_user_cannot_view_avatar_and_gets_generic_not_found(
    client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(client, unique_email("ownerav2"), "Owner Av Two")
    await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as stranger_client:
        await create_verified_user(stranger_client, unique_email("strangerav"), "Stranger Av")
        with_avatar = await stranger_client.get(f"/api/v1/users/{owner_id}/avatar")
        without_avatar = await stranger_client.get(f"/api/v1/users/{uuid.uuid4()}/avatar")
        assert with_avatar.status_code == 404
        assert without_avatar.status_code == 404
        # Same response either way — no side-channel revealing whether the target
        # user (or their avatar) actually exists.
        assert with_avatar.json() == without_avatar.json()


# --- API: replace safety -------------------------------------------------------


@pytest.mark.asyncio
async def test_replacing_avatar_deletes_previous_file_and_serves_new_one(
    client: AsyncClient,
) -> None:
    settings = get_settings()
    storage = LocalAvatarStorage(Path(settings.avatar_storage_dir))

    await create_verified_user(client, unique_email("replace"), "Replace Me")
    first = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("first.jpg", make_jpeg(colour=(200, 0, 0)), "image/jpeg")},
    )
    assert first.status_code == 200, first.text
    first_version = first.json()["avatar_version"]

    second = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("second.png", make_png(), "image/png")},
    )
    assert second.status_code == 200, second.text
    second_version = second.json()["avatar_version"]

    assert first_version != second_version
    assert await storage.load(first_version) is None  # previous file cleaned up
    assert await storage.load(second_version) is not None


@pytest.mark.asyncio
async def test_failed_replacement_does_not_delete_existing_avatar(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("keepold"), "Keep Old")
    good = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("good.jpg", make_jpeg(), "image/jpeg")},
    )
    assert good.status_code == 200
    good_version = good.json()["avatar_version"]

    failed = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
    )
    assert failed.status_code == 422

    me = await client.get("/api/v1/users/me")
    assert me.json()["avatar_version"] == good_version

    settings = get_settings()
    storage = LocalAvatarStorage(Path(settings.avatar_storage_dir))
    assert await storage.load(good_version) is not None


# --- API: removal ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_avatar_resets_to_initials_and_deletes_file(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("removeav"), "Remove Av")
    uploaded = await unsafe(
        client,
        "POST",
        "/api/v1/users/me/avatar",
        files={"file": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )
    version = uploaded.json()["avatar_version"]

    removed = await unsafe(client, "DELETE", "/api/v1/users/me/avatar")
    assert removed.status_code == 200
    assert removed.json()["avatar_version"] is None

    settings = get_settings()
    storage = LocalAvatarStorage(Path(settings.avatar_storage_dir))
    assert await storage.load(version) is None

    # Removing again (nothing left to remove) is a safe no-op, not an error.
    removed_again = await unsafe(client, "DELETE", "/api/v1/users/me/avatar")
    assert removed_again.status_code == 200
    assert removed_again.json()["avatar_version"] is None
