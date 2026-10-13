"""Which managed fixtures are showcase Homes, and what that restricts.

Deliberately dependency-light (models only) so provider integrations such as
mykhaya.driveway_mot can consult it without importing the seeders.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import ManagedDemoHome, ManagedDemoType

# Templates seeded by mykhaya.showcase and resettable from PCC. Apple Review,
# QA Test and Free Plan Demo keep their own legacy templates.
SHOWCASE_FIXTURE_TYPES = frozenset({ManagedDemoType.demo, ManagedDemoType.ultimate_demo})


def is_showcase_type(fixture_type: ManagedDemoType) -> bool:
    return fixture_type in SHOWCASE_FIXTURE_TYPES


async def is_showcase_home(db: AsyncSession, home_id: uuid.UUID) -> bool:
    """True for a Home registered as a showcase Demo Home.

    Vehicles in these Homes carry fictional registrations, so nothing may
    send them to a live government service (DVSA MOT history, DVLA) — the
    caller refuses the lookup server-side rather than relying on the UI."""
    found = await db.scalar(
        select(ManagedDemoHome.id)
        .where(
            ManagedDemoHome.home_id == home_id,
            ManagedDemoHome.fixture_type.in_(SHOWCASE_FIXTURE_TYPES),
        )
        .limit(1)
    )
    return found is not None
