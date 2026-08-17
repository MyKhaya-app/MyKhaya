"""Personal Calendar provisioning: one private, per-member HomeCalendar.

A shared helper (not routers.calendar itself) so it can be called from every
membership-creation path (routers.groups, routers.invitations) without those
routers depending on the calendar router module — same shape as
mykhaya.member_colours.assign_member_colour.

See routers.calendar for how `HomeCalendar.owner_user_id` is enforced as an
actual privacy boundary (never entitlement-gated, never visible/writable to
anyone but its owner, regardless of calendar_view_all) and
notifications.visibility.can_view_event for the read-side enforcement.

Managed child accounts are deliberately NOT provisioned a Personal Calendar
here — there is no established product rule yet for parent visibility into a
child's calendar/events, so this does not invent one. See the task's final
report for that open product decision.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import HomeCalendar


async def ensure_personal_calendar(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> HomeCalendar:
    """Idempotently returns this member's Personal Calendar within this
    Home, creating it if missing. Safe to call on every membership-creation
    path and as a defensive fallback elsewhere (e.g. list_calendars) — the
    (group_id, owner_user_id) UniqueConstraint on home_calendars makes a
    duplicate impossible even under concurrent calls; a race is resolved via
    a SAVEPOINT (begin_nested) so a conflict only unwinds this insert, never
    other work already pending on the caller's session/transaction."""
    existing: HomeCalendar | None = await db.scalar(
        select(HomeCalendar).where(
            HomeCalendar.group_id == group_id,
            HomeCalendar.owner_user_id == user_id,
        )
    )
    if existing is not None:
        return existing

    calendar = HomeCalendar(
        group_id=group_id,
        owner_user_id=user_id,
        name="Personal calendar",
        is_primary=False,
    )
    try:
        async with db.begin_nested():
            db.add(calendar)
            await db.flush()
    except Exception:
        # Lost the race to a concurrent call — the row now exists; fetch it.
        recovered: HomeCalendar | None = await db.scalar(
            select(HomeCalendar).where(
                HomeCalendar.group_id == group_id,
                HomeCalendar.owner_user_id == user_id,
            )
        )
        if recovered is None:
            raise
        return recovered
    return calendar
