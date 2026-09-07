"""Explicit, local/operator-only Apple TestFlight review fixture.

This module is never imported by application startup. It is intentionally a small
direct-DB management command because there is no existing seed service, while all
rows still use the application's normal ORM models and password hasher.
"""

from __future__ import annotations

import argparse
import asyncio
import os

FIXTURE_EMAIL = "apple-review@mykhaya.app"
FIXTURE_HOME_NAME = "Apple Review Home"
# A stable, unique fixture marker. It is not derived from display names and is
# also the Home's child-login code, which is already a unique Home identifier.
FIXTURE_HOME_CODE = "ARVHOME27"
FIXTURE_PASSWORD_ENV = "MYKHAYA_APPLE_REVIEW_PASSWORD"  # noqa: S105
FIXTURE_KEY = "apple-review"
TIMEZONE = "Europe/London"


def _password() -> str:
    value = os.environ.get(FIXTURE_PASSWORD_ENV, "")
    if not value:
        raise RuntimeError(
            f"{FIXTURE_PASSWORD_ENV} must be set; the review password is never stored "
            "in source or logs"
        )
    return value


async def create_fixture() -> None:
    password = _password()
    from mykhaya.db import SessionFactory
    from mykhaya.managed_demo_homes import ManagedDemoService
    from mykhaya.models import ManagedDemoType

    async with SessionFactory() as db:
        row = await ManagedDemoService.get(db, FIXTURE_KEY)
        if row is None:
            await ManagedDemoService.create(
                db,
                fixture_key=FIXTURE_KEY,
                display_name=FIXTURE_HOME_NAME,
                fixture_type=ManagedDemoType.apple_review,
                email=FIXTURE_EMAIL,
                password=password,
                created_by=None,
                home_code=FIXTURE_HOME_CODE,
            )
        else:
            await ManagedDemoService.reset_password(db, row, password)
            await ManagedDemoService.refresh_template(db, row)
        await db.commit()
    print(f"Created Apple review fixture Home '{FIXTURE_HOME_NAME}' ({FIXTURE_HOME_CODE})")
    return


async def remove_fixture() -> None:
    from mykhaya.db import SessionFactory
    from mykhaya.managed_demo_homes import ManagedDemoService

    async with SessionFactory() as db:
        row = await ManagedDemoService.get(db, FIXTURE_KEY)
        if row is not None:
            await ManagedDemoService.delete(db, row)
        await db.commit()
    print("Removed the Apple review fixture")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage the opt-in Apple TestFlight review fixture"
    )
    parser.add_argument("action", choices=("create", "refresh", "remove"))
    args = parser.parse_args()
    if args.action in {"create", "refresh"}:
        asyncio.run(create_fixture())
    else:
        asyncio.run(remove_fixture())


if __name__ == "__main__":
    main()
