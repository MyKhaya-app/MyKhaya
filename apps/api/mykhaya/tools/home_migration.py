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
from typing import Any

from sqlalchemy import Column, Date, DateTime, String, Table, Time, Uuid, insert, select

from mykhaya import models as _models  # noqa: F401 - register ORM tables in Base.metadata
from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.config import Settings, get_settings
from mykhaya.db import Base, SessionFactory
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
VERSION = 1
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
            if len(base64.b64decode(asset["content"], validate=True)) > MAX_FILE_BYTES:
                raise MigrationError("Migration package asset exceeds the safe limit.")
        except ValueError as exc:
            raise MigrationError("Migration package asset content is not valid base64.") from exc


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    if table is None:
        raise MigrationError(f"Expected model table is not present: {name}")
    return table


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


def _export_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in SECRET_COLUMNS and key not in STRIPE_COLUMNS and key not in ADMIN_COLUMNS
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
                _export_row({key: _json_value(value) for key, value in row.items()})
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
        if name in SECRET_COLUMNS or name in STRIPE_COLUMNS:
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
) -> dict[str, Any]:
    return {
        "migration_id": package["migration_id"],
        "source_home_id": package["source_home_id"],
        "target_home_id": str(target_home_id) if target_home_id else None,
        "status": status,
        "counts": {name: len(rows) for name, rows in package["data"].items()},
        "matched_existing_users": matched,
        "new_users": created,
        "warnings": reasons,
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
        matched = sum(normalise_email(member["email"]) in existing for member in package["members"])
        created = len(package["members"]) - matched
        reasons = [] if settings.environment == "production" else ["Target is not production."]
        return _report(
            package,
            target_home_id=None,
            status="READY_TO_IMPORT" if not reasons else "NOT_SAFE_TO_IMPORT",
            reasons=reasons,
            matched=matched,
            created=created,
        )


async def import_home(
    package: dict[str, Any],
    settings: Settings,
    *,
    dry_run: bool,
    target_environment: str,
    confirm: bool,
) -> dict[str, Any]:
    validate_package(package)
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
            for name in TABLE_ORDER[2:]:
                table = _table(name)
                for source in package["data"].get(name, []):
                    old_id = source.get("id")
                    if old_id is not None:
                        if name == "notification_preferences":
                            source_user = maps["users"].get(str(source.get("user_id")))
                            if source_user in matched_user_ids:
                                continue
                        maps[name][str(old_id)] = _new_id()
                    values = _rewrite(source, maps, table)
                    values = {
                        key: _restore_value(table.c[key], value)
                        for key, value in values.items()
                        if key in table.c
                    }
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
                new_key = f"{uuid.uuid4()}.webp"
                if asset["kind"] == "avatar":
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
            return _report(package, target_home_id=target_home_id, status="IMPORTED", reasons=[])
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
