"""Family-plan showcase seeders: household, Calendar, Nudges, Meals, Lists,
Wishlists and personal settings.

Each seeder writes the same ordinary Home-owned rows the product's own
endpoints write, with the same invariants (scope/owner rules, all-day UTC
bounds, member ids rather than copied names, processed images in the normal
storage seams). Nothing here bypasses an entitlement: the caller only runs a
seeder whose entitlement the Home's real plan grants (see
mykhaya.showcase.registry).
"""

from __future__ import annotations

import uuid
from calendar import isleap
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from mykhaya.attachments.processing import process_attachment_upload
from mykhaya.avatars.processing import process_avatar_upload
from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.colour_palette import PALETTE_HEX, ColourToken
from mykhaya.meal_images import get_meal_image_storage, meal_image_filename
from mykhaya.models import (
    CalendarEvent,
    CalendarEventLabel,
    CalendarEventMember,
    ChildProfile,
    GuardianAssignment,
    HomeCalendarHighlightSettings,
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
    MealSlot,
    Membership,
    NotificationPreferences,
    PermissionProfile,
    RecurrencePattern,
    Reminder,
    ReminderCompletion,
    ReminderMember,
    Role,
    RoutineScope,
    Todo,
    TodoCategory,
    TodoMember,
    User,
    Wishlist,
    WishlistItem,
    WishlistItemReservation,
    WishlistOccasion,
    WishlistReservationActorType,
)
from mykhaya.showcase import images, parker
from mykhaya.showcase.context import SHOWCASE_TIMEZONE_NAME, ShowcaseContext

# The same seven event categories a normal Home is created with
# (routers.groups.DEFAULT_LABELS), all active because the Home is on a paid
# plan — never extra system categories the product does not have.
_LABELS = (
    (parker.LABEL_FAMILY, "teal"),
    (parker.LABEL_SCHOOL, "purple"),
    (parker.LABEL_WORK, "emerald"),
    (parker.LABEL_APPOINTMENT, "orange"),
    (parker.LABEL_BIRTHDAY, "rose"),
    (parker.LABEL_ACTIVITY, "blue"),
    (parker.LABEL_OTHER, "slate"),
)


def _birthday(ctx: ShowcaseContext, spec: parker.MemberSpec) -> tuple[int, int, int]:
    when = ctx.day(spec.birthday_offset)
    year = when.year - spec.age_on_birthday
    if (when.month, when.day) == (2, 29) and not isleap(year):
        return year, 2, 28
    return year, when.month, when.day


async def _store_avatar(ctx: ShowcaseContext, user: User, spec: parker.MemberSpec) -> None:
    raw = images.approved_photo("avatars", spec.key) or images.render_avatar_illustration(
        spec.key, spec.avatar
    )
    # Same naming rule as routers.users._avatar_filename: a fresh,
    # unpredictable name per upload, never the user's id.
    key = f"{uuid.uuid4()}.webp"
    await get_avatar_storage(ctx.settings).save(key, process_avatar_upload(raw))
    ctx.written.avatars.append(key)
    user.avatar_key = key
    user.avatar_updated_at = datetime.now(UTC)


async def seed_household(ctx: ShowcaseContext) -> int:
    """Emma (the existing owner) plus James, Sophie and Oliver."""
    db = ctx.db
    owner_spec = parker.OWNER
    ctx.owner.display_name = owner_spec.name
    ctx.owner.timezone = SHOWCASE_TIMEZONE_NAME
    ctx.owner.birth_year, ctx.owner.birth_month, ctx.owner.birth_day = _birthday(ctx, owner_spec)
    ctx.owner_membership.colour = owner_spec.colour
    await _store_avatar(ctx, ctx.owner, owner_spec)
    ctx.users[owner_spec.key] = ctx.owner
    ctx.memberships[owner_spec.key] = ctx.owner_membership
    ctx.personal_calendars[owner_spec.key] = await ensure_personal_calendar(
        db, ctx.home_id, ctx.owner.id
    )

    for spec in parker.MEMBERS:
        # Members have no credentials: only the primary demo account signs
        # in. Identities are namespaced to this fixture so two showcase Homes
        # never collide on the unique email, and use reserved domains that
        # can never reach a real inbox: children the managed-child .invalid
        # convention (routers.children, never exposed by the API); adults the
        # IANA-reserved example.com, because an adult member's address is
        # shown and validated as an EmailStr where .invalid is rejected.
        domain = "managed.mykhaya.invalid" if spec.is_child else "example.com"
        email = ctx.preserved_member_emails.get(
            spec.name, f"{spec.email_local}+{ctx.fixture_key}@{domain}"
        )
        user = User(
            email=email,
            display_name=spec.name,
            email_verified_at=datetime.now(UTC),
            is_active=True,
            timezone=SHOWCASE_TIMEZONE_NAME,
        )
        if not spec.is_child:
            user.birth_year, user.birth_month, user.birth_day = _birthday(ctx, spec)
        db.add(user)
        await db.flush()
        membership = Membership(
            group_id=ctx.home_id,
            user_id=user.id,
            role=Role.member if spec.is_child else Role.adult_member,
            relationship=HouseholdRelationship.child
            if spec.is_child
            else HouseholdRelationship.partner,
            permission_profile=PermissionProfile.child_restricted
            if spec.is_child
            else PermissionProfile.standard_partner,
            colour=spec.colour,
        )
        db.add(membership)
        await db.flush()
        if spec.is_child:
            year, month, day = _birthday(ctx, spec)
            profile = ChildProfile(
                membership_id=membership.id,
                group_id=ctx.home_id,
                age_band=spec.age_band,
                permissions={},
                birth_year=year,
                birth_month=month,
                birth_day=day,
                birthday_visible=True,
            )
            db.add(profile)
            await db.flush()
            for guardian_key in parker.ADULTS:
                guardian = ctx.memberships.get(guardian_key)
                if guardian is not None:
                    db.add(
                        GuardianAssignment(
                            child_profile_id=profile.id,
                            guardian_membership_id=guardian.id,
                            assigned_by_user_id=ctx.owner.id,
                        )
                    )
        else:
            ctx.personal_calendars[spec.key] = await ensure_personal_calendar(
                db, ctx.home_id, user.id
            )
        await _store_avatar(ctx, user, spec)
        ctx.users[spec.key] = user
        ctx.memberships[spec.key] = membership
    await db.flush()
    return len(ctx.users)


def _series_start(ctx: ShowcaseContext, spec: parker.EventSpec) -> date:
    anchor = ctx.day(-28)
    if spec.recurrence == RecurrencePattern.weekdays:
        return anchor + timedelta(days=(7 - anchor.weekday()) % 7)
    if spec.weekday is not None:
        return anchor + timedelta(days=(spec.weekday - anchor.weekday()) % 7)
    return ctx.day(spec.day)


async def add_event(ctx: ShowcaseContext, spec: parker.EventSpec) -> CalendarEvent:
    """Create one event exactly as routers.calendar.create_event stores it."""
    start_day = _series_start(ctx, spec)
    if spec.start is None:
        start_at = ctx.all_day_start(start_day)
        end_at = start_at + timedelta(days=spec.days)
    else:
        start_at = ctx.at(start_day, spec.start)
        end_at = ctx.at(start_day, spec.end or spec.start)
    people = tuple(key for key in spec.people if key in ctx.users)
    author = parker.JAMES if parker.EMMA not in people and parker.JAMES in people else parker.EMMA
    calendar = ctx.personal_calendars[parker.EMMA] if spec.personal else ctx.home_calendar
    event = CalendarEvent(
        group_id=ctx.home_id,
        calendar_id=calendar.id,
        label_id=ctx.labels[spec.label].id if spec.label in ctx.labels else None,
        title=spec.title,
        description=spec.description,
        start_at=start_at,
        end_at=end_at,
        is_all_day=spec.start is None,
        timezone=SHOWCASE_TIMEZONE_NAME,
        location_text=spec.location,
        reminder_minutes=spec.reminder_minutes,
        recurrence=spec.recurrence,
        recurrence_interval=1,
        created_by=ctx.users[author].id,
    )
    ctx.db.add(event)
    await ctx.db.flush()
    ctx.db.add_all(
        CalendarEventMember(group_id=ctx.home_id, event_id=event.id, user_id=user_id)
        for user_id in ctx.user_ids(people)
    )
    return event


async def ensure_labels(ctx: ShowcaseContext) -> None:
    for index, (name, colour) in enumerate(_LABELS):
        label = CalendarEventLabel(
            group_id=ctx.home_id,
            name=name,
            color=PALETTE_HEX[ColourToken(colour)],
            is_system=True,
            is_active=True,
            sort_order=(index + 1) * 10,
        )
        ctx.db.add(label)
        ctx.labels[name] = label
    await ctx.db.flush()


async def seed_baseline(ctx: ShowcaseContext) -> int:
    """A clean showcase Home: what a new paid Home has before anyone adds
    content — the event categories and the owner's Personal Calendar."""
    await ensure_labels(ctx)
    await ensure_personal_calendar(ctx.db, ctx.home_id, ctx.owner.id)
    return 0


async def seed_calendar(ctx: ShowcaseContext) -> int:
    await ensure_labels(ctx)
    for spec in parker.EVENTS:
        await add_event(ctx, spec)
    # Members' birthdays appear on the Calendar through the product's own
    # Calendar Highlights setting, not as duplicated event rows.
    settings_row = await ctx.db.scalar(
        select(HomeCalendarHighlightSettings).where(
            HomeCalendarHighlightSettings.group_id == ctx.home_id
        )
    )
    if settings_row is None:
        ctx.db.add(HomeCalendarHighlightSettings(group_id=ctx.home_id, birthdays_enabled=True))
    else:
        settings_row.birthdays_enabled = True
    await ctx.db.flush()
    return len(parker.EVENTS)


async def _nudge_categories(ctx: ShowcaseContext) -> None:
    for name in parker.NUDGE_CATEGORIES:
        category = TodoCategory(group_id=ctx.home_id, name=name, created_by=ctx.owner.id)
        ctx.db.add(category)
        ctx.nudge_categories[name] = category
    await ctx.db.flush()


def _completion_time(ctx: ShowcaseContext, offset: int) -> datetime:
    return ctx.at(ctx.day(offset), "08:15")


async def seed_nudges(ctx: ShowcaseContext) -> int:
    db = ctx.db
    await _nudge_categories(ctx)
    total = 0
    anchor = ctx.day(-28)
    for spec in parker.ROUTINES:
        week_anchor = (
            anchor + timedelta(days=(spec.weekday - anchor.weekday()) % 7)
            if spec.weekday is not None
            else anchor
        )
        routine = HouseholdRoutine(
            group_id=ctx.home_id,
            title=spec.title,
            description=spec.description,
            category_id=ctx.nudge_categories[spec.category].id,
            scope=RoutineScope.household,
            interval_weeks=1,
            repeat_unit=spec.repeat_unit,
            week_anchor_date=week_anchor,
            reminder_timing=spec.timing,
            pinned=spec.pinned,
            enabled=True,
            start_date=anchor,
            created_by=ctx.owner.id,
        )
        db.add(routine)
        await db.flush()
        db.add_all(
            HouseholdRoutineMember(routine_id=routine.id, user_id=user_id)
            for user_id in ctx.user_ids(spec.people)
        )
        for offset in spec.completed_days:
            db.add(
                HouseholdRoutineCompletion(
                    routine_id=routine.id,
                    occurrence_date=ctx.day(offset),
                    completed_by=ctx.owner.id,
                    completed_at=_completion_time(ctx, offset),
                )
            )
        total += 1
    for reminder_spec in parker.REMINDERS:
        first_due = min((reminder_spec.day, *reminder_spec.completed_days))
        reminder = Reminder(
            group_id=ctx.home_id,
            title=reminder_spec.title,
            description=reminder_spec.description,
            category_id=ctx.nudge_categories[reminder_spec.category].id,
            scope=RoutineScope.household,
            due_date=ctx.day(first_due),
            due_time=ctx.clock(reminder_spec.time),
            repeat=reminder_spec.repeat,
            cadence=reminder_spec.cadence,
            enabled=True,
            created_by=ctx.owner.id,
        )
        db.add(reminder)
        await db.flush()
        db.add_all(
            ReminderMember(reminder_id=reminder.id, user_id=user_id)
            for user_id in ctx.user_ids(reminder_spec.people)
        )
        for offset in reminder_spec.completed_days:
            db.add(
                ReminderCompletion(
                    reminder_id=reminder.id,
                    occurrence_date=ctx.day(offset),
                    completed_by=ctx.owner.id,
                    completed_at=_completion_time(ctx, offset),
                )
            )
        total += 1
    for todo_spec in parker.TODOS:
        personal_owner = ctx.users[todo_spec.personal_owner] if todo_spec.personal_owner else None
        todo = Todo(
            group_id=ctx.home_id,
            title=todo_spec.title,
            description=todo_spec.description,
            scope=RoutineScope.personal if personal_owner else RoutineScope.household,
            owner_user_id=personal_owner.id if personal_owner else None,
            category_id=ctx.nudge_categories[todo_spec.category].id,
            due_date=ctx.day(todo_spec.day),
            completed_at=ctx.at(ctx.day(todo_spec.completed_day), "18:30")
            if todo_spec.completed_day is not None
            else None,
            completed_by=ctx.users[todo_spec.completed_by or parker.EMMA].id
            if todo_spec.completed_day is not None
            else None,
            created_by=ctx.owner.id,
        )
        db.add(todo)
        await db.flush()
        if personal_owner is None:
            db.add_all(
                TodoMember(todo_id=todo.id, user_id=user_id)
                for user_id in ctx.user_ids(todo_spec.people)
            )
        total += 1
    await db.flush()
    return total


async def seed_meals(ctx: ShowcaseContext) -> int:
    db = ctx.db
    storage = get_meal_image_storage(ctx.settings)
    meals: dict[str, Meal] = {}
    for spec in parker.RECIPES:
        raw = images.approved_photo("meals", spec.slug) or images.render_meal_illustration(
            spec.slug, spec.art
        )
        key = meal_image_filename()
        await storage.save(key, process_attachment_upload(raw))
        ctx.written.meal_images.append(key)
        meal = Meal(
            group_id=ctx.home_id,
            name=spec.name,
            description=spec.description,
            image_key=key,
            meal_type=spec.meal_type,
            prep_minutes=spec.prep,
            cook_minutes=spec.cook,
            servings=spec.servings,
            instructions="\n\n".join(
                f"{number}. {step}" for number, step in enumerate(spec.steps, start=1)
            ),
            is_favourite=spec.favourite,
            tags=list(spec.tags),
            created_by=ctx.owner.id,
        )
        db.add(meal)
        await db.flush()
        db.add_all(
            MealIngredient(meal_id=meal.id, position=index, quantity=qty, unit=unit, text=text)
            for index, (qty, unit, text) in enumerate(spec.ingredients)
        )
        meals[spec.slug] = meal

    monday = ctx.reference_date - timedelta(days=ctx.reference_date.weekday())
    birthday_dinner = ctx.day(parker.BIRTHDAY_DINNER_DAY)
    plan: list[tuple[date, parker.MealPlanSpec]] = [
        (monday + timedelta(days=spec.day), spec)
        for spec in parker.MEAL_PLAN
        if not (
            spec.slot == MealSlot.dinner and monday + timedelta(days=spec.day) == birthday_dinner
        )
    ]
    plan.append(
        (
            birthday_dinner,
            parker.MealPlanSpec(
                0, MealSlot.dinner, quick_name=parker.BIRTHDAY_DINNER_QUICK_MEAL, time="18:00"
            ),
        )
    )
    for when, entry_spec in plan:
        entry = MealPlanEntry(
            group_id=ctx.home_id,
            meal_id=meals[entry_spec.recipe].id if entry_spec.recipe else None,
            quick_meal_name=entry_spec.quick_name,
            date=when,
            meal_slot=entry_spec.slot,
            time=ctx.clock(entry_spec.time),
            cook_member_id=ctx.users[entry_spec.cook].id if entry_spec.cook else None,
            makes_leftovers=entry_spec.makes_leftovers,
            created_by=ctx.owner.id,
        )
        db.add(entry)
        await db.flush()
        db.add_all(
            MealPlanParticipant(meal_plan_entry_id=entry.id, user_id=user_id)
            for user_id in ctx.user_ids(entry_spec.people)
        )
    await db.flush()
    ctx.add_count("meal_plan_entries", len(plan))
    return len(meals)


async def seed_lists(ctx: ShowcaseContext) -> int:
    db = ctx.db
    for spec in parker.LISTS:
        household_list = HouseholdList(
            group_id=ctx.home_id,
            name=spec.name,
            icon=spec.icon,
            scope=RoutineScope.household.value,
            created_by=ctx.owner.id,
        )
        db.add(household_list)
        await db.flush()
        for index, item in enumerate(spec.items):
            checker = ctx.users[item.checked_by] if item.checked_by else None
            db.add(
                HouseholdListItem(
                    list_id=household_list.id,
                    position=index,
                    text=item.text,
                    quantity=item.quantity,
                    note=item.note,
                    assigned_member_id=ctx.users[item.assignee].id if item.assignee else None,
                    is_checked=checker is not None,
                    completed_at=ctx.at(ctx.day(-1), "17:45") if checker else None,
                    completed_by=checker.id if checker else None,
                    created_by=ctx.owner.id,
                )
            )
        ctx.add_count("list_items", len(spec.items))
    await db.flush()
    return len(parker.LISTS)


def _next_christmas(ctx: ShowcaseContext) -> date:
    christmas = date(ctx.reference_date.year, 12, 25)
    return christmas if christmas >= ctx.reference_date else date(christmas.year + 1, 12, 25)


async def seed_wishlists(ctx: ShowcaseContext) -> int:
    db = ctx.db
    for spec in parker.WISHLISTS:
        occasion_date = (
            _next_christmas(ctx)
            if spec.occasion == WishlistOccasion.christmas
            else ctx.day(spec.occasion_day)
            if spec.occasion_day is not None
            else None
        )
        wishlist = Wishlist(
            home_id=ctx.home_id,
            owner_user_id=ctx.users[spec.owner].id,
            title=spec.title,
            occasion=spec.occasion,
            occasion_date=occasion_date,
            description=spec.description,
            created_by=ctx.owner.id,
            home_visible=True,
        )
        db.add(wishlist)
        await db.flush()
        for index, item_spec in enumerate(spec.items):
            item = WishlistItem(
                wishlist_id=wishlist.id,
                name=item_spec.name,
                price=item_spec.price,
                currency="GBP" if item_spec.price is not None else None,
                note=item_spec.note,
                quantity=item_spec.quantity,
                sort_order=index,
            )
            db.add(item)
            await db.flush()
            if item_spec.reserved_by:
                reserver = ctx.users[item_spec.reserved_by]
                db.add(
                    WishlistItemReservation(
                        wishlist_item_id=item.id,
                        status=item_spec.reservation,
                        actor_type=WishlistReservationActorType.member,
                        actor_user_id=reserver.id,
                        buyer_display_name=reserver.display_name.split(" ")[0],
                    )
                )
        ctx.add_count("wishlist_items", len(spec.items))
    await db.flush()
    return len(parker.WISHLISTS)


async def seed_personal_settings(ctx: ShowcaseContext) -> int:
    """Emma's own Calendar and notification preferences — in-app and push
    only. Email stays at its opt-in default (off), so the showcase never
    emails anyone, and member accounts have no devices or credentials."""
    prefs = await ctx.db.scalar(
        select(NotificationPreferences).where(NotificationPreferences.user_id == ctx.owner.id)
    )
    if prefs is None:
        prefs = NotificationPreferences(user_id=ctx.owner.id)
        ctx.db.add(prefs)
    prefs.email_enabled = False
    prefs.default_event_reminder_enabled = True
    prefs.default_event_reminder_minutes = 30
    prefs.all_day_reminder_enabled = True
    prefs.all_day_reminder_time = ctx.clock("08:00")
    prefs.default_calendar_id = ctx.home_calendar.id
    prefs.week_starts_on = "monday"
    prefs.daily_nudge_summary_enabled = True
    prefs.daily_nudge_summary_time = ctx.clock("07:30")
    await ctx.db.flush()
    return 1
