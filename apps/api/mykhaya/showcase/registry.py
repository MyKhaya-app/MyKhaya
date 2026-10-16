"""The showcase module registry and the seed orchestrator.

Family Demo and Ultimate Demo share one dataset and one ordered list of
module seeders. Which seeders run is decided by the Home's real plan
(mykhaya.entitlements.PLAN_DEFINITIONS), never by the template name: a seeder
whose entitlement the plan does not grant is skipped, so Ultimate-only data
can never appear in a Family Home. Adding a newly released module's showcase
is one new ShowcaseModule entry with its entitlement key — nothing else
duplicates the Family seed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.entitlements import PLAN_DEFINITIONS
from mykhaya.models import HomeCalendar, Membership, SubscriptionPlan, User
from mykhaya.showcase import family, ultimate
from mykhaya.showcase.context import ShowcaseContext, StoredFiles


@dataclass(frozen=True)
class ShowcaseModule:
    key: str
    name: str
    # The plan entitlement this module's data requires; None for data every
    # plan supports (household members, Calendar, personal settings).
    entitlement: str | None
    seed: Callable[[ShowcaseContext], Awaitable[int]]


SHOWCASE_MODULES: tuple[ShowcaseModule, ...] = (
    ShowcaseModule("household", "Household members", None, family.seed_household),
    ShowcaseModule("calendar", "Calendar", None, family.seed_calendar),
    ShowcaseModule("nudges", "Nudges", "nudges.enabled", family.seed_nudges),
    ShowcaseModule("meals", "Meal Plans", "meals.enabled", family.seed_meals),
    ShowcaseModule("lists", "Lists", "lists.enabled", family.seed_lists),
    ShowcaseModule("wishlists", "Wishlists", "wishlists.enabled", family.seed_wishlists),
    ShowcaseModule("settings", "Personal settings", None, family.seed_personal_settings),
    # Ultimate-only modules.
    ShowcaseModule("budget", "Budget", "budget.enabled", ultimate.seed_budget),
    ShowcaseModule("driveway", "Driveway", "driveway.enabled", ultimate.seed_driveway),
)


def modules_for_plan(plan: SubscriptionPlan) -> tuple[ShowcaseModule, ...]:
    definition = PLAN_DEFINITIONS[plan]
    return tuple(
        module
        for module in SHOWCASE_MODULES
        if module.entitlement is None or definition.booleans.get(module.entitlement, False)
    )


@dataclass(frozen=True)
class ShowcaseSeedResult:
    counts: dict[str, int]
    written: StoredFiles


async def seed_showcase(
    db: AsyncSession,
    settings: Settings,
    *,
    home_id: uuid.UUID,
    owner: User,
    owner_membership: Membership,
    home_calendar: HomeCalendar,
    fixture_key: str,
    plan: SubscriptionPlan,
    reference_date: date,
    preserved_member_emails: dict[str, str] | None = None,
) -> ShowcaseSeedResult:
    """Seed every module the plan entitles, in the caller's transaction.

    On any failure the images this run already wrote are removed before the
    error propagates, so a rolled-back transaction leaves nothing behind."""
    ctx = ShowcaseContext(
        db=db,
        settings=settings,
        home_id=home_id,
        owner=owner,
        owner_membership=owner_membership,
        plan=plan,
        fixture_key=fixture_key,
        reference_date=reference_date,
        home_calendar=home_calendar,
        preserved_member_emails=preserved_member_emails or {},
    )
    try:
        for module in modules_for_plan(plan):
            ctx.add_count(module.key, await module.seed(ctx))
        await db.flush()
    except BaseException:
        await ctx.written.delete_all(settings)
        raise
    return ShowcaseSeedResult(counts=dict(ctx.counts), written=ctx.written)
