"""Explicit, local/operator-only Apple TestFlight review fixture.

This module is never imported by application startup. It is intentionally a small
direct-DB management command because there is no existing seed service, while all
rows still use the application's normal ORM models and password hasher.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription, record_subscription_event
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
    SubscriptionPlan,
    SubscriptionProvider,
    User,
)
from mykhaya.security import normalise_email, password_hash

FIXTURE_EMAIL = "apple-review@mykhaya.app"
FIXTURE_HOME_NAME = "Apple Review Home"
# A stable, unique fixture marker. It is not derived from display names and is
# also the Home's child-login code, which is already a unique Home identifier.
FIXTURE_HOME_CODE = "ARVHOME27"
FIXTURE_PASSWORD_ENV = "MYKHAYA_APPLE_REVIEW_PASSWORD"  # noqa: S105
TIMEZONE = "Europe/London"

MEMBER_EMAILS = {
    "Alex Review": FIXTURE_EMAIL,
    "Jamie Review": "jamie-review@mykhaya.app",
    "Sam Review": "managed-child-sam-review@managed.mykhaya.invalid",
}


def _password() -> str:
    value = os.environ.get(FIXTURE_PASSWORD_ENV, "")
    if not value:
        raise RuntimeError(
            f"{FIXTURE_PASSWORD_ENV} must be set; the review password is never stored "
            "in source or logs"
        )
    return value


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(TIMEZONE))


def fixture_event_specs(today: date) -> tuple[tuple[str, date, int, int, int, int, str], ...]:
    return (
        ("School pickup", today, 15, 15, 15, 45, "School"),
        ("Family dinner", today, 18, 30, 19, 30, "Home"),
        ("Dentist appointment", today + timedelta(days=1), 10, 0, 10, 45, "Dental clinic"),
        ("Swimming lesson", today + timedelta(days=2), 17, 0, 18, 0, "Leisure centre"),
        ("Family day out", today + timedelta(days=4), 10, 0, 15, 0, "City park"),
    )


def fixture_meal_dates(today: date) -> tuple[date, ...]:
    monday = today + timedelta(days=(7 - today.weekday()) % 7)
    return tuple(monday + timedelta(days=offset) for offset in range(4))


async def _user(
    db: AsyncSession, email: str, name: str, *, password: str | None = None
) -> User:
    existing = await db.scalar(select(User).where(User.email == normalise_email(email)))
    if existing:
        existing.display_name = name
        existing.is_active = True
        existing.email_verified_at = datetime.now(UTC)
        if password is not None:
            identity = await db.scalar(
                select(AuthIdentity).where(AuthIdentity.user_id == existing.id)
            )
            if identity is None:
                identity = AuthIdentity(
                    user_id=existing.id, password_hash=password_hash.hash(password)
                )
                db.add(identity)
            else:
                identity.password_hash = password_hash.hash(password)
        return existing
    user = User(
        email=normalise_email(email),
        display_name=name,
        email_verified_at=datetime.now(UTC),
        timezone=TIMEZONE,
    )
    db.add(user)
    await db.flush()
    if password is not None:
        db.add(AuthIdentity(user_id=user.id, password_hash=password_hash.hash(password)))
    return user


async def _remove_existing_fixture(db: AsyncSession) -> None:
    group = await db.scalar(select(Group).where(Group.child_login_code == FIXTURE_HOME_CODE))
    if group is None:
        return
    owner = await db.get(User, group.created_by)
    if (
        owner is None
        or normalise_email(owner.email) != FIXTURE_EMAIL
        or group.name != FIXTURE_HOME_NAME
    ):
        raise RuntimeError("Refusing to remove a Home that does not match the Apple fixture marker")
    member_ids = list(
        await db.scalars(select(Membership.user_id).where(Membership.group_id == group.id))
    )
    await db.delete(group)
    await db.flush()
    for user_id in set(member_ids):
        remaining = await db.scalar(select(Membership.id).where(Membership.user_id == user_id))
        if remaining is None:
            await db.execute(delete(AuthIdentity).where(AuthIdentity.user_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))


async def create_fixture() -> None:
    password = _password()
    async with SessionFactory() as db:
        await _remove_existing_fixture(db)
        owner = await _user(db, FIXTURE_EMAIL, "Alex Review", password=password)
        jamie = await _user(db, MEMBER_EMAILS["Jamie Review"], "Jamie Review")
        sam = await _user(db, MEMBER_EMAILS["Sam Review"], "Sam Review")
        group = Group(
            name=FIXTURE_HOME_NAME,
            created_by=owner.id,
            child_login_code=FIXTURE_HOME_CODE,
        )
        db.add(group)
        await db.flush()
        members = [
            Membership(
                group_id=group.id, user_id=owner.id, role=Role.owner,
                relationship=HouseholdRelationship.home_admin,
                permission_profile=PermissionProfile.home_admin,
            ),
            Membership(
                group_id=group.id, user_id=jamie.id, role=Role.adult_member,
                relationship=HouseholdRelationship.adult,
                permission_profile=PermissionProfile.standard_partner,
            ),
            Membership(
                group_id=group.id, user_id=sam.id, role=Role.member,
                relationship=HouseholdRelationship.child,
                permission_profile=PermissionProfile.child_restricted,
            ),
        ]
        db.add_all(members)
        await db.flush()
        profile = ChildProfile(
            membership_id=members[2].id, group_id=group.id,
            age_band=ChildAgeBand.age_13_15, permissions={},
        )
        db.add(profile)
        db.add_all(
            [
                GuardianAssignment(
                    child_profile_id=profile.id,
                    guardian_membership_id=members[0].id,
                    assigned_by_user_id=owner.id,
                ),
                GuardianAssignment(
                    child_profile_id=profile.id,
                    guardian_membership_id=members[1].id,
                    assigned_by_user_id=owner.id,
                ),
            ]
        )
        calendar = HomeCalendar(
            group_id=group.id, name="Home Calendar", timezone=TIMEZONE, is_primary=True
        )
        db.add(calendar)
        subscription = await ensure_home_subscription(db, group.id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.complimentary
        subscription.complimentary_reason = "Apple TestFlight review fixture"
        await record_subscription_event(
            db, group.id, event_type="fixture.created", to_plan=SubscriptionPlan.family,
            to_provider=SubscriptionProvider.complimentary,
            reason="Apple TestFlight review fixture",
        )
        await db.flush()

        now = datetime.now(ZoneInfo(TIMEZONE))
        today = now.date()
        for title, day, sh, sm, eh, em, location in fixture_event_specs(today):
            event = CalendarEvent(
                group_id=group.id, calendar_id=calendar.id, title=title,
                start_at=_at(day, sh, sm), end_at=_at(day, eh, em),
                timezone=TIMEZONE, location_text=location, created_by=owner.id,
            )
            db.add(event)
            await db.flush()
            db.add_all(
                [
                    CalendarEventMember(group_id=group.id, event_id=event.id, user_id=user.id)
                    for user in (owner, jamie, sam)
                ]
            )

        for title, repeat_unit in (("Feed the dog", "daily"), ("Put bins out", "weekly")):
            routine = HouseholdRoutine(
                group_id=group.id, title=title, scope=RoutineScope.household,
                interval_weeks=1, repeat_unit=repeat_unit, week_anchor_date=today,
                reminder_timing=RoutineReminderTiming.evening_before,
                enabled=True, start_date=today, created_by=owner.id,
            )
            db.add(routine)
            await db.flush()
            db.add_all(
                [
                    HouseholdRoutineMember(routine_id=routine.id, user_id=user.id)
                    for user in (owner, jamie)
                ]
            )
        for title, due in (
            ("Order school lunches", today + timedelta(days=1)),
            ("Call grandparents", today + timedelta(days=3)),
        ):
            reminder = Reminder(
                group_id=group.id, title=title, scope=RoutineScope.household,
                due_date=due, due_time=time(9), repeat=ReminderRepeat.never,
                cadence=ReminderCadence.once, enabled=True, created_by=owner.id,
            )
            db.add(reminder)
            await db.flush()
            db.add_all(
                [
                    ReminderMember(reminder_id=reminder.id, user_id=user.id)
                    for user in (owner, jamie)
                ]
            )

        meal_names = ("Spaghetti Bolognese", "Chicken Fajitas", "Homemade Pizza", "Curry")
        for meal_date, name in zip(fixture_meal_dates(today), meal_names, strict=True):
            meal = Meal(
                group_id=group.id, name=name, meal_type=MealType.dinner, created_by=owner.id
            )
            db.add(meal)
            await db.flush()
            entry = MealPlanEntry(
                group_id=group.id, meal_id=meal.id, date=meal_date,
                meal_slot=MealSlot.dinner, time=time(18), created_by=owner.id,
            )
            db.add(entry)
            await db.flush()
            db.add_all(
                [
                    MealPlanParticipant(meal_plan_entry_id=entry.id, user_id=user.id)
                    for user in (owner, jamie, sam)
                ]
            )

        shopping = HouseholdList(
            group_id=group.id, name="Shopping", icon="shopping", created_by=owner.id
        )
        db.add(shopping)
        await db.flush()
        db.add_all(
            [
                HouseholdListItem(
                    list_id=shopping.id, position=index, text=item, created_by=owner.id
                )
                for index, item in enumerate(("Milk", "Bread", "Apples", "Pasta", "Coffee"))
            ]
        )
        await db.commit()
    print(f"Created Apple review fixture Home '{FIXTURE_HOME_NAME}' ({FIXTURE_HOME_CODE})")


async def remove_fixture() -> None:
    async with SessionFactory() as db:
        await _remove_existing_fixture(db)
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
