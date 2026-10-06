"""PCC orchestration around the single Home migration engine.

This module deliberately contains no export/import/remapping logic. It stores
only package metadata and a controlled storage key so dry-run approval is bound
to the exact uploaded bytes without putting package contents in audit events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        path.write_text, json.dumps(package, sort_keys=True) + "\n", encoding="utf-8"
    )
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
