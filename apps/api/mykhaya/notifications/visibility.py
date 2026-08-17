"""The single reusable "can this user see this calendar content" check.

Mirrors the inline visibility logic already proven in
apps/api/mykhaya/routers/calendar.py (list_events, event_detail, home_summary) exactly —
extracted here so a briefing/reminder generator replicates it rather than reinventing a
second, potentially-diverging version. See docs/security/threat-model.md on cross-member
data leakage.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.models import CalendarEvent, CalendarEventMember, HomeCalendar, Membership


async def active_membership(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    membership: Membership | None = await db.scalar(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
    )
    return membership


async def can_view_event(db: AsyncSession, event: CalendarEvent, user_id: uuid.UUID) -> bool:
    membership = await active_membership(db, event.group_id, user_id)
    if membership is None:
        return False
    capabilities = await capabilities_for(db, membership)
    if Capability.calendar_view not in capabilities:
        return False
    # A hard privacy boundary, checked before (and independent of)
    # calendar_view_all — a Home admin/partner's blanket visibility must
    # never reach into another member's Personal Calendar. See
    # routers.calendar._personal_calendar_visibility_filter, the same rule
    # applied at the SQL-query level for list/detail endpoints.
    calendar = await db.get(HomeCalendar, event.calendar_id)
    if (
        calendar is not None
        and calendar.owner_user_id is not None
        and calendar.owner_user_id != user_id
    ):
        return False
    if Capability.calendar_view_all in capabilities:
        return True
    if event.created_by == user_id:
        return True
    assigned = await db.scalar(
        select(CalendarEventMember.id).where(
            CalendarEventMember.event_id == event.id,
            CalendarEventMember.user_id == user_id,
        )
    )
    return assigned is not None


async def viewer_ids_for_event(db: AsyncSession, event: CalendarEvent) -> set[uuid.UUID]:
    """Members explicitly attached to the event — the natural reminder recipient set.
    (Not the same as "everyone who *could* view it" via calendar_view_all — a household
    admin with blanket visibility should not get reminded about an event they aren't
    actually part of.)"""
    rows = (
        await db.scalars(
            select(CalendarEventMember.user_id).where(CalendarEventMember.event_id == event.id)
        )
    ).all()
    return set(rows)
