"""Home-scoped Family retention and purge lifecycle.

The destructive set is explicit. User-owned records, the Free calendar,
independent shares, billing, security and audit history are not purge targets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.entitlements import (
    get_home_subscription,
    resolve_effective_plan,
    transition_expired_family_home,
)
from mykhaya.models import (
    CalendarEvent,
    CalendarEventActivity,
    CalendarEventException,
    CalendarEventMember,
    CalendarShare,
    ChildProfile,
    FeatureOverride,
    GuardianAssignment,
    HomeCalendar,
    HomeRetentionLifecycle,
    HomeRetentionMembership,
    HomeRetentionState,
    HomeSubscription,
    HomeSubscriptionEvent,
    HouseholdList,
    HouseholdListItem,
    HouseholdRelationship,
    HouseholdRoutine,
    HouseholdRoutineCompletion,
    HouseholdRoutineMember,
    Meal,
    MealIngredient,
    MealPlanEntry,
    MealPlanParticipant,
    Membership,
    Reminder,
    ReminderCompletion,
    ReminderMember,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    Todo,
    TodoMember,
    Wishlist,
    WishlistGuestSession,
    WishlistItem,
    WishlistItemReservation,
    WishlistShare,
)

RETENTION_DAYS = 90


async def _home_lock(db: AsyncSession, home_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"family-retention:{home_id}"},
    )


async def _retained_user_id(db: AsyncSession, home_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(Membership.user_id)
        .where(Membership.group_id == home_id, Membership.removed_at.is_(None))
        .order_by(
            (Membership.relationship == HouseholdRelationship.home_admin).desc(),
            Membership.created_at.asc(),
            Membership.id.asc(),
        )
        .limit(1)
    )


async def _snapshot_disconnected_members(
    db: AsyncSession,
    lifecycle: HomeRetentionLifecycle,
    home_id: uuid.UUID,
    expiry: datetime,
) -> None:
    retained_user_id = await _retained_user_id(db, home_id)
    memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.group_id == home_id,
                Membership.removed_at == expiry,
                Membership.user_id != retained_user_id,
            )
        )
    ).all()
    for membership in memberships:
        db.add(
            HomeRetentionMembership(
                lifecycle_id=lifecycle.id,
                membership_id=membership.id,
                user_id=membership.user_id,
                relationship=membership.relationship,
            )
        )


async def start_family_retention(
    db: AsyncSession, home_id: uuid.UUID, *, now: datetime | None = None
) -> HomeRetentionLifecycle | None:
    """Create one retention cycle only after an actual Family expiry."""
    effective_now = now or datetime.now(UTC)
    await _home_lock(db, home_id)
    subscription = await get_home_subscription(db, home_id)
    if subscription is None or subscription.provider != SubscriptionProvider.stripe:
        return None
    if subscription.status not in {
        SubscriptionStatus.cancel_at_period_end,
        SubscriptionStatus.cancelled,
    }:
        return None
    expiry = subscription.current_period_end
    if expiry is None or expiry > effective_now:
        return None

    lifecycle = await db.scalar(
        select(HomeRetentionLifecycle)
        .where(HomeRetentionLifecycle.home_id == home_id)
        .with_for_update()
    )
    if lifecycle is None:
        lifecycle = HomeRetentionLifecycle(
            home_id=home_id,
            state=HomeRetentionState.retained_free,
            family_expired_at=expiry,
            retention_deadline=expiry + timedelta(days=RETENTION_DAYS),
        )
        db.add(lifecycle)
        await db.flush()
        await _snapshot_disconnected_members(db, lifecycle, home_id, expiry)
        db.add(
            HomeSubscriptionEvent(
                group_id=home_id,
                event_type="family_retention_started",
                from_plan=subscription.plan,
                to_plan=SubscriptionPlan.free,
                from_provider=subscription.provider,
                to_provider=subscription.provider,
                from_status=subscription.status,
                to_status=subscription.status,
                reason="90-day Family data retention started at authoritative expiry.",
            )
        )
    elif lifecycle.state == HomeRetentionState.restored and expiry > lifecycle.family_expired_at:
        lifecycle.state = HomeRetentionState.retained_free
        lifecycle.family_expired_at = expiry
        lifecycle.retention_deadline = expiry + timedelta(days=RETENTION_DAYS)
        lifecycle.purge_started_at = None
        lifecycle.purged_at = None
        lifecycle.restored_at = None
        await _snapshot_disconnected_members(db, lifecycle, home_id, expiry)
    return lifecycle


async def restore_family_retention(
    db: AsyncSession, home_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    """Restore Family data, reactivating Child memberships only."""
    effective_now = now or datetime.now(UTC)
    await _home_lock(db, home_id)
    subscription = await get_home_subscription(db, home_id)
    if subscription is None or resolve_effective_plan(subscription) != SubscriptionPlan.family:
        return False
    lifecycle = await db.scalar(
        select(HomeRetentionLifecycle)
        .where(HomeRetentionLifecycle.home_id == home_id)
        .with_for_update()
    )
    if lifecycle is None or lifecycle.state not in {
        HomeRetentionState.retained_free,
        HomeRetentionState.purge_pending,
    }:
        return False
    if lifecycle.retention_deadline <= effective_now:
        return False

    snapshots = (
        await db.scalars(
            select(HomeRetentionMembership)
            .where(HomeRetentionMembership.lifecycle_id == lifecycle.id)
            .with_for_update()
        )
    ).all()
    for snapshot in snapshots:
        if snapshot.relationship != HouseholdRelationship.child:
            continue
        membership = await db.get(Membership, snapshot.membership_id)
        if membership is not None and membership.removed_at is not None:
            membership.removed_at = None
            snapshot.restored_at = effective_now

    await db.execute(
        text(
            "UPDATE home_entitlement_grants SET revoked_at = NULL "
            "WHERE source_group_id = :home_id AND revoked_at = :expiry"
        ),
        {"home_id": home_id, "expiry": lifecycle.family_expired_at},
    )
    lifecycle.state = HomeRetentionState.restored
    lifecycle.restored_at = effective_now
    return True


async def _delete_ids(db: AsyncSession, model: object, column: object, ids: list[uuid.UUID]) -> None:
    if ids:
        await db.execute(delete(model).where(column.in_(ids)))  # type: ignore[attr-defined]


async def purge_family_home(
    db: AsyncSession, home_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    """Purge only eligible Family/Home-owned data after the deadline."""
    effective_now = now or datetime.now(UTC)
    await _home_lock(db, home_id)
    lifecycle = await db.scalar(
        select(HomeRetentionLifecycle)
        .where(HomeRetentionLifecycle.home_id == home_id)
        .with_for_update()
    )
    if lifecycle is None or lifecycle.state not in {
        HomeRetentionState.retained_free,
        HomeRetentionState.purge_pending,
    }:
        return False
    if lifecycle.retention_deadline > effective_now:
        return False

    subscription = await get_home_subscription(db, home_id)
    if subscription is not None and resolve_effective_plan(subscription) == SubscriptionPlan.family:
        lifecycle.state = HomeRetentionState.restored
        lifecycle.restored_at = effective_now
        return False

    lifecycle.state = HomeRetentionState.purge_pending
    lifecycle.purge_started_at = effective_now
    await db.flush()

    secondary_ids = list(
        (
            await db.scalars(
                select(HomeCalendar.id).where(
                    HomeCalendar.group_id == home_id,
                    HomeCalendar.owner_user_id.is_(None),
                    HomeCalendar.is_primary.is_(False),
                )
            )
        ).all()
    )
    shared_ids = set(
        (
            await db.scalars(
                select(CalendarShare.calendar_id).where(
                    CalendarShare.calendar_id.in_(secondary_ids),
                    CalendarShare.revoked_at.is_(None),
                )
            )
        ).all()
    )
    purge_calendar_ids = [calendar_id for calendar_id in secondary_ids if calendar_id not in shared_ids]
    event_ids = list(
        (await db.scalars(select(CalendarEvent.id).where(CalendarEvent.calendar_id.in_(purge_calendar_ids)))).all()
    )
    await _delete_ids(db, CalendarEventActivity, CalendarEventActivity.event_id, event_ids)
    await _delete_ids(db, CalendarEventException, CalendarEventException.event_id, event_ids)
    await _delete_ids(db, CalendarEventMember, CalendarEventMember.event_id, event_ids)
    await _delete_ids(db, CalendarEvent, CalendarEvent.id, event_ids)
    await _delete_ids(db, HomeCalendar, HomeCalendar.id, purge_calendar_ids)

    routine_ids = list((await db.scalars(select(HouseholdRoutine.id).where(
        HouseholdRoutine.group_id == home_id, HouseholdRoutine.scope == "household"
    ))).all())
    await _delete_ids(db, HouseholdRoutineMember, HouseholdRoutineMember.routine_id, routine_ids)
    await _delete_ids(db, HouseholdRoutineCompletion, HouseholdRoutineCompletion.routine_id, routine_ids)
    await _delete_ids(db, HouseholdRoutine, HouseholdRoutine.id, routine_ids)

    reminder_ids = list((await db.scalars(select(Reminder.id).where(
        Reminder.group_id == home_id, Reminder.scope == "household"
    ))).all())
    await _delete_ids(db, ReminderMember, ReminderMember.reminder_id, reminder_ids)
    await _delete_ids(db, ReminderCompletion, ReminderCompletion.reminder_id, reminder_ids)
    await _delete_ids(db, Reminder, Reminder.id, reminder_ids)

    todo_ids = list((await db.scalars(select(Todo.id).where(
        Todo.group_id == home_id, Todo.scope == "household"
    ))).all())
    await _delete_ids(db, TodoMember, TodoMember.todo_id, todo_ids)
    await _delete_ids(db, Todo, Todo.id, todo_ids)

    entry_ids = list((await db.scalars(select(MealPlanEntry.id).where(MealPlanEntry.group_id == home_id))).all())
    await _delete_ids(db, MealPlanParticipant, MealPlanParticipant.meal_plan_entry_id, entry_ids)
    await _delete_ids(db, MealPlanEntry, MealPlanEntry.id, entry_ids)
    meal_ids = list((await db.scalars(select(Meal.id).where(Meal.group_id == home_id))).all())
    await _delete_ids(db, MealIngredient, MealIngredient.meal_id, meal_ids)
    await _delete_ids(db, Meal, Meal.id, meal_ids)

    list_ids = list((await db.scalars(select(HouseholdList.id).where(HouseholdList.group_id == home_id))).all())
    await _delete_ids(db, HouseholdListItem, HouseholdListItem.list_id, list_ids)
    await _delete_ids(db, HouseholdList, HouseholdList.id, list_ids)

    wishlist_ids = list((await db.scalars(select(Wishlist.id).where(
        Wishlist.home_id == home_id, Wishlist.home_visible.is_(True)
    ))).all())
    wishlist_item_ids = list((await db.scalars(
        select(WishlistItem.id).where(WishlistItem.wishlist_id.in_(wishlist_ids))
    )).all())
    wishlist_share_ids = list((await db.scalars(
        select(WishlistShare.id).where(WishlistShare.wishlist_id.in_(wishlist_ids))
    )).all())
    await _delete_ids(db, WishlistItemReservation, WishlistItemReservation.wishlist_item_id, wishlist_item_ids)
    await _delete_ids(db, WishlistGuestSession, WishlistGuestSession.share_id, wishlist_share_ids)
    await _delete_ids(db, WishlistShare, WishlistShare.id, wishlist_share_ids)
    await _delete_ids(db, WishlistItem, WishlistItem.id, wishlist_item_ids)
    await _delete_ids(db, Wishlist, Wishlist.id, wishlist_ids)

    child_profile_ids = list((await db.scalars(select(ChildProfile.id).where(ChildProfile.group_id == home_id))).all())
    child_membership_ids = list((await db.scalars(select(Membership.id).where(
        Membership.group_id == home_id, Membership.relationship == HouseholdRelationship.child
    ))).all())
    await _delete_ids(db, GuardianAssignment, GuardianAssignment.child_profile_id, child_profile_ids)
    await _delete_ids(db, ChildProfile, ChildProfile.id, child_profile_ids)
    await _delete_ids(db, Membership, Membership.id, child_membership_ids)

    await db.execute(delete(FeatureOverride).where(FeatureOverride.group_id == home_id))
    db.add(
        HomeSubscriptionEvent(
            group_id=home_id,
            event_type="family_data_purged",
            from_plan=subscription.plan if subscription else SubscriptionPlan.free,
            to_plan=SubscriptionPlan.free,
            from_provider=subscription.provider if subscription else SubscriptionProvider.free,
            to_provider=subscription.provider if subscription else SubscriptionProvider.free,
            from_status=subscription.status if subscription else SubscriptionStatus.active,
            to_status=subscription.status if subscription else SubscriptionStatus.active,
            reason="Eligible Home-owned Family data permanently purged after retention deadline.",
        )
    )
    lifecycle.state = HomeRetentionState.purged
    lifecycle.purged_at = effective_now
    return True


async def scan_family_retention(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Bounded scheduler scan; duplicate runs are safe."""
    effective_now = now or datetime.now(UTC)
    subscriptions = (
        await db.scalars(
            select(HomeSubscription.group_id).where(
                HomeSubscription.provider == SubscriptionProvider.stripe,
                HomeSubscription.status.in_((SubscriptionStatus.cancel_at_period_end, SubscriptionStatus.cancelled)),
                HomeSubscription.current_period_end.is_not(None),
                HomeSubscription.current_period_end <= effective_now,
            ).limit(100)
        )
    ).all()
    processed = 0
    for home_id in subscriptions:
        await transition_expired_family_home(db, home_id, now=effective_now)
        if await start_family_retention(db, home_id, now=effective_now):
            processed += 1

    due = (
        await db.scalars(
            select(HomeRetentionLifecycle.home_id).where(
                HomeRetentionLifecycle.state == HomeRetentionState.retained_free,
                HomeRetentionLifecycle.retention_deadline <= effective_now,
            ).limit(100)
        )
    ).all()
    for home_id in due:
        if await purge_family_home(db, home_id, now=effective_now):
            processed += 1
    return processed
