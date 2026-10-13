"""Remove a showcase Home's content ahead of a reseed (PCC "Reset Showcase Data").

Scope is exactly one managed showcase Home: every query below is keyed by
that Home's id, plus the personal Budget and settings of accounts that
belong to it alone. Kept: the Home itself and its name, the owner account and
its credentials/sessions, the managed-fixture record, the subscription,
module overrides, MFA policy, the primary Home Calendar and the owner's
Personal Calendar, and the system Driveway Nudges category.

Rows are deleted children-first with Core statements, because several
user/category references are ON DELETE RESTRICT (Vehicle owner, Budget
categories) and must be gone before the rows they guard.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    BudgetCategory,
    BudgetIncomeSource,
    BudgetItem,
    BudgetMonth,
    BudgetMonthCategory,
    BudgetMonthIncome,
    BudgetMonthItem,
    BudgetPartnerShare,
    BudgetProfile,
    BudgetSpendingEntry,
    CalendarEvent,
    CalendarEventLabel,
    CalendarShare,
    HomeCalendar,
    HomeCalendarHighlightSettings,
    HomeJoinRequest,
    HouseholdList,
    HouseholdRoutine,
    Invitation,
    ListTemplate,
    ManagedDemoHome,
    Meal,
    MealPlanEntry,
    Membership,
    Notification,
    NotificationPreferences,
    Reminder,
    Todo,
    TodoCategory,
    User,
    Vehicle,
    Wishlist,
)
from mykhaya.showcase.context import StoredFiles


class ShowcasePurgeRefused(RuntimeError):
    pass


async def _purge_budgets(db: AsyncSession, user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    profile_ids = select(BudgetProfile.id).where(BudgetProfile.owner_user_id.in_(user_ids))
    month_ids = select(BudgetMonth.id).where(BudgetMonth.profile_id.in_(profile_ids))
    month_category_ids = select(BudgetMonthCategory.id).where(
        BudgetMonthCategory.month_id.in_(month_ids)
    )
    await db.execute(
        delete(BudgetSpendingEntry).where(
            BudgetSpendingEntry.month_category_id.in_(month_category_ids)
        )
    )
    await db.execute(delete(BudgetMonthItem).where(BudgetMonthItem.month_id.in_(month_ids)))
    await db.execute(delete(BudgetMonthIncome).where(BudgetMonthIncome.month_id.in_(month_ids)))
    await db.execute(delete(BudgetMonthCategory).where(BudgetMonthCategory.month_id.in_(month_ids)))
    await db.execute(delete(BudgetMonth).where(BudgetMonth.profile_id.in_(profile_ids)))
    await db.execute(delete(BudgetItem).where(BudgetItem.profile_id.in_(profile_ids)))
    await db.execute(
        delete(BudgetIncomeSource).where(BudgetIncomeSource.profile_id.in_(profile_ids))
    )
    await db.execute(delete(BudgetCategory).where(BudgetCategory.profile_id.in_(profile_ids)))
    await db.execute(
        delete(BudgetPartnerShare).where(BudgetPartnerShare.profile_id.in_(profile_ids))
    )
    await db.execute(delete(BudgetProfile).where(BudgetProfile.owner_user_id.in_(user_ids)))


async def purge_showcase_home(db: AsyncSession, row: ManagedDemoHome) -> StoredFiles:
    """Delete the Home's showcase content. Returns the image files that are
    now unreferenced; the caller removes them only after its commit."""
    home_id = row.home_id
    owner_memberships = list(
        await db.scalars(
            select(Membership.group_id).where(
                Membership.user_id == row.owner_user_id, Membership.removed_at.is_(None)
            )
        )
    )
    if owner_memberships != [home_id]:
        # The owner's Budget and settings are personal, not Home-owned; they
        # are only safe to reset while the account belongs to this Home alone.
        raise ShowcasePurgeRefused(
            "The managed owner account belongs to another Home, so its data can't be reset."
        )
    stale = StoredFiles()

    # Driveway first: Vehicle.owner_user_id is ON DELETE RESTRICT.
    stale.vehicle_photos.extend(
        key
        for key in await db.scalars(
            select(Vehicle.photo_key).where(
                Vehicle.group_id == home_id, Vehicle.photo_key.is_not(None)
            )
        )
        if key
    )
    await db.execute(delete(Vehicle).where(Vehicle.group_id == home_id))

    # Nudges (members/completions cascade). The system Driveway category stays.
    await db.execute(delete(Reminder).where(Reminder.group_id == home_id))
    await db.execute(delete(HouseholdRoutine).where(HouseholdRoutine.group_id == home_id))
    await db.execute(delete(Todo).where(Todo.group_id == home_id))
    await db.execute(
        delete(TodoCategory).where(
            TodoCategory.group_id == home_id, TodoCategory.managed_source.is_(None)
        )
    )

    # Meals, Lists, Wishlists (child rows cascade).
    stale.meal_images.extend(
        key
        for key in await db.scalars(
            select(Meal.image_key).where(Meal.group_id == home_id, Meal.image_key.is_not(None))
        )
        if key
    )
    await db.execute(delete(MealPlanEntry).where(MealPlanEntry.group_id == home_id))
    await db.execute(delete(Meal).where(Meal.group_id == home_id))
    await db.execute(delete(HouseholdList).where(HouseholdList.group_id == home_id))
    await db.execute(delete(ListTemplate).where(ListTemplate.group_id == home_id))
    await db.execute(delete(Wishlist).where(Wishlist.home_id == home_id))

    # Calendar content. The primary Home Calendar and Personal Calendars stay
    # (a removed member's Personal Calendar cascades with the member below).
    await db.execute(delete(CalendarShare).where(CalendarShare.source_group_id == home_id))
    await db.execute(delete(CalendarEvent).where(CalendarEvent.group_id == home_id))
    await db.execute(delete(CalendarEventLabel).where(CalendarEventLabel.group_id == home_id))
    await db.execute(
        delete(HomeCalendar).where(
            HomeCalendar.group_id == home_id,
            HomeCalendar.owner_user_id.is_(None),
            HomeCalendar.is_primary.is_(False),
        )
    )
    await db.execute(
        delete(HomeCalendarHighlightSettings).where(
            HomeCalendarHighlightSettings.group_id == home_id
        )
    )

    # Pending invitations/join requests and the in-app inbox for this Home.
    await db.execute(delete(Invitation).where(Invitation.group_id == home_id))
    await db.execute(delete(HomeJoinRequest).where(HomeJoinRequest.group_id == home_id))
    await db.execute(delete(Notification).where(Notification.group_id == home_id))

    # Members. Accounts that belong only to this Home are fixture members and
    # are removed with their personal data; anyone who also belongs to
    # another Home only loses this membership.
    member_ids = list(
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == home_id, Membership.user_id != row.owner_user_id
            )
        )
    )
    other_homes = select(Membership.user_id).where(
        Membership.user_id.in_(member_ids), Membership.group_id != home_id
    )
    orphan_ids = list(
        await db.scalars(select(User.id).where(User.id.in_(member_ids), ~User.id.in_(other_homes)))
    )
    stale.avatars.extend(
        key
        for key in await db.scalars(
            select(User.avatar_key).where(
                User.id.in_([*orphan_ids, row.owner_user_id]), User.avatar_key.is_not(None)
            )
        )
        if key
    )
    await _purge_budgets(db, [*orphan_ids, row.owner_user_id])
    if member_ids:
        await db.execute(
            delete(Membership).where(
                Membership.group_id == home_id, Membership.user_id.in_(member_ids)
            )
        )
    if orphan_ids:
        await db.execute(delete(User).where(User.id.in_(orphan_ids)))

    # Owner's personal showcase settings return to defaults until reseeded.
    await db.execute(
        delete(NotificationPreferences).where(NotificationPreferences.user_id == row.owner_user_id)
    )
    owner = await db.get(User, row.owner_user_id)
    if owner is not None:
        owner.avatar_key = None
        owner.avatar_updated_at = None
        owner.birth_year = owner.birth_month = owner.birth_day = None
    await db.flush()
    return stale
