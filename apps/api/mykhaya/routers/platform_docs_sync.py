"""Platform Control Centre: BookStack documentation sync (mykhaya.docs_sync).

Owner/Administrator only, for reading as well as changing: the page shows
where internal documentation is published. Every change needs recent
authentication and an audit reason. The token secret is write-only: it is
never returned, logged or audited. These routes live under /platform, so
they inherit the Control Centre's session, CSRF and network-allowlist
protection; no new public endpoint is introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya import docs_sync
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_schemas import SensitiveActionRequest
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles
from mykhaya.routers.platform import OPERATORS

router = APIRouter(prefix="/platform/docs-sync", tags=["platform-docs-sync"])


class ConnectionUpdate(SensitiveActionRequest):
    url: str = Field(min_length=8, max_length=300)
    token_id: str = Field(min_length=1, max_length=200)
    # Blank keeps the stored secret, but only while the URL is unchanged.
    token_secret: str | None = Field(default=None, max_length=500)
    repository_url: str | None = Field(default=None, max_length=300)
    include_paths: list[str] = Field(default_factory=list, max_length=20)


class BookSelection(SensitiveActionRequest):
    book_id: int = Field(ge=1)


class AutoSync(SensitiveActionRequest):
    enabled: bool


class Action(SensitiveActionRequest):
    pass


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


@router.get("")
async def overview(
    _: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    state = await docs_sync.load(db, docs_sync.STATUS_KEY)
    source: dict[str, Any]
    try:
        docs = docs_sync.discover(settings, config)
        source = {"available": True, "documents": len(docs)}
        pending = docs_sync.source_hash(docs) != state.get("last_synced_hash")
    except docs_sync.SyncError as exc:
        source = {"available": False, "error": str(exc)}
        pending = False
    return {
        "environment": settings.environment,
        "branch": docs_sync.source_branch(settings),
        "url": config.get("url"),
        "token_id": config.get("token_id"),
        "has_token_secret": bool(config.get("token_secret_encrypted")),
        "repository_url": config.get("repository_url"),
        "include_paths": config.get("include_paths") or [],
        "book_id": config.get("book_id"),
        "book_name": config.get("book_name"),
        "auto_enabled": bool(config.get("auto_enabled")),
        "configured": docs_sync.is_configured(config),
        "connection": state.get("connection"),
        "last_success_at": state.get("last_success_at"),
        "last_run": state.get("last_run"),
        "sync_requested": bool(state.get("requested")),
        "changes_pending": pending,
        "source": source,
    }


@router.put("/connection")
async def save_connection(
    body: ConnectionUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    try:
        url = await docs_sync.validate_bookstack_url(body.url)
    except docs_sync.SyncError as exc:
        raise _bad_request(str(exc)) from exc
    repository_url = (body.repository_url or "").strip().rstrip("/") or None
    if repository_url and not repository_url.startswith("https://"):
        raise _bad_request("The repository URL must start with https://.")
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    url_changed = config.get("url") != url
    secret = (body.token_secret or "").strip()
    if not secret and (url_changed or not config.get("token_secret_encrypted")):
        # Never send a stored token to a newly entered host.
        raise _bad_request("Enter the token secret (required when the URL changes).")
    previous = {"url": config.get("url"), "token_id": config.get("token_id")}
    config.update(
        url=url,
        token_id=body.token_id.strip(),
        repository_url=repository_url,
        include_paths=[p.strip().strip("/") for p in body.include_paths if p.strip().strip("/")],
    )
    if secret:
        config["token_secret_encrypted"] = docs_sync.encrypt_token_secret(settings, secret)
    if url_changed:
        # A different instance: the previous book selection does not apply,
        # and automatic sync waits for a book to be chosen again.
        config.update(book_id=None, book_name=None, auto_enabled=False)
    await docs_sync.store(db, docs_sync.CONFIG_KEY, config, context.administrator.id)
    platform_audit(
        db,
        request,
        context,
        "docs_sync.connection_updated",
        "setting",
        reason=body.reason,
        previous=previous,
        new={"url": url, "token_id": config["token_id"], "token_secret_changed": bool(secret)},
    )
    await db.commit()
    return {"saved": True, "book_cleared": url_changed}


async def _client(db: AsyncSession, settings: Settings) -> docs_sync.BookStack:
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    try:
        return docs_sync.client_for(settings, config)
    except docs_sync.SyncError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/test")
async def test_connection(
    body: Action,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    client = await _client(db, settings)
    try:
        books = await client.list_books()
        result = {"ok": True, "message": f"Connected. {len(books)} book(s) visible to this token."}
    except (docs_sync.SyncError, LookupError) as exc:
        message = str(exc) if isinstance(exc, docs_sync.SyncError) else "BookStack API not found."
        result = {"ok": False, "message": message}
    state = await docs_sync.load(db, docs_sync.STATUS_KEY)
    state["connection"] = {**result, "checked_at": datetime.now(UTC).isoformat()}
    await docs_sync.store(db, docs_sync.STATUS_KEY, state)
    platform_audit(
        db,
        request,
        context,
        "docs_sync.connection_tested",
        "setting",
        reason=body.reason,
        new={"ok": result["ok"]},
    )
    await db.commit()
    return result


@router.get("/books")
async def list_books(
    _: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    client = await _client(db, settings)
    try:
        return {"books": await client.list_books()}
    except (docs_sync.SyncError, LookupError) as exc:
        message = str(exc) if isinstance(exc, docs_sync.SyncError) else "BookStack API not found."
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, message) from exc


@router.put("/book")
async def select_book(
    body: BookSelection,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    client = await _client(db, settings)
    try:
        books = {book["id"]: book["name"] for book in await client.list_books()}
    except (docs_sync.SyncError, LookupError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not load BookStack books.") from exc
    if body.book_id not in books:
        raise _bad_request("That book is not visible to the configured token.")
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    previous = {"book_id": config.get("book_id"), "book_name": config.get("book_name")}
    config.update(book_id=body.book_id, book_name=books[body.book_id])
    await docs_sync.store(db, docs_sync.CONFIG_KEY, config, context.administrator.id)
    platform_audit(
        db,
        request,
        context,
        "docs_sync.book_selected",
        "setting",
        reason=body.reason,
        previous=previous,
        new={"book_id": body.book_id, "book_name": books[body.book_id]},
    )
    await db.commit()
    return {"book_id": body.book_id, "book_name": books[body.book_id]}


@router.put("/auto")
async def set_auto_sync(
    body: AutoSync,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    if body.enabled and not docs_sync.is_configured(config):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Configure the connection and a book before enabling."
        )
    config["auto_enabled"] = body.enabled
    await docs_sync.store(db, docs_sync.CONFIG_KEY, config, context.administrator.id)
    platform_audit(
        db,
        request,
        context,
        "docs_sync.auto_enabled" if body.enabled else "docs_sync.auto_disabled",
        "setting",
        reason=body.reason,
    )
    await db.commit()
    return {"auto_enabled": body.enabled}


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def request_sync(
    body: Action,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Queues a sync; the scheduler runs it within about 30 seconds (a full
    first sync can take a minute or two, so it is not run in the request)."""
    require_recent_auth(context, settings)
    config = await docs_sync.load(db, docs_sync.CONFIG_KEY)
    if not docs_sync.is_configured(config):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Configure the connection and a book before syncing."
        )
    state = await docs_sync.load(db, docs_sync.STATUS_KEY)
    state["requested"] = True
    await docs_sync.store(db, docs_sync.STATUS_KEY, state)
    platform_audit(
        db,
        request,
        context,
        "docs_sync.sync_requested",
        "setting",
        reason=body.reason,
        new={"book_id": config.get("book_id")},
    )
    await db.commit()
    return {"requested": True}
