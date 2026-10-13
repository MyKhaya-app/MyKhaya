"""Read-only count of vehicles whose nickname is a copy of their registration.

Before this change the web Add Vehicle form defaulted a blank nickname to the
registration, so some existing rows may hold the plate in ``nickname`` — an
unprotected field shown in lists and reminders. This tool only *counts* them
so the owner can decide what to do; it never prints a nickname, registration,
vehicle ID or Home ID, and it never writes.

Safe in DEV and PROD: aggregate SELECTs only, inside a PostgreSQL
``READ ONLY`` transaction that is never committed, using the api's ordinary
runtime database role. Output is a JSON object of four integers.

Usage (inside the running api container)::

    docker compose exec -T api python -m mykhaya.tools.driveway_nickname_audit
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import ColumnElement, func, select, text

from mykhaya.db import SessionFactory
from mykhaya.models import Vehicle


def _squash(column: Any) -> ColumnElement[str]:
    """Uppercase and strip every whitespace character, so "AP22 OOJ",
    "ap22ooj" and " AP22  OOJ " all compare equal."""
    return func.upper(func.regexp_replace(column, r"\s+", "", "g"))


async def count_nickname_registration_copies() -> dict[str, int]:
    matches = (Vehicle.registration.is_not(None)) & (
        _squash(Vehicle.nickname) == _squash(Vehicle.registration)
    )
    async with SessionFactory() as db:
        # Enforced by PostgreSQL, not just by convention: any write attempted
        # in this transaction fails. Rolled back (never committed) on exit.
        await db.execute(text("SET TRANSACTION READ ONLY"))
        total = await db.scalar(select(func.count()).select_from(Vehicle))
        active_matches = await db.scalar(
            select(func.count()).where(matches, Vehicle.archived_at.is_(None))
        )
        archived_matches = await db.scalar(
            select(func.count()).where(matches, Vehicle.archived_at.is_not(None))
        )
        homes_affected = await db.scalar(
            select(func.count(func.distinct(Vehicle.group_id))).where(matches)
        )
    return {
        "vehicles_total": int(total or 0),
        "nickname_equals_registration_active": int(active_matches or 0),
        "nickname_equals_registration_archived": int(archived_matches or 0),
        "homes_affected": int(homes_affected or 0),
    }


def main() -> None:
    print(json.dumps(asyncio.run(count_nickname_registration_copies()), indent=2))


if __name__ == "__main__":
    main()
