"""Idempotent synthetic fixture for the isolated Lab environment."""

from __future__ import annotations

import asyncio
import os

FIXTURE_KEY = "lab-review"
FIXTURE_EMAIL = "lab-owner@example.com"
FIXTURE_HOME_NAME = "MyKhaya Lab Home"
FIXTURE_HOME_CODE = "LABHOME27"


async def seed() -> None:
    from mykhaya.config import get_settings

    settings = get_settings()
    if settings.environment != "lab":
        raise RuntimeError("Lab fixture seeding is only permitted when MYKHAYA_ENVIRONMENT=lab")
    password = os.environ.get("MYKHAYA_LAB_FIXTURE_PASSWORD", "")
    if not password or "CHANGE_ME" in password or len(password) < 12:
        raise RuntimeError("MYKHAYA_LAB_FIXTURE_PASSWORD must be a real Lab-only password")

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
                fixture_type=ManagedDemoType.demo,
                email=FIXTURE_EMAIL,
                password=password,
                created_by=None,
                home_code=FIXTURE_HOME_CODE,
            )
        else:
            await ManagedDemoService.reset_password(db, row, password)
            await ManagedDemoService.refresh_template(db, row)
        await db.commit()
    print(f"Seeded synthetic Lab Home '{FIXTURE_HOME_NAME}' ({FIXTURE_HOME_CODE})")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
