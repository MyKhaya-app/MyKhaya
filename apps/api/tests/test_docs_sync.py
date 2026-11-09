"""Focused checks for the BookStack documentation sync (mykhaya.docs_sync)
against an in-memory fake BookStack (httpx.MockTransport). No real BookStack
or network access is involved."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from test_platform_control_centre import admin_client, admin_factory, login, unsafe  # noqa: F401

from mykhaya import docs_sync
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import PlatformAdministrator, PlatformRole, PlatformSetting

SECRET = "bookstack-token-secret-never-shown"


class FakeBookStack:
    def __init__(self) -> None:
        self.books = [{"id": 7, "name": "Engineering"}, {"id": 9, "name": "Other"}]
        self.pages: dict[int, dict[str, Any]] = {}
        self.chapters: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.reject = False
        self.next_id = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if self.reject or request.headers.get("authorization") != f"Token tid:{SECRET}":
            return httpx.Response(401, json={"error": "unauthorised"})
        path = request.url.path.removeprefix("/api/")
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET" and path == "books":
            return httpx.Response(200, json={"data": self.books})
        if request.method == "POST" and path == "chapters":
            self.next_id += 1
            self.chapters[self.next_id] = body
            return httpx.Response(200, json={"id": self.next_id})
        if request.method == "POST" and path == "pages":
            self.next_id += 1
            self.pages[self.next_id] = body
            return httpx.Response(200, json={"id": self.next_id})
        if request.method == "PUT" and path.startswith("pages/"):
            page_id = int(path.split("/")[1])
            if page_id not in self.pages:
                return httpx.Response(404, json={})
            self.pages[page_id].update(body)
            return httpx.Response(200, json={"id": page_id})
        return httpx.Response(404, json={})


@pytest.fixture
def docs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "docs"
    (root / "architecture").mkdir(parents=True)
    (root / "operations").mkdir()
    (root / "README.md").write_text("# Overview\n\nSee [ops](operations/runbook.md).\n")
    (root / "architecture" / "status.md").write_text(
        "# Status\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nprint(1)\n```\n"
    )
    (root / "operations" / "runbook.md").write_text("# Status\n\nRunbook body.\n")
    monkeypatch.setattr(get_settings(), "docs_sync_source_dir", str(root))
    monkeypatch.setattr(docs_sync, "WRITE_PAUSE_SECONDS", 0)
    return root


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBookStack:
    fake = FakeBookStack()
    monkeypatch.setattr(docs_sync, "_transport_override", httpx.MockTransport(fake.handler))

    # The test container has no public DNS; treat the fake host as public.
    def allow_public(url: str) -> str | None:
        return None if "bookstack.example.com" in url else "blocked_ip"

    monkeypatch.setattr(docs_sync, "_validate_target", allow_public)
    return fake


@pytest.fixture
async def clean_sync_state(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],  # noqa: F811
) -> AsyncIterator[Callable[[PlatformRole], Awaitable[PlatformAdministrator]]]:
    keys = [docs_sync.CONFIG_KEY, docs_sync.STATUS_KEY, docs_sync.PAGES_KEY]

    async def wipe() -> None:
        async with SessionFactory() as db:
            await db.execute(delete(PlatformSetting).where(PlatformSetting.key.in_(keys)))
            await db.commit()

    await wipe()
    yield admin_factory
    await wipe()


async def configure(book_id: int | None = 7, **extra: Any) -> None:
    async with SessionFactory() as db:
        await docs_sync.store(
            db,
            docs_sync.CONFIG_KEY,
            {
                "url": "https://bookstack.example.com",
                "token_id": "tid",
                "token_secret_encrypted": docs_sync.encrypt_token_secret(get_settings(), SECRET),
                "book_id": book_id,
                "book_name": "Engineering",
                "repository_url": "https://github.com/example/repo",
                **extra,
            },
        )
        await db.commit()


# --- URL safety, discovery and branch -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://bookstack.example.com",
        "https://user:pw@bookstack.example.com",
        "https://10.0.0.5",
        "https://127.0.0.1",
        "https://169.254.169.254",
    ],
)
async def test_unsafe_bookstack_urls_are_rejected(url: str) -> None:
    with pytest.raises(docs_sync.SyncError):
        await docs_sync.validate_bookstack_url(url)


def test_discovery_handles_duplicates_chapters_links_and_notice(docs_root: Path) -> None:
    docs = {
        doc.path: doc
        for doc in docs_sync.discover(
            get_settings(), {"repository_url": "https://github.com/example/repo"}
        )
    }
    assert docs["architecture/status.md"].name == "Status (architecture/status.md)"
    assert docs["operations/runbook.md"].name == "Status (operations/runbook.md)"
    assert docs["architecture/status.md"].chapter == "Architecture"
    assert docs["README.md"].chapter is None
    readme = docs["README.md"].markdown
    assert "https://github.com/example/repo/blob/dev/docs/operations/runbook.md" in readme
    assert "on the `dev` branch" in readme
    assert "| a | b |" in docs["architecture/status.md"].markdown
    assert "```py" in docs["architecture/status.md"].markdown
    assert not docs["README.md"].markdown.startswith("# Overview")


def test_branch_follows_environment_and_never_shares_state() -> None:
    settings = get_settings()
    assert (
        docs_sync.source_branch(settings.model_copy(update={"environment": "production"})) == "main"
    )
    assert (
        docs_sync.source_branch(settings.model_copy(update={"environment": "development"})) == "dev"
    )
    # Associations are scoped to instance host + book, so a PROD (or other)
    # instance can never reuse DEV page IDs.
    dev = docs_sync.association_key({"url": "https://docs-dev.example.com", "book_id": 7})
    prod = docs_sync.association_key({"url": "https://docs.example.com", "book_id": 7})
    assert dev != prod


# --- publishing ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_creates_then_skips_then_updates_without_duplicates(
    docs_root: Path, fake: FakeBookStack, clean_sync_state: Any
) -> None:
    await configure()
    first = await docs_sync.run_sync(get_settings(), trigger="manual")
    assert first["status"] == "succeeded", first
    assert (first["created"], first["updated"], first["skipped"]) == (3, 0, 0)
    assert len(fake.chapters) == 2 and len(fake.pages) == 3

    second = await docs_sync.run_sync(get_settings(), trigger="manual")
    assert (second["created"], second["updated"], second["skipped"]) == (0, 0, 3)

    (docs_root / "architecture" / "status.md").write_text("# Status\n\nChanged.\n")
    third = await docs_sync.run_sync(get_settings(), trigger="automatic")
    assert (third["created"], third["updated"], third["skipped"]) == (0, 1, 2)
    assert len(fake.pages) == 3  # updated in place, no duplicate
    assert any("Changed." in page["markdown"] for page in fake.pages.values())
    # Nothing is ever deleted.
    assert not any(method == "DELETE" for method, _ in fake.calls)


@pytest.mark.asyncio
async def test_page_deleted_in_bookstack_is_recreated_and_new_book_is_fresh(
    docs_root: Path, fake: FakeBookStack, clean_sync_state: Any
) -> None:
    await configure()
    await docs_sync.run_sync(get_settings(), trigger="manual")
    readme_id = next(pid for pid, page in fake.pages.items() if page["name"] == "Overview")
    del fake.pages[readme_id]
    (docs_root / "README.md").write_text("# Overview\n\nEdited.\n")
    result = await docs_sync.run_sync(get_settings(), trigger="manual")
    assert result["created"] == 1 and result["skipped"] == 2

    # Switching book never touches pages published to the old one.
    old_pages = dict(fake.pages)
    await configure(book_id=9)
    switched = await docs_sync.run_sync(get_settings(), trigger="manual")
    assert switched["created"] == 3
    for page_id, page in old_pages.items():
        assert fake.pages[page_id] == page


@pytest.mark.asyncio
async def test_failure_is_recorded_safely_and_unconfigured_does_nothing(
    docs_root: Path, fake: FakeBookStack, clean_sync_state: Any
) -> None:
    await docs_sync.tick(get_settings())  # unconfigured: no calls at all
    assert fake.calls == []
    await configure()
    fake.reject = True
    result = await docs_sync.run_sync(get_settings(), trigger="manual")
    assert result["status"] == "failed"
    assert "rejected the API token" in result["error"]
    assert SECRET not in json.dumps(result)


# --- PCC endpoints -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pcc_flow_connect_test_select_book_and_request_sync(
    docs_root: Path,
    fake: FakeBookStack,
    clean_sync_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    owner = await clean_sync_state(PlatformRole.owner)
    await login(admin_client, owner)
    base = "/api/v1/platform/docs-sync"
    initial = (await admin_client.get(base)).json()
    assert initial["configured"] is False and initial["auto_enabled"] is False
    assert (
        await unsafe(
            admin_client,
            "POST",
            f"{base}/sync",
            json={"reason": "Try before setup", "confirmed": True},
        )
    ).status_code == 409

    saved = await unsafe(
        admin_client,
        "PUT",
        f"{base}/connection",
        json={
            "url": "https://bookstack.example.com/",
            "token_id": "tid",
            "token_secret": SECRET,
            "repository_url": "https://github.com/example/repo",
            "reason": "Configure DEV BookStack",
            "confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    tested = await unsafe(
        admin_client,
        "POST",
        f"{base}/test",
        json={"reason": "Check token works", "confirmed": True},
    )
    assert tested.json()["ok"] is True
    books = (await admin_client.get(f"{base}/books")).json()["books"]
    assert {book["name"] for book in books} == {"Engineering", "Other"}
    bad = await unsafe(
        admin_client,
        "PUT",
        f"{base}/book",
        json={"book_id": 999, "reason": "Pick a missing book", "confirmed": True},
    )
    assert bad.status_code == 422
    picked = await unsafe(
        admin_client,
        "PUT",
        f"{base}/book",
        json={"book_id": 7, "reason": "Publish to Engineering", "confirmed": True},
    )
    assert picked.json()["book_name"] == "Engineering"
    queued = await unsafe(
        admin_client, "POST", f"{base}/sync", json={"reason": "First publish", "confirmed": True}
    )
    assert queued.status_code == 202

    overview = await admin_client.get(base)
    assert SECRET not in overview.text
    assert overview.json()["has_token_secret"] is True and overview.json()["sync_requested"] is True

    # Changing the URL without re-entering the secret is refused (the stored
    # token must never be sent to a new host).
    moved = await unsafe(
        admin_client,
        "PUT",
        f"{base}/connection",
        json={
            "url": "https://other.bookstack.example.com",
            "token_id": "tid",
            "reason": "Move instance",
            "confirmed": True,
        },
    )
    assert moved.status_code == 422


@pytest.mark.asyncio
async def test_non_operators_cannot_view_or_change_docs_sync(
    clean_sync_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    viewer = await clean_sync_state(PlatformRole.support)
    await login(admin_client, viewer)
    assert (await admin_client.get("/api/v1/platform/docs-sync")).status_code == 403
    denied = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/docs-sync/connection",
        json={
            "url": "https://bookstack.example.com",
            "token_id": "x",
            "token_secret": "y",
            "reason": "Not allowed here",
            "confirmed": True,
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_periodic_check_is_local_only_and_caches_the_hash(
    docs_root: Path, fake: FakeBookStack, clean_sync_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(auto_enabled=True)
    await docs_sync.run_sync(get_settings(), trigger="manual")
    fake.calls.clear()
    monkeypatch.setattr(docs_sync, "_hash_cache", None)
    reads: list[int] = []
    real_discover = docs_sync.discover

    def counting_discover(*args: Any) -> Any:
        reads.append(1)
        return real_discover(*args)

    monkeypatch.setattr(docs_sync, "discover", counting_discover)
    for _ in range(3):
        await docs_sync.tick(get_settings())
    assert fake.calls == []  # nothing changed: no BookStack request at all
    assert len(reads) == 1  # files read and hashed once, then only stat()ed
