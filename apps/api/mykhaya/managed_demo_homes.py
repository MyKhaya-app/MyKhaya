"""Shared lifecycle service for explicitly managed Demo/Test Homes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.models import (
    AuthIdentity,
    CalendarEvent,
    CalendarEventMember,
    ChildAgeBand,
    ChildProfile,
    Group,
    GuardianAssignment,
    HomeCalendar,
    HouseholdList,
    HouseholdListItem,
    HouseholdRelationship,
    HouseholdRoutine,
    HouseholdRoutineMember,
    ManagedDemoHome,
    ManagedDemoStatus,
    ManagedDemoType,
    Meal,
    MealPlanEntry,
    MealPlanParticipant,
    MealSlot,
    MealType,
    Membership,
    PermissionProfile,
    Reminder,
    ReminderCadence,
    ReminderMember,
    ReminderRepeat,
    Role,
    RoutineReminderTiming,
    RoutineScope,
    Session,
    SubscriptionPlan,
    SubscriptionProvider,
    TrustedDevice,
    User,
)
from mykhaya.security import generate_home_code, normalise_email, password_hash

FIXTURE_TIMEZONE = ZoneInfo("Europe/London")


class ManagedDemoError(RuntimeError):
    pass


class ManagedDemoService:
    """Owns lifecycle state; templates remain explicit functions in fixture modules."""

    @staticmethod
    async def get(db: AsyncSession, fixture_key: str) -> ManagedDemoHome | None:
        return cast(
            ManagedDemoHome | None,
            await db.scalar(
                select(ManagedDemoHome).where(ManagedDemoHome.fixture_key == fixture_key)
            ),
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        fixture_key: str,
        display_name: str,
        fixture_type: ManagedDemoType,
        email: str,
        password: str,
        created_by: uuid.UUID | None,
        expires_at: datetime | None = None,
        enabled: bool = True,
        home_code: str | None = None,
    ) -> ManagedDemoHome:
        """Create the managed identity and Home; callers then seed a template."""
        email = normalise_email(email)
        if await ManagedDemoService.get(db, fixture_key):
            raise ManagedDemoError("Fixture key already exists")
        if await db.scalar(select(User).where(User.email == email)):
            raise ManagedDemoError("Refusing to adopt an existing customer account")
        user = User(
            email=email,
            display_name=display_name,
            email_verified_at=datetime.now(UTC),
            is_active=enabled,
        )
        db.add(user)
        await db.flush()
        db.add(AuthIdentity(user_id=user.id, password_hash=password_hash.hash(password)))
        home = Group(
            name=display_name,
            created_by=user.id,
            child_login_code=home_code or generate_home_code(),
        )
        db.add(home)
        await db.flush()
        db.add(
            Membership(
                group_id=home.id,
                user_id=user.id,
                role=Role.owner,
                relationship=HouseholdRelationship.home_admin,
                permission_profile=PermissionProfile.home_admin,
            )
        )
        db.add(HomeCalendar(group_id=home.id, name="Home Calendar", is_primary=True))
        row = await ManagedDemoService.register(
            db,
            fixture_key=fixture_key,
            display_name=display_name,
            fixture_type=fixture_type,
            home_id=home.id,
            owner_user_id=user.id,
            created_by=created_by,
            expires_at=expires_at,
        )
        row.status = ManagedDemoStatus.enabled if enabled else ManagedDemoStatus.disabled
        if not enabled:
            row.disabled_at = datetime.now(UTC)
        from mykhaya.entitlements import ensure_home_subscription

        subscription = await ensure_home_subscription(db, home.id)
        # Free Plan Demo must exercise the real Free-plan entitlement path
        # (see docs/architecture/commercial-entitlements.md) rather than a
        # Home override — every other template is a Family-access fixture
        # (App Store review, sales demo, generic QA), unchanged.
        subscription.plan = (
            SubscriptionPlan.free
            if fixture_type == ManagedDemoType.free_demo
            else SubscriptionPlan.family
        )
        subscription.provider = SubscriptionProvider.complimentary
        subscription.complimentary_reason = f"Managed Demo/Test Home: {fixture_key}"
        await ManagedDemoService.seed_template(db, row)
        await db.flush()
        return row

    @staticmethod
    async def seed_template(db: AsyncSession, row: ManagedDemoHome) -> None:
        """Seed the selected supported template using normal Home-owned rows."""
        owner = await db.get(User, row.owner_user_id)
        calendar = await db.scalar(
            select(HomeCalendar).where(
                HomeCalendar.group_id == row.home_id, HomeCalendar.is_primary.is_(True)
            )
        )
        if owner is None or calendar is None:
            raise ManagedDemoError("Managed Home is missing its owner or primary calendar")
        today = datetime.now(FIXTURE_TIMEZONE).date()
        member_specs: tuple[tuple[str, str, bool], ...]
        events: tuple[tuple[str, int, int, int, int], ...]
        routines: tuple[tuple[str, str], ...]
        reminders: tuple[tuple[str, int], ...]
        meals: tuple[str, ...]
        lists: tuple[tuple[str, tuple[str, ...]], ...]
        # Free Plan Demo's own events live on the owner's Personal Calendar
        # (owner_user_id IS NOT NULL), not the shared "Home Calendar" every
        # template gets from ManagedDemoService.create — matching what a
        # genuine solo Free signup gets (see mykhaya.calendar_provisioning
        # and mykhaya.routers.groups.create_group, which provision both for
        # every new Home) rather than hacking the shared calendar away.
        # calendar.max_calendars=1 on Free then makes the entitlement system
        # itself classify the shared Home Calendar as read_only_due_to_plan,
        # exactly as it would for a real Free Home — nothing here needs to
        # fake that.
        events_calendar_id = calendar.id
        if row.fixture_type == ManagedDemoType.apple_review:
            member_specs = (
                ("Jamie Review", "jamie-review@mykhaya.app", False),
                ("Sam Review", "managed-child-sam-review@managed.mykhaya.invalid", True),
            )
            events = (
                ("School pickup", 0, 15, 15, 45),
                ("Family dinner", 0, 18, 19, 30),
                ("Dentist appointment", 1, 10, 10, 45),
                ("Swimming lesson", 2, 17, 18, 0),
                ("Family day out", 4, 10, 15, 0),
            )
            routines = (("Feed the dog", "daily"), ("Put bins out", "weekly"))
            reminders = (("Order school lunches", 1), ("Call grandparents", 3))
            meals = ("Spaghetti Bolognese", "Chicken Fajitas", "Homemade Pizza", "Curry")
            lists = (("Shopping", ("Milk", "Bread", "Apples", "Pasta", "Coffee")),)
        elif row.fixture_type == ManagedDemoType.free_demo:
            # Free is a single-person personal organiser (see
            # docs/architecture/commercial-entitlements.md) — no second
            # member, no Nudges/Meal Plans/Wishlists/External Sharing rows
            # of any kind, so those tuples stay empty rather than seeding
            # Family-only content this fixture exists to prove is absent.
            member_specs = ()
            personal_calendar = await ensure_personal_calendar(db, row.home_id, owner.id)
            events_calendar_id = personal_calendar.id
            events = (
                ("Dentist appointment", 1, 10, 10, 45),
                ("Personal appointment", 0, 15, 15, 45),
                ("Grocery run", 2, 9, 9, 45),
                ("Weekend activity", 5, 11, 13, 0),
            )
            routines = ()
            reminders = ()
            meals = ()
            # Exactly two Lists, deliberately at the Free plan's
            # lists.max_lists=2 limit — see the module docstring.
            lists = (
                ("Groceries", ("Milk", "Bread", "Eggs", "Coffee")),
                ("Weekend jobs", ("Mow the lawn", "Wash the car", "Tidy the garage")),
            )
        else:
            member_specs = (
                ("Jamie Carter", "jamie-carter@demo.mykhaya.invalid", False),
                ("Sophie Carter", "sophie-carter@managed.mykhaya.invalid", True),
                ("Noah Carter", "noah-carter@managed.mykhaya.invalid", True),
            )
            events = (
                ("School pickup", 0, 15, 15, 45),
                ("Football training", 0, 17, 18, 30),
                ("Family dinner", 0, 18, 19, 30),
                ("Dentist", 1, 10, 10, 45),
                ("Grocery delivery", 1, 14, 15, 0),
                ("Swimming lesson", 2, 17, 18, 0),
                ("Parent evening", 3, 18, 20, 0),
                ("Birthday party", 4, 13, 16, 0),
            )
            routines = (
                ("Feed the dog", "daily"),
                ("Pack school bags", "daily"),
                ("Put bins out", "weekly"),
                ("Water plants", "weekly"),
            )
            reminders = (
                ("Order school lunches", 1),
                ("Pay nursery invoice", 2),
                ("Call grandparents", 3),
            )
            meals = (
                "Pasta primavera",
                "Chicken fajitas",
                "Homemade pizza",
                "Vegetable curry",
                "Fish tacos",
            )
            lists = (
                ("Shopping", ("Milk", "Bread", "Apples", "Pasta", "Coffee")),
                ("Weekend Jobs", ("Cut the grass", "Wash the car", "Sort recycling")),
                ("School Things", ("Glue sticks", "Pencils", "Notebooks")),
            )
        members = [owner]
        for name, email, is_child in member_specs:
            user = User(
                email=email, display_name=name, email_verified_at=datetime.now(UTC), is_active=True
            )
            db.add(user)
            await db.flush()
            membership = Membership(
                group_id=row.home_id,
                user_id=user.id,
                role=Role.member if is_child else Role.adult_member,
                relationship=HouseholdRelationship.child
                if is_child
                else HouseholdRelationship.adult,
                permission_profile=PermissionProfile.child_restricted
                if is_child
                else PermissionProfile.standard_partner,
            )
            db.add(membership)
            await db.flush()
            if is_child:
                profile = ChildProfile(
                    membership_id=membership.id,
                    group_id=row.home_id,
                    age_band=ChildAgeBand.age_13_15,
                    permissions={},
                )
                db.add(profile)
                await db.flush()
                guardian_membership = await db.scalar(
                    select(Membership).where(
                        Membership.group_id == row.home_id,
                        Membership.user_id == owner.id,
                    )
                )
                if guardian_membership is None:
                    raise ManagedDemoError("Managed Home owner membership is missing")
                db.add(
                    GuardianAssignment(
                        child_profile_id=profile.id,
                        guardian_membership_id=guardian_membership.id,
                        assigned_by_user_id=owner.id,
                    )
                )
            members.append(user)
        for title, day_offset, start_hour, end_hour, end_minute in events:
            start = datetime.combine(
                today + timedelta(days=day_offset), time(start_hour, 0), tzinfo=FIXTURE_TIMEZONE
            )
            end = datetime.combine(
                today + timedelta(days=day_offset),
                time(end_hour, end_minute),
                tzinfo=FIXTURE_TIMEZONE,
            )
            event = CalendarEvent(
                group_id=row.home_id,
                calendar_id=events_calendar_id,
                title=title,
                start_at=start,
                end_at=end,
                timezone="Europe/London",
                created_by=owner.id,
            )
            db.add(event)
            await db.flush()
            db.add_all(
                [
                    CalendarEventMember(group_id=row.home_id, event_id=event.id, user_id=user.id)
                    for user in members
                ]
            )
        for title, repeat_unit in routines:
            routine = HouseholdRoutine(
                group_id=row.home_id,
                title=title,
                scope=RoutineScope.household,
                interval_weeks=1,
                repeat_unit=repeat_unit,
                week_anchor_date=today,
                reminder_timing=RoutineReminderTiming.evening_before,
                enabled=True,
                start_date=today,
                created_by=owner.id,
            )
            db.add(routine)
            await db.flush()
            db.add_all(
                [
                    HouseholdRoutineMember(routine_id=routine.id, user_id=user.id)
                    for user in members[:2]
                ]
            )
        for title, day_offset in reminders:
            reminder = Reminder(
                group_id=row.home_id,
                title=title,
                scope=RoutineScope.household,
                due_date=today + timedelta(days=day_offset),
                due_time=time(9),
                repeat=ReminderRepeat.never,
                cadence=ReminderCadence.once,
                enabled=True,
                created_by=owner.id,
            )
            db.add(reminder)
            await db.flush()
            db.add_all(
                [ReminderMember(reminder_id=reminder.id, user_id=user.id) for user in members[:2]]
            )
        monday = today + timedelta(days=(7 - today.weekday()) % 7)
        for offset, name in enumerate(meals):
            meal = Meal(
                group_id=row.home_id, name=name, meal_type=MealType.dinner, created_by=owner.id
            )
            db.add(meal)
            await db.flush()
            entry = MealPlanEntry(
                group_id=row.home_id,
                meal_id=meal.id,
                date=monday + timedelta(days=offset),
                meal_slot=MealSlot.dinner,
                time=time(18),
                created_by=owner.id,
            )
            db.add(entry)
            await db.flush()
            db.add_all(
                [
                    MealPlanParticipant(meal_plan_entry_id=entry.id, user_id=user.id)
                    for user in members
                ]
            )
        for list_name, items in lists:
            household_list = HouseholdList(
                group_id=row.home_id, name=list_name, icon="shopping", created_by=owner.id
            )
            db.add(household_list)
            await db.flush()
            db.add_all(
                [
                    HouseholdListItem(
                        list_id=household_list.id, position=index, text=item, created_by=owner.id
                    )
                    for index, item in enumerate(items)
                ]
            )
        row.refreshed_at = datetime.now(UTC)
        await db.flush()

    @staticmethod
    async def refresh_template(db: AsyncSession, row: ManagedDemoHome) -> None:
        """Delete only Home-owned content and reseed without changing lifecycle state."""
        member_ids = list(
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == row.home_id,
                    Membership.user_id != row.owner_user_id,
                )
            )
        )
        event_ids = list(
            await db.scalars(select(CalendarEvent.id).where(CalendarEvent.group_id == row.home_id))
        )
        routine_ids = list(
            await db.scalars(
                select(HouseholdRoutine.id).where(HouseholdRoutine.group_id == row.home_id)
            )
        )
        reminder_ids = list(
            await db.scalars(select(Reminder.id).where(Reminder.group_id == row.home_id))
        )
        meal_ids = list(await db.scalars(select(Meal.id).where(Meal.group_id == row.home_id)))
        entry_ids = list(
            await db.scalars(select(MealPlanEntry.id).where(MealPlanEntry.group_id == row.home_id))
        )
        list_ids = list(
            await db.scalars(select(HouseholdList.id).where(HouseholdList.group_id == row.home_id))
        )
        if event_ids:
            await db.execute(
                delete(CalendarEventMember).where(CalendarEventMember.event_id.in_(event_ids))
            )
            await db.execute(delete(CalendarEvent).where(CalendarEvent.id.in_(event_ids)))
        if routine_ids:
            await db.execute(
                delete(HouseholdRoutineMember).where(
                    HouseholdRoutineMember.routine_id.in_(routine_ids)
                )
            )
            await db.execute(delete(HouseholdRoutine).where(HouseholdRoutine.id.in_(routine_ids)))
        if reminder_ids:
            await db.execute(
                delete(ReminderMember).where(ReminderMember.reminder_id.in_(reminder_ids))
            )
            await db.execute(delete(Reminder).where(Reminder.id.in_(reminder_ids)))
        if entry_ids:
            await db.execute(
                delete(MealPlanParticipant).where(
                    MealPlanParticipant.meal_plan_entry_id.in_(entry_ids)
                )
            )
            await db.execute(delete(MealPlanEntry).where(MealPlanEntry.id.in_(entry_ids)))
        if meal_ids:
            await db.execute(delete(Meal).where(Meal.id.in_(meal_ids)))
        if list_ids:
            await db.execute(
                delete(HouseholdListItem).where(HouseholdListItem.list_id.in_(list_ids))
            )
            await db.execute(delete(HouseholdList).where(HouseholdList.id.in_(list_ids)))
        if member_ids:
            await db.execute(
                delete(ChildProfile).where(
                    ChildProfile.group_id == row.home_id,
                    ChildProfile.membership_id.in_(
                        select(Membership.id).where(Membership.user_id.in_(member_ids))
                    ),
                )
            )
            await db.execute(
                delete(Membership).where(
                    Membership.group_id == row.home_id, Membership.user_id.in_(member_ids)
                )
            )
            remaining_members = select(Membership.user_id).where(Membership.user_id.in_(member_ids))
            orphaned_member_ids = select(User.id).where(
                User.id.in_(member_ids), ~User.id.in_(remaining_members)
            )
            await db.execute(delete(User).where(User.id.in_(orphaned_member_ids)))
        await ManagedDemoService.seed_template(db, row)

    @staticmethod
    async def register(
        db: AsyncSession,
        *,
        fixture_key: str,
        display_name: str,
        fixture_type: ManagedDemoType,
        home_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        created_by: uuid.UUID | None,
        expires_at: datetime | None = None,
    ) -> ManagedDemoHome:
        existing = await ManagedDemoService.get(db, fixture_key)
        if existing is not None:
            if existing.home_id != home_id or existing.owner_user_id != owner_user_id:
                raise ManagedDemoError("Fixture key is already registered to another Home/account")
            return existing
        if await db.scalar(select(ManagedDemoHome).where(ManagedDemoHome.home_id == home_id)):
            raise ManagedDemoError("Home is already managed under another fixture")
        if await db.scalar(
            select(ManagedDemoHome).where(ManagedDemoHome.owner_user_id == owner_user_id)
        ):
            raise ManagedDemoError("Account is already managed under another fixture")
        row = ManagedDemoHome(
            fixture_key=fixture_key,
            display_name=display_name,
            fixture_type=fixture_type,
            home_id=home_id,
            owner_user_id=owner_user_id,
            created_by=created_by,
            expires_at=expires_at,
            refreshed_at=datetime.now(UTC),
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def set_enabled(db: AsyncSession, row: ManagedDemoHome, enabled: bool) -> ManagedDemoHome:
        row.status = ManagedDemoStatus.enabled if enabled else ManagedDemoStatus.disabled
        row.disabled_at = None if enabled else datetime.now(UTC)
        owner = await db.get(User, row.owner_user_id)
        if owner is None:
            raise ManagedDemoError("Managed owner account is missing")
        owner.is_active = enabled
        await db.flush()
        return row

    @staticmethod
    async def reset_password(db: AsyncSession, row: ManagedDemoHome, new_password: str) -> None:
        identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == row.owner_user_id).with_for_update()
        )
        if identity is None:
            raise ManagedDemoError("Managed owner account has no password identity")
        identity.password_hash = password_hash.hash(new_password)
        identity.password_changed_at = datetime.now(UTC)
        await db.execute(
            update(Session)
            .where(Session.user_id == row.owner_user_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await db.execute(
            update(TrustedDevice)
            .where(TrustedDevice.user_id == row.owner_user_id)
            .values(revoked_at=datetime.now(UTC))
        )

    @staticmethod
    async def set_expiry(
        db: AsyncSession, row: ManagedDemoHome, expires_at: datetime | None
    ) -> ManagedDemoHome:
        row.expires_at = expires_at
        # Expiry edits are configuration-only.  Re-enabling an expired fixture
        # is an explicit lifecycle action through set_enabled(True).
        await db.flush()
        return row

    @staticmethod
    async def refresh(db: AsyncSession, row: ManagedDemoHome) -> ManagedDemoHome:
        """Record a template refresh without changing account state."""
        row.refreshed_at = datetime.now(UTC)
        await db.flush()
        return row

    @staticmethod
    async def expire_due(db: AsyncSession, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        rows = (
            await db.scalars(
                select(ManagedDemoHome).where(
                    ManagedDemoHome.expires_at.is_not(None),
                    ManagedDemoHome.expires_at <= now,
                    ManagedDemoHome.status != ManagedDemoStatus.expired,
                )
            )
        ).all()
        for row in rows:
            row.status = ManagedDemoStatus.expired
            row.disabled_at = now
            owner = await db.get(User, row.owner_user_id)
            if owner is not None:
                owner.is_active = False
        await db.flush()
        return len(rows)

    @staticmethod
    async def delete(db: AsyncSession, row: ManagedDemoHome) -> None:
        home = await db.get(Group, row.home_id)
        if home is None:
            await db.delete(row)
            return
        owner_id = row.owner_user_id
        memberships = list(
            await db.scalars(select(Membership).where(Membership.user_id == owner_id))
        )
        if len(memberships) != 1 or memberships[0].group_id != row.home_id:
            raise ManagedDemoError("Refusing to delete an owner account used outside this fixture")
        # Bulk-delete via Core `delete()`, not ORM object deletion — with
        # the Membership row(s) above loaded into the session's identity
        # map, SQLAlchemy would otherwise try to NULL out their (NOT NULL)
        # group_id during `home`'s own flush, since Group.memberships
        # carries no delete cascade of its own (a Core statement bypasses
        # that relationship-cascade path entirely). Every other Home-owned
        # table already has ondelete="CASCADE" at the database level (see
        # mykhaya.models) and is never loaded into the ORM session here, so
        # deleting `home` below still removes all of it correctly.
        for membership in memberships:
            db.expunge(membership)
        await db.execute(delete(Membership).where(Membership.group_id == row.home_id))
        await db.delete(row)
        await db.delete(home)
        await db.flush()
        await db.execute(update(User).where(User.id == owner_id).values(is_active=False))
