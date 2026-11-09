"""One-way documentation publishing: bundled repository docs -> BookStack.

The Markdown under ``docs/`` is copied into the API image at build time, so a
DEV image carries the ``dev`` branch's docs and a PROD image carries ``main``'s
(see apps/api/Dockerfile). No GitHub access or token is involved. A background
loop in the scheduler publishes them to the BookStack book an administrator
selected in PCC, when (a) automatic sync is enabled and the bundled docs'
content hash has changed since the last successful sync, or (b) an
administrator pressed "Sync now".

Safety rules:
- Configuration, credentials, page associations and status live in this
  environment's own database (PlatformSetting rows), so DEV and PROD never
  share or inherit anything. Nothing is configured by default.
- The token secret is encrypted at rest and never returned, logged or audited.
- The BookStack URL must be public HTTPS; every request re-validates the
  resolved addresses with the same SSRF guard used for link previews, and
  redirects are never followed.
- Only pages this publisher created (tracked by ID per instance+book) are ever
  updated. Nothing is deleted. Changing the URL or book starts a fresh
  association set rather than touching earlier pages.
- A failure is recorded in the status and never affects other MyKhaya work.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.db import SessionFactory
from mykhaya.models import PlatformSetting
from mykhaya.secrets_crypto import decrypt_secret, encrypt_secret
from mykhaya.wishlist_link_preview import _validate_target

log = structlog.get_logger()

CONFIG_KEY = "bookstack_sync"
STATUS_KEY = "bookstack_sync_status"
PAGES_KEY = "bookstack_sync_pages"
_SECRET_INFO = b"mykhaya-bookstack-token-v1"
_LOCK_KEY = 0x4D4B444F4353  # "MKDOCS"
LOOP_SECONDS = 30
RETRY_BACKOFF_SECONDS = 15 * 60
WRITE_PAUSE_SECONDS = 0.4  # stays under BookStack's default 180 requests/minute
TIMEOUT = httpx.Timeout(15.0)
USER_AGENT = "MyKhaya-DocsSync/1.0"


class SyncError(Exception):
    """A safe, operator-readable failure (never contains the token)."""


# --- configuration ---------------------------------------------------------------------


async def validate_bookstack_url(value: str) -> str:
    """Public HTTPS only: no credentials, query or fragment, and every
    resolved address must pass the existing SSRF guard."""
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise SyncError("The BookStack URL must start with https://.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SyncError("The BookStack URL must not contain credentials, a query or a fragment.")
    # Blocking DNS resolution: kept off the event loop.
    if await asyncio.to_thread(_validate_target, value) is not None:
        raise SyncError("The BookStack URL must resolve only to public internet addresses.")
    return value


async def _get_row(db: AsyncSession, key: str, *, lock: bool = False) -> PlatformSetting | None:
    query = select(PlatformSetting).where(PlatformSetting.key == key)
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def load(db: AsyncSession, key: str) -> dict[str, Any]:
    row = await _get_row(db, key)
    return dict((row.value if row else {}).get("value") or {})


async def store(
    db: AsyncSession, key: str, value: dict[str, Any], administrator_id: Any = None
) -> None:
    row = await _get_row(db, key, lock=True)
    if row is None:
        db.add(PlatformSetting(key=key, value={"value": value}, updated_by=administrator_id))
    else:
        row.value = {"value": value}
        if administrator_id is not None:
            row.updated_by = administrator_id


def encrypt_token_secret(settings: Settings, secret: str) -> str:
    return encrypt_secret(settings, secret, info=_SECRET_INFO)


def association_key(config: dict[str, Any]) -> str:
    """Associations are scoped to instance host + book, so a different
    instance or book never reuses (and so never overwrites) earlier pages."""
    return f"{urlsplit(config.get('url', '')).hostname}|{config.get('book_id')}"


def is_configured(config: dict[str, Any]) -> bool:
    return bool(
        config.get("url")
        and config.get("token_id")
        and config.get("token_secret_encrypted")
        and config.get("book_id")
    )


def source_branch(settings: Settings) -> str:
    return settings.docs_sync_branch or ("main" if settings.environment == "production" else "dev")


# --- BookStack client ----------------------------------------------------------------------


@dataclass
class BookStack:
    url: str
    token_id: str
    token_secret: str
    transport: httpx.AsyncBaseTransport | None = None

    async def request(self, method: str, path: str, json: Any = None) -> Any:
        # Re-validated on every call: DNS can change after configuration.
        if await asyncio.to_thread(_validate_target, self.url) is not None:
            raise SyncError("The BookStack URL no longer resolves to a permitted address.")
        headers = {
            "Authorization": f"Token {self.token_id}:{self.token_secret}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, follow_redirects=False, transport=self.transport
            ) as client:
                response = await client.request(
                    method, f"{self.url}/api/{path}", headers=headers, json=json
                )
        except httpx.TimeoutException as exc:
            raise SyncError("BookStack did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise SyncError("Could not connect to BookStack.") from exc
        if response.status_code in (401, 403):
            raise SyncError(
                "BookStack rejected the API token, or it lacks permission for this action."
            )
        if response.status_code == 404:
            raise LookupError(path)
        if response.status_code == 429:
            raise SyncError("BookStack rate limit reached; the next run will continue.")
        if response.status_code >= 300:
            raise SyncError(f"BookStack returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise SyncError("BookStack returned an unexpected (non-JSON) response.") from exc

    async def list_books(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "books?count=500&sort=+name")
        return [
            {"id": int(item["id"]), "name": str(item["name"])}
            for item in data.get("data", [])
            if isinstance(item, dict) and "id" in item and "name" in item
        ]


def client_for(settings: Settings, config: dict[str, Any]) -> BookStack:
    if not (config.get("url") and config.get("token_id") and config.get("token_secret_encrypted")):
        raise SyncError("BookStack is not configured.")
    return BookStack(
        url=config["url"],
        token_id=config["token_id"],
        token_secret=decrypt_secret(settings, config["token_secret_encrypted"], info=_SECRET_INFO),
        transport=_transport_override,
    )


# Tests replace this with an httpx.MockTransport; always None in production.
_transport_override: httpx.AsyncBaseTransport | None = None


# --- documents ---------------------------------------------------------------------------


@dataclass
class Doc:
    path: str  # relative to the docs root, POSIX
    name: str
    chapter: str | None
    markdown: str
    digest: str = field(default="")


_H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_MD_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+?\.md)(#[^)\s]*)?\)")


def _title_from_path(path: str) -> str:
    return Path(path).stem.replace("-", " ").replace("_", " ").strip().capitalize() or path


def discover(settings: Settings, config: dict[str, Any]) -> list[Doc]:
    root = Path(settings.docs_sync_source_dir)
    if not root.is_dir():
        raise SyncError("The bundled documentation folder is missing from this build.")
    include = [p.strip("/") for p in config.get("include_paths") or [] if p.strip("/")]
    branch = source_branch(settings)
    repo = (config.get("repository_url") or "").rstrip("/")
    docs: list[Doc] = []
    for file in sorted(root.rglob("*.md")):
        rel = file.relative_to(root).as_posix()
        if include and not any(rel == p or rel.startswith(p + "/") for p in include):
            continue
        body = file.read_text(encoding="utf-8", errors="replace")
        heading = _H1.search(body)
        name = heading.group(1).strip() if heading else _title_from_path(rel)
        if heading:
            body = body[: heading.start()] + body[heading.end() :]
        folder = rel.split("/", 1)[0] if "/" in rel else None

        def link(match: re.Match[str], rel: str = rel) -> str:
            if not repo:
                return match.group(0)
            target = (Path("docs") / Path(rel).parent / match.group(1)).as_posix()
            parts: list[str] = []
            for part in target.split("/"):
                if part == "..":
                    parts = parts[:-1]
                elif part not in ("", "."):
                    parts.append(part)
            return f"]({repo}/blob/{branch}/{'/'.join(parts)}{match.group(2) or ''})"

        body = _MD_LINK.sub(link, body).strip()
        source = f"docs/{rel}"
        source_ref = f"[{source}]({repo}/blob/{branch}/{source})" if repo else f"`{source}`"
        notice = (
            f"> Published automatically from {source_ref} on the `{branch}` branch of the "
            "MyKhaya repository. Edit the source in GitHub: changes made here are replaced "
            "on the next sync."
        )
        docs.append(
            Doc(
                rel,
                name[:255],
                folder.replace("-", " ").title() if folder else None,
                f"{notice}\n\n{body}\n",
            )
        )
    # Duplicate top-level headings: disambiguate every clash with its path.
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.name.casefold()] = counts.get(doc.name.casefold(), 0) + 1
    for doc in docs:
        if counts[doc.name.casefold()] > 1:
            doc.name = f"{doc.name} ({doc.path})"[:255]
        doc.digest = hashlib.sha256(
            f"{doc.name}\n{doc.chapter}\n{doc.markdown}".encode()
        ).hexdigest()
    return docs


def source_hash(docs: list[Doc]) -> str:
    return hashlib.sha256("".join(f"{d.path}:{d.digest}\n" for d in docs).encode()).hexdigest()


# --- publishing --------------------------------------------------------------------------


@dataclass
class Result:
    created: int = 0
    updated: int = 0
    skipped: int = 0


async def publish(
    client: BookStack, docs: list[Doc], book_id: int, pages: dict[str, Any], save: Any
) -> Result:
    """Create or update each doc. `pages` is this instance+book's persistent
    association map ({"pages": {path: {id, digest}}, "chapters": {name: id}});
    `save` persists it after every write so a crash can never cause
    duplicates on the next run."""
    result = Result()
    page_map: dict[str, Any] = pages.setdefault("pages", {})
    chapters: dict[str, Any] = pages.setdefault("chapters", {})
    for doc in docs:
        known = page_map.get(doc.path)
        if known and known.get("digest") == doc.digest:
            result.skipped += 1
            continue
        payload = {"name": doc.name, "markdown": doc.markdown}
        if known:
            try:
                await client.request("PUT", f"pages/{int(known['id'])}", payload)
                known["digest"] = doc.digest
                result.updated += 1
                await save()
                await asyncio.sleep(WRITE_PAUSE_SECONDS)
                continue
            except LookupError:
                pass  # our page was deleted in BookStack: recreate it below
        if doc.chapter:
            chapter_id = chapters.get(doc.chapter)
            if chapter_id is None:
                created = await client.request(
                    "POST", "chapters", {"book_id": book_id, "name": doc.chapter}
                )
                chapter_id = chapters[doc.chapter] = int(created["id"])
                await save()
                await asyncio.sleep(WRITE_PAUSE_SECONDS)
            target = {"chapter_id": chapter_id}
        else:
            target = {"book_id": book_id}
        try:
            created = await client.request("POST", "pages", {**target, **payload})
        except LookupError:
            # The chapter we created earlier was deleted: fall back to the book.
            chapters.pop(doc.chapter or "", None)
            created = await client.request("POST", "pages", {"book_id": book_id, **payload})
        page_map[doc.path] = {"id": int(created["id"]), "digest": doc.digest}
        result.created += 1
        await save()
        await asyncio.sleep(WRITE_PAUSE_SECONDS)
    return result


async def run_sync(settings: Settings, *, trigger: str) -> dict[str, Any]:
    """One full sync under an advisory lock. Always records a status."""
    async with SessionFactory() as lock_db:
        if not await lock_db.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}):
            return {"status": "already_running"}
        try:
            return await _locked_sync(settings, trigger)
        finally:
            await lock_db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            await lock_db.commit()


async def _locked_sync(settings: Settings, trigger: str) -> dict[str, Any]:
    started = datetime.now(UTC)
    async with SessionFactory() as db:
        config = await load(db, CONFIG_KEY)
        status = await load(db, STATUS_KEY)
        all_pages = await load(db, PAGES_KEY)
    key = association_key(config)
    pages: dict[str, Any] = all_pages.setdefault(key, {})

    async def save() -> None:
        async with SessionFactory() as db:
            await store(db, PAGES_KEY, all_pages)
            await db.commit()

    outcome: dict[str, Any] = {"trigger": trigger, "started_at": started.isoformat()}
    try:
        if not is_configured(config):
            raise SyncError("BookStack is not fully configured (URL, token and book).")
        docs = discover(settings, config)
        result = await publish(
            client_for(settings, config), docs, int(config["book_id"]), pages, save
        )
        outcome.update(
            status="succeeded",
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            error=None,
            source_hash=source_hash(docs),
        )
        status["last_success_at"] = datetime.now(UTC).isoformat()
        status["last_synced_hash"] = outcome["source_hash"]
    except Exception as exc:  # noqa: BLE001 - any failure is recorded, never propagated
        message = str(exc) if isinstance(exc, SyncError) else "Unexpected error during sync."
        log.warning("docs_sync.failed", error=type(exc).__name__)
        outcome.update(status="failed", error=message[:300])
    outcome["finished_at"] = datetime.now(UTC).isoformat()
    status.update(last_run=outcome, requested=False)
    async with SessionFactory() as db:
        await store(db, STATUS_KEY, status)
        await db.commit()
    return outcome


async def tick(settings: Settings) -> None:
    async with SessionFactory() as db:
        config = await load(db, CONFIG_KEY)
        status = await load(db, STATUS_KEY)
    if not is_configured(config):
        return
    if status.get("requested"):
        await run_sync(settings, trigger="manual")
        return
    if not config.get("auto_enabled"):
        return
    last = status.get("last_run") or {}
    if last.get("status") == "failed" and last.get("finished_at"):
        # Back off after a failure; "Sync now" bypasses this.
        finished = datetime.fromisoformat(last["finished_at"])
        if (datetime.now(UTC) - finished).total_seconds() < RETRY_BACKOFF_SECONDS:
            return
    try:
        current = _cached_source_hash(settings, config)
    except SyncError:
        return
    if current != status.get("last_synced_hash"):
        await run_sync(settings, trigger="automatic")


# The bundled docs are immutable for the life of a container, so the 30-second
# check only stats the files; they are read and hashed again only if that
# cheap fingerprint (or the publishing options) changes.
_hash_cache: tuple[tuple[Any, ...], str] | None = None


def _cached_source_hash(settings: Settings, config: dict[str, Any]) -> str:
    global _hash_cache
    root = Path(settings.docs_sync_source_dir)
    if not root.is_dir():
        raise SyncError("The bundled documentation folder is missing from this build.")
    stats = [path.stat() for path in root.rglob("*.md")]
    fingerprint = (
        len(stats),
        sum(stat.st_size for stat in stats),
        max((stat.st_mtime_ns for stat in stats), default=0),
        tuple(config.get("include_paths") or []),
        config.get("repository_url"),
        source_branch(settings),
    )
    if _hash_cache is None or _hash_cache[0] != fingerprint:
        _hash_cache = (fingerprint, source_hash(discover(settings, config)))
    return _hash_cache[1]


async def run_forever(settings: Settings) -> None:
    """Scheduler background loop; independent of anyone using PCC."""
    while True:
        try:
            await tick(settings)
        except Exception as exc:  # noqa: BLE001 - must never stop the scheduler
            log.error("docs_sync.tick_failed", error=type(exc).__name__)
        await asyncio.sleep(LOOP_SECONDS)
