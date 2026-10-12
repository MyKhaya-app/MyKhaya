"""PCC orchestration around the single Home migration engine.

This module deliberately contains no export/import/remapping logic. It stores
only package metadata and a controlled storage key so dry-run approval is bound
to the exact uploaded bytes without putting package contents in audit events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import JSON, Column, DateTime, String, Table, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.db import Base
from mykhaya.tools.home_migration import MAX_FILE_BYTES, MigrationError, validate_package

PACKAGE_STORE = Table(
    "home_migration_packages",
    Base.metadata,
    Column("id", Uuid(), primary_key=True),
    Column("migration_id", Uuid(), nullable=False, unique=True),
    Column("package_checksum", String(64), nullable=False, index=True),
    Column("storage_key", String(80), nullable=False, unique=True),
    Column("source_home_id", Uuid(), nullable=False),
    Column("summary", JSON, nullable=False),
    Column("dry_run_checksum", String(64), nullable=True),
    Column("dry_run_report", JSON, nullable=True),
    Column("completed_report", JSON, nullable=True),
    Column("status", String(32), nullable=False, server_default="uploaded"),
    Column("created_by", Uuid(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)
log = structlog.get_logger("home_migration")


def package_checksum(package: dict[str, Any]) -> str:
    body = {key: value for key, value in package.items() if key != "integrity_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def package_summary(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "migration_id": package["migration_id"],
        "source_environment": package["source_environment"],
        "source_home_id": package["source_home_id"],
        "exported_at": package["exported_at"],
        "member_count": len(package["members"]),
        "asset_count": len(package["files"]),
        "counts": {name: len(rows) for name, rows in package["data"].items()},
        "version": package["version"],
    }


def storage_path(settings: Settings, storage_key: str) -> Path:
    root = Path(settings.home_migration_storage_dir).resolve()
    path = (root / storage_key).resolve()
    if path.parent != root:
        raise MigrationError("Invalid migration package storage key.")
    return path


async def load_package(settings: Settings, storage_key: str) -> dict[str, Any]:
    path = storage_path(settings, storage_key)
    if not await asyncio.to_thread(path.is_file):
        raise MigrationError("The migration package is no longer available.")
    raw = await asyncio.to_thread(path.read_bytes)
    if len(raw) > MAX_FILE_BYTES:
        raise MigrationError("The migration package exceeds the safe size limit.")
    try:
        package = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationError("The migration package is not valid JSON.") from exc
    if not isinstance(package, dict):
        raise MigrationError("The migration package has an invalid shape.")
    validate_package(package)
    return package


async def store_package(
    db: AsyncSession,
    settings: Settings,
    package: dict[str, Any],
    *,
    created_by: uuid.UUID,
) -> dict[str, Any]:
    validate_package(package)
    checksum = package_checksum(package)
    package_id = uuid.uuid4()
    storage_key = f"{package_id}.json"
    path = storage_path(settings, storage_key)
    try:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            path.write_text, json.dumps(package, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        log.exception("home_migration.package_storage_unavailable", storage_key=storage_key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            log.warning("home_migration.package_storage_cleanup_failed", storage_key=storage_key)
        raise MigrationError(
            "Migration package storage is unavailable. "
            "Check the Home Migration storage configuration."
        ) from exc
    row = {
        "id": package_id,
        "migration_id": uuid.UUID(package["migration_id"]),
        "package_checksum": checksum,
        "storage_key": storage_key,
        "source_home_id": uuid.UUID(package["source_home_id"]),
        "summary": package_summary(package),
        "status": "uploaded",
        "created_by": created_by,
        "created_at": datetime.now(UTC),
    }
    try:
        await db.execute(PACKAGE_STORE.insert().values(**row))
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return {**row, "id": str(package_id), "migration_id": str(row["migration_id"])}


async def get_package(db: AsyncSession, package_id: uuid.UUID) -> dict[str, Any] | None:
    result = await db.execute(select(PACKAGE_STORE).where(PACKAGE_STORE.c.id == package_id))
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


def migration_enabled(row: dict[str, Any] | None) -> bool:
    """Read the JSON payload stored in PlatformSetting.value."""
    return bool(row and row.get("value") is True)


# --- Package file lifecycle -------------------------------------------------
#
# A package is a plaintext copy of an entire Home (members, birth dates,
# Budget, vehicles incl. registration/VIN, photos). Its file is kept only as
# long as the workflow needs it: deleted as soon as an import completes, and
# otherwise purged by the scheduler once older than
# MYKHAYA_HOME_MIGRATION_PACKAGE_TTL_HOURS. The database row (summary counts,
# checksum, reports — no package content) is kept as the audit trail; only
# its status changes to "expired".

EXPIRED_STATUS = "expired"
# Bounded work per scheduler pass: stat at most this many directory entries
# and delete at most PURGE_DELETE_LIMIT files. Packages are rare, manual
# artefacts, so a backlog clears over successive hourly passes.
PURGE_SCAN_LIMIT = 5000
PURGE_DELETE_LIMIT = 200


@dataclass(frozen=True)
class PackagePurgeResult:
    scanned: int
    removed_completed: int
    removed_expired: int
    removed_orphaned: int

    @property
    def removed(self) -> int:
        return self.removed_completed + self.removed_expired + self.removed_orphaned


async def discard_package_file(settings: Settings, storage_key: str) -> None:
    """Best-effort removal; a leftover file is still caught by the TTL purge."""
    try:
        await asyncio.to_thread(storage_path(settings, storage_key).unlink, missing_ok=True)
    except (OSError, MigrationError):
        log.warning("home_migration.package_discard_failed", storage_key=storage_key)


def _scan_package_files(root: Path) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= PURGE_SCAN_LIMIT:
                break
            if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False):
                found.append((entry.name, entry.stat(follow_symlinks=False).st_mtime))
    return found


async def purge_expired_packages(
    db: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> PackagePurgeResult:
    """Delete package files that have outlived their purpose:

    * completed imports — always (the import no longer needs the bytes);
    * any other package older than the TTL — and mark its row "expired";
    * orphan files with no row (e.g. a crash between write and insert)
      older than the TTL.

    Never touches a non-completed package younger than the TTL. Logs counts
    only — never package content, and storage keys only on failure.
    """
    root = Path(settings.home_migration_storage_dir)
    if not await asyncio.to_thread(root.is_dir):
        return PackagePurgeResult(0, 0, 0, 0)
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=settings.home_migration_package_ttl_hours)
    files = await asyncio.to_thread(_scan_package_files, root)
    rows = {}
    if files:
        result = await db.execute(
            select(
                PACKAGE_STORE.c.id,
                PACKAGE_STORE.c.storage_key,
                PACKAGE_STORE.c.status,
                PACKAGE_STORE.c.created_at,
            ).where(PACKAGE_STORE.c.storage_key.in_([name for name, _ in files]))
        )
        rows = {row.storage_key: row for row in result}
    completed = expired = orphaned = 0
    expired_ids: list[uuid.UUID] = []
    for name, mtime in files:
        if completed + expired + orphaned >= PURGE_DELETE_LIMIT:
            break
        row = rows.get(name)
        expired_id: uuid.UUID | None = None
        if row is None:
            if datetime.fromtimestamp(mtime, UTC) >= cutoff:
                continue
            kind = "orphaned"
        elif row.status == "completed":
            kind = "completed"
        elif row.created_at < cutoff:
            kind = "expired"
            expired_id = row.id
        else:
            continue
        try:
            await asyncio.to_thread((root / name).unlink, missing_ok=True)
        except OSError:
            log.warning("home_migration.package_purge_failed", storage_key=name)
            continue
        if kind == "completed":
            completed += 1
        elif expired_id is not None:
            expired += 1
            expired_ids.append(expired_id)
        else:
            orphaned += 1
    if expired_ids:
        await db.execute(
            PACKAGE_STORE.update()
            .where(PACKAGE_STORE.c.id.in_(expired_ids), PACKAGE_STORE.c.status != "completed")
            .values(status=EXPIRED_STATUS)
        )
        await db.commit()
    outcome = PackagePurgeResult(len(files), completed, expired, orphaned)
    if outcome.removed:
        log.info(
            "home_migration.packages_purged",
            removed_completed=completed,
            removed_expired=expired,
            removed_orphaned=orphaned,
        )
    return outcome
