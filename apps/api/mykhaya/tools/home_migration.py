"""One-off, local-only Home export/import utility.

This is deliberately a CLI rather than a PCC endpoint. It uses an explicit
allow-list of Home-owned tables, rewrites database identities on import, and
fails closed when the package or target state is unsafe. The package is
personal data: keep it encrypted in transit and remove it after use.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import secrets
import sys
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Column, Date, DateTime, String, Table, Time, Uuid, func, insert, select

from mykhaya import models as _models  # noqa: F401 - register ORM tables in Base.metadata
from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.config import Settings, get_settings
from mykhaya.db import Base, SessionFactory
from mykhaya.driveway_sensitive import (
    DrivewayFieldEncryptionUnavailable,
    DrivewaySensitiveReadError,
    logical_registration,
    logical_vin,
    vehicle_sensitive_ciphertexts,
)
from mykhaya.ids import uuid7
from mykhaya.meal_images import get_meal_image_storage
from mykhaya.models import TokenPurpose
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email
from mykhaya.platform_runtime import email_verification_required
from mykhaya.security import (
    create_action_token,
    derived_token,
    generate_home_code,
    normalise_email,
    password_hash,
)
from mykhaya.vehicle_photo_storage import get_vehicle_photo_storage

FORMAT = "mykhaya-home-migration"
VERSION = 2
MAX_FILE_BYTES = 52_428_800

TABLE_ORDER = (
    "groups",
    "users",
    "group_memberships",
    "child_profiles",
    "guardian_assignments",
    "home_calendars",
    "calendar_event_labels",
    "calendar_events",
    "calendar_event_members",
    "calendar_event_activity",
    "calendar_event_exceptions",
    "calendar_shares",
    "todo_categories",
    "household_routines",
    "household_routine_members",
    "household_routine_completions",
    "reminders",
    "reminder_members",
    "reminder_completions",
    "todos",
    "todo_members",
    "meals",
    "meal_ingredients",
    "meal_plan_entries",
    "meal_plan_participants",
    "list_templates",
    "list_template_sections",
    "list_template_items",
    "household_lists",
    "household_list_sections",
    "household_list_items",
    "wishlists",
    "wishlist_items",
    "wishlist_shares",
    "wishlist_item_reservations",
    "vehicles",
    "budget_profiles",
    "budget_months",
    "budget_categories",
    "budget_items",
    "budget_income_sources",
    "budget_month_categories",
    "budget_month_items",
    "budget_month_income",
    "budget_spending_entries",
    "budget_partner_shares",
    "notification_preferences",
    "feature_overrides",
    "home_calendar_highlight_settings",
    "home_holiday_subscriptions",
    "home_entitlement_grants",
    "home_subscriptions",
)

EXCLUDED_TABLES = {
    "auth_identities",
    "sessions",
    "trusted_devices",
    "action_tokens",
    "user_mfa_methods",
    "mfa_email_challenges",
    "external_identities",
    "user_passkeys",
    "audit_events",
    "product_usage_events",
    "outbox_events",
    "worker_job_records",
    "notifications",
    "notification_deliveries",
    "push_subscriptions",
    "native_push_devices",
    "group_invitations",
    "home_join_requests",
    "home_subscription_events",
    "stripe_webhook_events",
    "stripe_webhook_failures",
    "stripe_billing_diagnostics",
    "platform_settings",
    "platform_administrators",
    "platform_sessions",
    "administrative_audit_events",
    "security_events",
    "managed_demo_homes",
    "home_retention_lifecycles",
    "home_retention_memberships",
    "beta_pending_registrations",
    "beta_invitations",
    "beta_enrollments",
    "support_tickets",
    "support_ticket_messages",
    "support_ticket_attachments",
    "support_ticket_diagnostics",
    # Driveway MOT history is provider cache tied to the source environment's
    # lookups; the target re-fetches it (see PROVIDER_CACHE_COLUMNS).
    "vehicle_mot_tests",
    "vehicle_mot_defects",
}

# Every persistent SQLAlchemy table must be classified here.  This registry is
# deliberately explicit: a new model table is a review blocker until its
# migration treatment is chosen and the drift test is updated.
CoverageClass = Literal["MIGRATE", "REMAP", "RECREATE", "ENVIRONMENT_LOCAL", "FORBIDDEN"]
ENVIRONMENT_LOCAL_TABLES = {
    "admin_recovery_codes",
    "admin_webauthn_credentials",
    "administrative_notes",
    "backup_runs",
    "beta_programmes",
    "beta_waitlist_entries",
    "feature_flags",
    "legal_acceptance_evidence",
    "legal_acceptances",
    "legal_document_versions",
    "legal_documents",
    "monitor_alerts",
    "monitor_components",
    "monitor_observations",
    "monitor_overrides",
    "monitor_transitions",
    "notification_template_revisions",
    "notification_templates",
    "operational_heartbeats",
    "platform_administrator_invitations",
    "platform_holiday_dates",
    "platform_holiday_sources",
    "platform_push_settings",
    "platform_smtp_settings",
    "platform_stripe_settings",
    "privacy_requests",
    "product_usage_daily_aggregates",
    "public_incidents",
    "status_incident_services",
    "status_incident_updates",
    "stripe_webhook_ip_security_settings",
    "subprocessors",
    "home_migration_ledger",
}
FORBIDDEN_TABLES = EXCLUDED_TABLES | {"wishlist_guest_sessions"}
TABLE_CLASSIFICATIONS: dict[str, CoverageClass] = {
    **{name: "MIGRATE" for name in TABLE_ORDER if name != "home_holiday_subscriptions"},
    "home_holiday_subscriptions": "REMAP",
    **{name: "FORBIDDEN" for name in FORBIDDEN_TABLES},
    **{name: "ENVIRONMENT_LOCAL" for name in ENVIRONMENT_LOCAL_TABLES},
}

FILE_STORE_CLASSIFICATIONS = {
    "avatars": "MIGRATE",
    "vehicle_photos": "MIGRATE",
    "meal_images": "MIGRATE",
    "support_attachments": "ENVIRONMENT_LOCAL",
    "legal_evidence": "ENVIRONMENT_LOCAL",
    "home_migration_packages": "ENVIRONMENT_LOCAL",
}

SECRET_COLUMNS = {
    "password_hash",
    "token_hash",
    "encrypted_secret",
    "code_hash",
    "secret_key",
    "join_code_hash",
    "join_code_encrypted",
    "credential_id",
    # Field-encryption envelopes are bound to the source row id and the source
    # environment's keyring, so they are never carried in a package; import
    # re-derives them from the plaintext (see mykhaya.driveway_sensitive).
    "registration_ciphertext",
    "vin_ciphertext",
}
# Derived provider state on vehicles (Driveway MOT). Never carried across:
# an imported vehicle starts "not yet checked" and refreshes in the target.
PROVIDER_CACHE_COLUMNS = {
    "inspection_status",
    "inspection_due_date",
    "mot_first_due_date",
    "mot_refreshed_at",
    "mot_refresh_attempted_at",
    "mot_refresh_outcome",
}
STRIPE_COLUMNS = {"external_customer_id", "external_subscription_id", "external_price_id"}
ADMIN_COLUMNS = {"created_by", "updated_by", "published_by", "complimentary_granted_by"}
HOME_SECRET_COLUMNS = {"child_login_code", "join_code_hash", "join_code_encrypted"}

LEDGER = Table(
    "home_migration_ledger",
    Base.metadata,
    # This table is created by Alembic 0111 and deliberately has no ORM model.
    Column("id", Uuid(), primary_key=True),
    Column("migration_id", Uuid(), nullable=False),
    Column("source_home_id", Uuid(), nullable=False),
    Column("target_home_id", Uuid(), nullable=False),
    Column("package_checksum", String(64), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
)


class MigrationError(RuntimeError):
    """A safe-to-report validation or migration failure."""


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if hasattr(value, "value"):
        return value.value
    return value


def _uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"Invalid UUID in package: {value!r}") from exc


def _canonical_payload(package: dict[str, Any]) -> bytes:
    body = {key: value for key, value in package.items() if key != "integrity_sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def validate_package(package: dict[str, Any]) -> None:
    required = {
        "format",
        "version",
        "migration_id",
        "exported_at",
        "source_environment",
        "source_home_id",
        "home",
        "members",
        "data",
        "files",
        "environment_mappings",
        "manifest",
        "integrity_sha256",
    }
    if set(package) < required or package["format"] != FORMAT or package["version"] != VERSION:
        raise MigrationError("Unsupported or incomplete migration package.")
    if package["source_environment"] != "development":
        raise MigrationError("Only development packages are accepted.")
    _uuid(package["migration_id"])
    _uuid(package["source_home_id"])
    if not isinstance(package["members"], list) or not isinstance(package["data"], dict):
        raise MigrationError("Migration package members/data have invalid shapes.")
    if not isinstance(package.get("environment_mappings", {}), dict) or not isinstance(
        package.get("manifest", {}), dict
    ):
        raise MigrationError("Migration package environment mappings have an invalid shape.")
    expected = hashlib.sha256(_canonical_payload(package)).hexdigest()
    if not secrets.compare_digest(expected, str(package["integrity_sha256"])):
        raise MigrationError("Migration package integrity check failed.")
    for table, rows in package["data"].items():
        if table not in TABLE_ORDER or not isinstance(rows, list):
            raise MigrationError(f"Unsupported or malformed table payload: {table}.")
        for row in rows:
            if not isinstance(row, dict) or any(column in SECRET_COLUMNS for column in row):
                raise MigrationError(f"Unsafe secret-bearing row in {table}.")
    for member in package["members"]:
        if not isinstance(member, dict) or "id" not in member or "email" not in member:
            raise MigrationError("Every package member must contain an id and email.")
        _uuid(member["id"])
    if not isinstance(package["files"], list):
        raise MigrationError("Migration package files have an invalid shape.")
    for asset in package["files"]:
        if not isinstance(asset, dict) or asset.get("kind") not in {
            "avatar",
            "vehicle_photo",
            "meal_image",
        }:
            raise MigrationError("Migration package contains an unsupported asset.")
        key = asset.get("key")
        if not isinstance(key, str) or Path(key).name != key or key in {".", ".."}:
            raise MigrationError("Migration package contains an unsafe asset key.")
        if not isinstance(asset.get("content"), str):
            raise MigrationError("Migration package asset content is malformed.")
        try:
            decoded = base64.b64decode(asset["content"], validate=True)
            if len(decoded) > MAX_FILE_BYTES:
                raise MigrationError("Migration package asset exceeds the safe limit.")
            if asset.get("size_bytes") is not None and asset["size_bytes"] != len(decoded):
                raise MigrationError("Migration asset size does not match its manifest.")
            if asset.get("sha256") is not None and not secrets.compare_digest(
                asset["sha256"], hashlib.sha256(decoded).hexdigest()
            ):
                raise MigrationError("Migration asset checksum does not match its manifest.")
        except ValueError as exc:
            raise MigrationError("Migration package asset content is not valid base64.") from exc
    manifest = package["manifest"]
    expected_counts = {name: len(rows) for name, rows in package["data"].items()}
    if manifest.get("record_counts") != expected_counts:
        raise MigrationError("Migration manifest record counts do not match package data.")
    if manifest.get("asset_count") != len(package["files"]):
        raise MigrationError("Migration manifest asset count does not match package data.")
    if len(manifest.get("assets", [])) != len(package["files"]):
        raise MigrationError("Migration manifest asset entries are incomplete.")


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    if table is None:
        raise MigrationError(f"Expected model table is not present: {name}")
    return table


def validate_schema_coverage() -> None:
    """Fail closed when the model schema grows without migration policy."""
    model_tables = set(Base.metadata.tables)
    covered = set(TABLE_CLASSIFICATIONS) | {"home_migration_ledger", "home_migration_packages"}
    missing = sorted(model_tables - covered)
    unknown = sorted(
        set(TABLE_CLASSIFICATIONS)
        - model_tables
        - {"home_migration_ledger", "home_migration_packages"}
    )
    if missing or unknown:
        details = []
        if missing:
            details.append("unclassified tables: " + ", ".join(missing))
        if unknown:
            details.append("stale classifications: " + ", ".join(unknown))
        raise MigrationError(
            "Migration schema coverage is incomplete (" + "; ".join(details) + ")."
        )


def _row_matches_home(row: dict[str, Any], home_id: uuid.UUID, member_ids: set[uuid.UUID]) -> bool:
    for column in ("group_id", "source_group_id"):
        if column in row and row[column] is not None and _uuid(row[column]) == home_id:
            return True
    for column in (
        "user_id",
        "owner_user_id",
        "created_by",
        "completed_by",
        "cook_member_id",
        "recipient_user_id",
        "granted_by_user_id",
        "billing_owner_user_id",
    ):
        if column in row and row[column] is not None and _uuid(row[column]) in member_ids:
            return True
    return False


def _safe_user(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "created_at",
        "updated_at",
        "email",
        "display_name",
        "timezone",
        "birth_month",
        "birth_day",
        "birth_year",
        "avatar_key",
    }
    return {key: value for key, value in row.items() if key in allowed}


def _logical_vehicle_row(row: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Packages carry the LOGICAL registration/VIN, never ciphertext. With the
    Phase 2D read flag on, that logical value comes from the same
    ciphertext-first read path the API uses (mykhaya.driveway_sensitive); the
    ciphertext columns are then stripped by _export_row as before. A stored
    ciphertext that will not decrypt aborts the export (no plaintext
    fallback)."""
    try:
        registration = logical_registration(
            row["id"],
            plaintext=row.get("registration"),
            ciphertext=row.get("registration_ciphertext"),
            settings=settings,
        )
        vin = logical_vin(
            row["id"],
            plaintext=row.get("vin"),
            ciphertext=row.get("vin_ciphertext"),
            settings=settings,
        )
    except DrivewaySensitiveReadError as exc:
        raise MigrationError("A vehicle's protected details could not be read.") from exc
    return {**row, "registration": registration, "vin": vin}


def _export_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in SECRET_COLUMNS
        and key not in STRIPE_COLUMNS
        and key not in ADMIN_COLUMNS
        and key not in PROVIDER_CACHE_COLUMNS
    }


def _restore_value(column: Column[Any], value: Any) -> Any:
    """Turn JSON scalars back into the Python values asyncpg expects."""
    if value is None:
        return None
    if isinstance(column.type, Uuid):
        return _uuid(value)
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(column.type, Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(column.type, Time):
        from datetime import time

        return time.fromisoformat(value) if isinstance(value, str) else value
    return value


def _asset_path(settings: Settings, kind: str, key: str) -> Path:
    if not key or Path(key).name != key or key in {".", ".."}:
        raise MigrationError("Unsafe asset key.")
    roots = {
        "avatar": settings.avatar_storage_dir,
        "vehicle_photo": settings.vehicle_photo_storage_dir,
        "meal_image": settings.meal_image_storage_dir,
    }
    if kind not in roots:
        raise MigrationError(f"Unsupported asset kind: {kind}")
    return (Path(roots[kind]).resolve() / key).resolve()


async def _read_asset(settings: Settings, kind: str, key: str) -> str:
    path = _asset_path(settings, kind, key)
    root = {
        "avatar": Path(settings.avatar_storage_dir),
        "vehicle_photo": Path(settings.vehicle_photo_storage_dir),
        "meal_image": Path(settings.meal_image_storage_dir),
    }[kind].resolve()
    if not await asyncio.to_thread(path.is_file) or path.parent != root:
        raise MigrationError(f"Referenced {kind} file is missing: {key}")
    data = await asyncio.to_thread(path.read_bytes)
    if len(data) > MAX_FILE_BYTES:
        raise MigrationError(f"Referenced {kind} file exceeds the safe package limit: {key}")
    return base64.b64encode(data).decode("ascii")


async def export_home(home_id: uuid.UUID, output: Path, settings: Settings) -> dict[str, Any]:
    if settings.environment != "development":
        raise MigrationError("Export is permitted only from development.")
    validate_schema_coverage()
    async with SessionFactory() as db:
        home_table = _table("groups")
        home = (
            (await db.execute(select(home_table).where(home_table.c.id == home_id)))
            .mappings()
            .one_or_none()
        )
        if home is None:
            raise MigrationError(f"Home {home_id} was not found.")
        membership_table = _table("group_memberships")
        memberships = (
            (
                await db.execute(
                    select(membership_table).where(membership_table.c.group_id == home_id)
                )
            )
            .mappings()
            .all()
        )
        member_ids = {row["user_id"] for row in memberships}
        package: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "migration_id": str(uuid.uuid4()),
            "exported_at": datetime.now(UTC).isoformat(),
            "source_environment": "development",
            "source_home_id": str(home_id),
            "home": {
                key: _json_value(value)
                for key, value in home.items()
                if key not in HOME_SECRET_COLUMNS
            },
            "members": [],
            "data": {},
            "files": [],
            "environment_mappings": {"holiday_sources": []},
            "manifest": {},
        }
        users = _table("users")
        for user_id in member_ids:
            row = (await db.execute(select(users).where(users.c.id == user_id))).mappings().one()
            package["members"].append(
                _safe_user({key: _json_value(value) for key, value in row.items()})
            )
        for name in TABLE_ORDER[2:]:
            table = _table(name)
            rows = (await db.execute(select(table))).mappings().all()
            selected = [
                _export_row(
                    {
                        key: _json_value(value)
                        for key, value in (
                            _logical_vehicle_row(dict(row), settings) if name == "vehicles" else row
                        ).items()
                    }
                )
                for row in rows
                if _row_matches_home(dict(row), home_id, member_ids)
            ]
            if selected:
                package["data"][name] = selected
        referenced_user_ids = set(member_ids)
        for name, rows in package["data"].items():
            table = _table(name)
            user_columns = {
                column.name
                for column in table.columns
                if any(foreign.column.table.name == "users" for foreign in column.foreign_keys)
            }
            for row in rows:
                referenced_user_ids.update(
                    _uuid(row[column]) for column in user_columns if row.get(column) is not None
                )
        package_member_ids = {str(member["id"]) for member in package["members"]}
        for user_id in referenced_user_ids - member_ids:
            referenced_user = (
                (await db.execute(select(users).where(users.c.id == user_id)))
                .mappings()
                .one_or_none()
            )
            if referenced_user is not None and str(user_id) not in package_member_ids:
                package["members"].append(
                    _safe_user({key: _json_value(value) for key, value in referenced_user.items()})
                )
        for member in package["members"]:
            if member.get("avatar_key"):
                package["files"].append(
                    {
                        "kind": "avatar",
                        "owner_id": member["id"],
                        "key": member["avatar_key"],
                        "content": await _read_asset(settings, "avatar", member["avatar_key"]),
                    }
                )
        for row in package["data"].get("vehicles", []):
            if row.get("photo_key"):
                package["files"].append(
                    {
                        "kind": "vehicle_photo",
                        "owner_id": row["id"],
                        "key": row["photo_key"],
                        "content": await _read_asset(settings, "vehicle_photo", row["photo_key"]),
                    }
                )
        for row in package["data"].get("meals", []):
            if row.get("image_key"):
                package["files"].append(
                    {
                        "kind": "meal_image",
                        "owner_id": row["id"],
                        "key": row["image_key"],
                        "content": await _read_asset(settings, "meal_image", row["image_key"]),
                    }
                )
        for asset in package["files"]:
            raw_asset = base64.b64decode(asset["content"], validate=True)
            asset["size_bytes"] = len(raw_asset)
            asset["sha256"] = hashlib.sha256(raw_asset).hexdigest()
        holiday_source_ids = {
            _uuid(row["source_id"]) for row in package["data"].get("home_holiday_subscriptions", [])
        }
        if holiday_source_ids:
            holiday_sources = _table("platform_holiday_sources")
            source_rows = (
                (
                    await db.execute(
                        select(holiday_sources).where(holiday_sources.c.id.in_(holiday_source_ids))
                    )
                )
                .mappings()
                .all()
            )
            if len(source_rows) != len(holiday_source_ids):
                raise MigrationError("A Home holiday catalogue source is missing from DEV.")
            package["environment_mappings"]["holiday_sources"] = [
                {
                    "source_id": str(row["id"]),
                    "country_code": row["country_code"],
                    "region_code": row["region_code"],
                }
                for row in source_rows
            ]
    package["manifest"] = {
        "record_counts": {name: len(rows) for name, rows in package["data"].items()},
        "asset_count": len(package["files"]),
        "assets": [
            {
                "kind": asset["kind"],
                "owner_id": asset.get("owner_id"),
                "size_bytes": asset.get("size_bytes"),
                "sha256": asset.get("sha256"),
            }
            for asset in package["files"]
        ],
        "classified_tables": len(TABLE_CLASSIFICATIONS),
        "excluded_tables": sorted(FORBIDDEN_TABLES | ENVIRONMENT_LOCAL_TABLES),
    }
    package["integrity_sha256"] = hashlib.sha256(_canonical_payload(package)).hexdigest()
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        output.write_text, json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return package


def _new_id() -> uuid.UUID:
    return uuid7()


def _rewrite(
    row: dict[str, Any], maps: dict[str, dict[str, uuid.UUID]], table: Table
) -> dict[str, Any]:
    result = dict(row)
    old_id = str(result.get("id")) if result.get("id") is not None else None
    for column in table.columns:
        name = column.name
        if name in SECRET_COLUMNS or name in STRIPE_COLUMNS or name in PROVIDER_CACHE_COLUMNS:
            result.pop(name, None)
            continue
        if name in ADMIN_COLUMNS:
            result[name] = None
        targets = [
            maps[foreign.column.table.name]
            for foreign in column.foreign_keys
            if foreign.column.table.name in maps
        ]
        if targets and result.get(name) is not None:
            target = targets[0]
            if str(result[name]) not in target:
                if name not in {"last_edited_by", "deleted_by", "actor_user_id", "completed_by"}:
                    raise MigrationError(
                        f"Unmapped foreign key {table.name}.{name}={result[name]}."
                    )
                result[name] = None
            else:
                result[name] = str(target[str(result[name])])
        if name == "id" and old_id is not None:
            result[name] = str(maps[table.name][old_id])
    return result


def _report(
    package: dict[str, Any],
    *,
    target_home_id: uuid.UUID | None,
    status: str,
    reasons: list[str],
    matched: int = 0,
    created: int = 0,
    account_readiness: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    asset_manifest = [
        {
            "kind": asset["kind"],
            "owner_id": asset.get("owner_id"),
            "size_bytes": asset.get("size_bytes"),
            "sha256": asset.get("sha256"),
        }
        for asset in package.get("files", [])
    ]
    return {
        "migration_id": package["migration_id"],
        "source_home_id": package["source_home_id"],
        "target_home_id": str(target_home_id) if target_home_id else None,
        "status": status,
        "counts": {name: len(rows) for name, rows in package["data"].items()},
        "matched_existing_users": matched,
        "new_users": created,
        "account_readiness": account_readiness or [],
        "warnings": reasons,
        "manifest": {
            "record_counts": {name: len(rows) for name, rows in package["data"].items()},
            "asset_count": len(asset_manifest),
            "assets": asset_manifest,
            "classified_tables": len(TABLE_CLASSIFICATIONS),
            "excluded_tables": sorted(FORBIDDEN_TABLES | ENVIRONMENT_LOCAL_TABLES),
        },
    }


def _human_report(report: dict[str, Any]) -> str:
    lines = [
        "MyKhaya Home Migration",
        "=======================",
        f"Migration ID: {report['migration_id']}",
        f"Source Home: {report['source_home_id']}",
        f"Target Home: {report['target_home_id'] or 'not created'}",
        f"Status: {report['status']}",
        "",
        "Counts",
        "------",
    ]
    lines.extend(f"{name}: {count}" for name, count in report["counts"].items())
    lines.extend(
        [
            "",
            f"Matched existing users: {report['matched_existing_users']}",
            f"New accounts: {report['new_users']}",
            f"Account readiness entries: {len(report.get('account_readiness', []))}",
            "Warnings:",
        ]
    )
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


async def _existing_users_by_normalized_email(db: Any) -> dict[str, uuid.UUID]:
    users = _table("users")
    normalized: dict[str, uuid.UUID] = {}
    for row in (await db.execute(select(users))).mappings():
        email = normalise_email(str(row["email"]))
        existing = normalized.get(email)
        if existing is not None and existing != row["id"]:
            raise MigrationError(f"Target contains multiple users with normalized email {email}.")
        normalized[email] = row["id"]
    return normalized


async def _write_reports(report: dict[str, Any], report_dir: Path | None) -> None:
    if report_dir is None:
        return
    await asyncio.to_thread(report_dir.mkdir, parents=True, exist_ok=True)
    stem = f"migration-report-{report['migration_id']}"
    await asyncio.to_thread(
        (report_dir / f"{stem}.json").write_text,
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    await asyncio.to_thread(
        (report_dir / f"{stem}.txt").write_text,
        _human_report(report),
        encoding="utf-8",
    )


async def inspect_import(package: dict[str, Any], settings: Settings) -> dict[str, Any]:
    validate_package(package)
    validate_schema_coverage()
    migration_id = _uuid(package["migration_id"])
    async with SessionFactory() as db:
        done = (
            (await db.execute(select(LEDGER).where(LEDGER.c.migration_id == migration_id)))
            .mappings()
            .first()
        )
        if done is not None:
            return _report(package, target_home_id=None, status="ALREADY_COMPLETED", reasons=[])
        existing = await _existing_users_by_normalized_email(db)
        auth_identities = _table("auth_identities")
        external_identities = _table("external_identities")
        memberships = _table("group_memberships")
        account_readiness: list[dict[str, Any]] = []
        matched = sum(normalise_email(member["email"]) in existing for member in package["members"])
        created = len(package["members"]) - matched
        reasons = [] if settings.environment == "production" else ["Target is not production."]
        source_emails: dict[str, str] = {}
        for member in package["members"]:
            email = normalise_email(member["email"])
            previous = source_emails.get(email)
            if previous is not None and previous != str(member["id"]):
                reasons.append("The package contains an ambiguous duplicate member identity.")
            source_emails[email] = str(member["id"])
            target_id = existing.get(email)
            auth_count = 0
            external_count = 0
            membership_count = 0
            if target_id is not None:
                auth_count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(auth_identities)
                            .where(auth_identities.c.user_id == target_id)
                        )
                    ).scalar_one()
                )
                external_count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(external_identities)
                            .where(external_identities.c.user_id == target_id)
                        )
                    ).scalar_one()
                )
                membership_count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(memberships)
                            .where(memberships.c.user_id == target_id)
                        )
                    ).scalar_one()
                )
                if auth_count == 0:
                    reasons.append(
                        "An existing PROD member has no password identity; resolve the account "
                        "through the existing account-linking or recovery process before import."
                    )
            provider_only = target_id is not None and auth_count == 0 and external_count > 0
            account_readiness.append(
                {
                    "dev_member_id": str(member["id"]),
                    "proposed_prod_user_id": str(target_id) if target_id else None,
                    "existing_prod_account": target_id is not None,
                    "new_account_required": target_id is None,
                    "password_recovery_suitable": bool(email),
                    "email_verification_required": await email_verification_required(db, settings),
                    "provider_only_account": provider_only,
                    "identity_conflict": target_id is not None and auth_count == 0,
                    "existing_prod_home_memberships": membership_count,
                    "profile_preserved": target_id is not None,
                    "redacted_email": email[:1] + "***@" + email.split("@", 1)[1],
                }
            )
        holiday_sources = _table("platform_holiday_sources")
        for mapping in package.get("environment_mappings", {}).get("holiday_sources", []):
            matches = (
                (
                    await db.execute(
                        select(holiday_sources.c.id).where(
                            holiday_sources.c.country_code == mapping.get("country_code"),
                            holiday_sources.c.region_code == mapping.get("region_code"),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(matches) != 1:
                reasons.append("A Home holiday catalogue source is missing or ambiguous in PROD.")
        return _report(
            package,
            target_home_id=None,
            status="READY_TO_IMPORT" if not reasons else "NOT_SAFE_TO_IMPORT",
            reasons=reasons,
            matched=matched,
            created=created,
            account_readiness=account_readiness,
        )


async def _reconcile_import(
    db: Any,
    package: dict[str, Any],
    maps: dict[str, dict[str, uuid.UUID]],
    *,
    target_home_id: uuid.UUID,
    verified_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile the committed logical dataset before writing the ledger."""
    table_counts: dict[str, dict[str, int]] = {}
    relationship_checks = 0
    broken_relationships = 0
    for name, rows in package["data"].items():
        table = _table(name)
        source_ids = [str(row["id"]) for row in rows if row.get("id") is not None]
        target_ids = [maps[name][source_id] for source_id in source_ids if source_id in maps[name]]
        destination_count = 0
        if target_ids:
            destination_count = int(
                (
                    await db.execute(
                        select(func.count()).select_from(table).where(table.c.id.in_(target_ids))
                    )
                ).scalar_one()
            )
        table_counts[name] = {
            "source": len(rows),
            "destination": destination_count,
        }
        for row in rows:
            for column in table.columns:
                for foreign in column.foreign_keys:
                    if foreign.column.table.name in maps and row.get(column.name) is not None:
                        relationship_checks += 1
                        if str(row[column.name]) not in maps[foreign.column.table.name]:
                            broken_relationships += 1
    source_records = sum(item["source"] for item in table_counts.values())
    destination_records = sum(item["destination"] for item in table_counts.values())
    status = (
        "VERIFIED"
        if (
            source_records == destination_records
            and broken_relationships == 0
            and len(verified_assets) == len(package.get("files", []))
        )
        else "VERIFICATION_FAILED"
    )
    return {
        "status": status,
        "target_home_id": str(target_home_id),
        "source_records": source_records,
        "destination_records": destination_records,
        "table_counts": table_counts,
        "relationships_checked": relationship_checks,
        "broken_relationships": broken_relationships,
        "files_expected": len(package.get("files", [])),
        "files_verified": len(verified_assets),
        "assets": verified_assets,
        "unexpected_exclusions": [],
    }


async def import_home(
    package: dict[str, Any],
    settings: Settings,
    *,
    dry_run: bool,
    target_environment: str,
    confirm: bool,
) -> dict[str, Any]:
    validate_package(package)
    validate_schema_coverage()
    if settings.environment != target_environment:
        raise MigrationError("Target flag does not match MYKHAYA_ENVIRONMENT.")
    if settings.environment == "production" and not confirm:
        raise MigrationError("Production import requires --target-environment prod --confirm.")
    if dry_run:
        return await inspect_import(package, settings)
    if settings.environment != "production":
        raise MigrationError("Real imports are permitted only into production.")
    migration_id = _uuid(package["migration_id"])
    created_files: list[tuple[str, str]] = []
    verified_assets: list[dict[str, Any]] = []
    async with SessionFactory() as db:
        existing_ledger = (
            (
                await db.execute(
                    select(LEDGER).where(
                        (LEDGER.c.migration_id == migration_id)
                        | (LEDGER.c.source_home_id == _uuid(package["source_home_id"]))
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing_ledger:
            raise MigrationError(
                f"Migration {migration_id} was already completed. No changes made."
            )
        maps: dict[str, dict[str, uuid.UUID]] = defaultdict(dict)
        try:
            users = _table("users")
            existing_users = await _existing_users_by_normalized_email(db)
            matched_user_ids: set[uuid.UUID] = set()
            for member in package["members"]:
                email = normalise_email(member["email"])
                target_id = existing_users.get(email, _new_id())
                maps["users"][str(member["id"])] = target_id
                if email not in existing_users:
                    values = {
                        key: _restore_value(users.c[key], value)
                        for key, value in member.items()
                        if key in users.c and key != "id"
                    }
                    values.update({"id": target_id, "email": email, "avatar_key": None})
                    await db.execute(insert(users).values(values))
                    auth = _table("auth_identities")
                    await db.execute(
                        insert(auth).values(
                            id=_new_id(),
                            user_id=target_id,
                            password_hash=password_hash.hash(secrets.token_urlsafe(48)),
                        )
                    )
                    if await email_verification_required(db, settings):
                        token = await create_action_token(
                            db, target_id, TokenPurpose.verify_email, settings, 60 * 24
                        )
                        raw = derived_token(
                            token.id,
                            token.purpose.value,
                            settings.secret_key.get_secret_value(),
                        )
                        subject, message, html = await render_notification_email(
                            db,
                            settings,
                            "email_verification",
                            {"link": f"{settings.public_web_url}/verify-email?token={raw}"},
                        )
                        await notify(
                            db,
                            settings=settings,
                            recipient_user_id=target_id,
                            notification_type="email_verification",
                            title=subject,
                            body=message,
                            idempotency_key=f"email_verification:{token.id}",
                            html_body=html,
                        )
                    existing_users[email] = target_id
                else:
                    matched_user_ids.add(target_id)
            groups = _table("groups")
            target_home_id = _new_id()
            maps["groups"][package["source_home_id"]] = target_home_id
            source_home = package["home"]
            creator = maps["users"].get(str(source_home["created_by"]))
            if creator is None:
                raise MigrationError("Home creator is not an exported member.")
            home_values = {
                key: _restore_value(groups.c[key], value)
                for key, value in source_home.items()
                if key in groups.c and key != "id" and key not in HOME_SECRET_COLUMNS
            }
            home_values.update(
                {
                    "id": target_home_id,
                    "created_by": creator,
                    "child_login_code": generate_home_code(),
                    "join_code_hash": None,
                    "join_code_encrypted": None,
                    "join_code_generated_at": None,
                    "last_activity_at": None,
                    "suspended_at": None,
                    "archived_at": None,
                }
            )
            await db.execute(insert(groups).values(home_values))
            holiday_source_map: dict[str, uuid.UUID] = {}
            target_holiday_sources = _table("platform_holiday_sources")
            for mapping in package.get("environment_mappings", {}).get("holiday_sources", []):
                source_id = str(mapping.get("source_id"))
                matches = (
                    (
                        await db.execute(
                            select(target_holiday_sources.c.id).where(
                                target_holiday_sources.c.country_code
                                == mapping.get("country_code"),
                                target_holiday_sources.c.region_code == mapping.get("region_code"),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(matches) != 1:
                    raise MigrationError(
                        "A Home holiday catalogue source cannot be resolved uniquely in PROD."
                    )
                holiday_source_map[source_id] = matches[0]
            # Driveway reminders link to their vehicle through reminders.source_id,
            # which is not a foreign key (so _rewrite can't remap it) and is
            # imported before vehicles: allocate the new vehicle ids up front.
            for vehicle_row in package["data"].get("vehicles", []):
                if vehicle_row.get("id") is not None:
                    maps["vehicles"][str(vehicle_row["id"])] = _new_id()
            for name in TABLE_ORDER[2:]:
                table = _table(name)
                for source in package["data"].get(name, []):
                    old_id = source.get("id")
                    if old_id is not None:
                        if name == "notification_preferences":
                            source_user = maps["users"].get(str(source.get("user_id")))
                            if source_user in matched_user_ids:
                                continue
                        maps[name].setdefault(str(old_id), _new_id())
                    values = _rewrite(source, maps, table)
                    if name == "home_holiday_subscriptions":
                        source_id = str(values.get("source_id"))
                        target_source_id = holiday_source_map.get(source_id)
                        if target_source_id is None:
                            raise MigrationError(
                                "A Home holiday subscription has no safe PROD catalogue mapping."
                            )
                        values["source_id"] = target_source_id
                    if name == "reminders" and values.get("source_type") == "driveway":
                        vehicle_id = maps["vehicles"].get(str(values.get("source_id")))
                        if vehicle_id is None:
                            # Its vehicle isn't in the package: keep the reminder,
                            # detached, rather than linked to another Home's vehicle.
                            values.update(source_type=None, source_id=None, source_event=None)
                        else:
                            values["source_id"] = str(vehicle_id)
                    values = {
                        key: _restore_value(table.c[key], value)
                        for key, value in values.items()
                        if key in table.c
                    }
                    if (
                        "created_by" in table.c
                        and not table.c["created_by"].nullable
                        and values.get("created_by") is None
                    ):
                        # Attribution columns are never carried across (see
                        # ADMIN_COLUMNS); where one is required, the row is
                        # attributed to the imported Home's creator instead.
                        values["created_by"] = creator
                    if name == "vehicles":
                        # Same single write path as the Driveway router: the
                        # ciphertext (dual-write on) is bound to the NEW row id.
                        try:
                            values.update(
                                vehicle_sensitive_ciphertexts(
                                    values["id"],
                                    registration=values.get("registration"),
                                    vin=values.get("vin"),
                                    settings=settings,
                                )
                            )
                        except DrivewayFieldEncryptionUnavailable as exc:
                            raise MigrationError(
                                "Vehicle field encryption is enabled but unavailable."
                            ) from exc
                    if name == "home_subscriptions":
                        values.update(
                            {
                                "external_customer_id": None,
                                "external_subscription_id": None,
                                "external_price_id": None,
                                "complimentary_granted_by": None,
                            }
                        )
                    await db.execute(
                        insert(table).values({k: v for k, v in values.items() if k in table.c})
                    )
            for asset in package.get("files", []):
                data = base64.b64decode(asset["content"], validate=True)
                if len(data) > MAX_FILE_BYTES:
                    raise MigrationError("Asset exceeds the safe import limit.")
                asset_sha256 = hashlib.sha256(data).hexdigest()
                if asset.get("sha256") and not secrets.compare_digest(
                    asset["sha256"], asset_sha256
                ):
                    raise MigrationError("Migration asset checksum validation failed.")
                new_key = f"{uuid.uuid4()}.webp"
                if asset["kind"] == "avatar":
                    target_user = _table("users")
                    target_user_id = maps["users"].get(str(asset["owner_id"]))
                    if target_user_id is not None:
                        existing_avatar = (
                            await db.execute(
                                select(target_user.c.avatar_key).where(
                                    target_user.c.id == target_user_id
                                )
                            )
                        ).scalar_one_or_none()
                        if existing_avatar is not None:
                            raise MigrationError(
                                "An existing PROD profile picture would be overwritten; "
                                "resolve the asset conflict before import."
                            )
                    await get_avatar_storage(settings).save(new_key, data)
                    target_table_name, column = "users", "avatar_key"
                elif asset["kind"] == "vehicle_photo":
                    await get_vehicle_photo_storage(settings).save(new_key, data)
                    target_table_name, column = "vehicles", "photo_key"
                elif asset["kind"] == "meal_image":
                    await get_meal_image_storage(settings).save(new_key, data)
                    target_table_name, column = "meals", "image_key"
                else:
                    raise MigrationError(f"Unsupported asset kind: {asset.get('kind')}")
                created_files.append((asset["kind"], new_key))
                asset_target_id = maps[target_table_name].get(str(asset["owner_id"]))
                if asset_target_id:
                    target_table = _table(target_table_name)
                    predicate = target_table.c.id == asset_target_id
                    if target_table_name == "users":
                        predicate = predicate & target_table.c.avatar_key.is_(None)
                    await db.execute(
                        target_table.update().where(predicate).values({column: new_key})
                    )
                else:
                    raise MigrationError("Migration asset owner could not be remapped safely.")
                verified_assets.append(
                    {
                        "kind": asset["kind"],
                        "owner_id": asset.get("owner_id"),
                        "size_bytes": len(data),
                        "sha256": asset_sha256,
                    }
                )
            reconciliation = await _reconcile_import(
                db,
                package,
                maps,
                target_home_id=target_home_id,
                verified_assets=verified_assets,
            )
            if reconciliation["status"] != "VERIFIED":
                raise MigrationError("Post-import reconciliation failed before completion.")
            await db.execute(
                insert(LEDGER).values(
                    id=_new_id(),
                    migration_id=migration_id,
                    source_home_id=_uuid(package["source_home_id"]),
                    target_home_id=target_home_id,
                    package_checksum=package["integrity_sha256"],
                    completed_at=datetime.now(UTC),
                )
            )
            await db.commit()
            report = _report(package, target_home_id=target_home_id, status="IMPORTED", reasons=[])
            report["reconciliation"] = reconciliation
            return report
        except Exception:
            await db.rollback()
            cleanup_errors: list[str] = []
            for kind, key in created_files:
                try:
                    if kind == "avatar":
                        await get_avatar_storage(settings).delete(key)
                    elif kind == "vehicle_photo":
                        await get_vehicle_photo_storage(settings).delete(key)
                    else:
                        await get_meal_image_storage(settings).delete(key)
                except Exception as cleanup_error:
                    cleanup_errors.append(f"{kind}:{key}:{type(cleanup_error).__name__}")
            if cleanup_errors:
                raise MigrationError(
                    "Database import rolled back, but asset cleanup failed: "
                    + ", ".join(cleanup_errors)
                ) from None
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mykhaya.tools.home_migration")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--home-id", required=True, type=uuid.UUID)
    export.add_argument("--output", required=True, type=Path)
    imp = commands.add_parser("import")
    imp.add_argument("--input", required=True, type=Path)
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--confirm", action="store_true")
    imp.add_argument("--target-environment", choices=("dev", "prod"), required=True)
    imp.add_argument("--report-dir", type=Path)
    return parser


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.command == "export":
        package = await export_home(args.home_id, args.output, settings)
        report = _report(package, target_home_id=None, status="EXPORTED", reasons=[])
        await _write_reports(report, getattr(args, "report_dir", None))
        print(_human_report(report), end="")
        return 0
    package = json.loads(await asyncio.to_thread(args.input.read_text, encoding="utf-8"))
    report = await import_home(
        package,
        settings,
        dry_run=args.dry_run,
        target_environment="production" if args.target_environment == "prod" else "development",
        confirm=args.confirm,
    )
    await _write_reports(report, args.report_dir)
    print(_human_report(report), end="")
    return 0 if report["status"] in {"READY_TO_IMPORT", "IMPORTED", "ALREADY_COMPLETED"} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main(_parser().parse_args())))
    except (MigrationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"NOT SAFE TO IMPORT: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
