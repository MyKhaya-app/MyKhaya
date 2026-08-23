"""The single reusable "can this user see this calendar content" check.

Mirrors the inline visibility logic already proven in
apps/api/mykhaya/routers/calendar.py (list_events, event_detail, home_summary) exactly —
extracted here so a briefing/reminder generator replicates it rather than reinventing a
second, potentially-diverging version. See docs/security/threat-model.md on cross-member
data leakage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.models import (
    CalendarEvent,
    CalendarEventMember,
    CalendarShare,
    CalendarShareStatus,
    HomeCalendar,
    Membership,
)


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


async def active_calendar_share(
    db: AsyncSession, calendar_id: uuid.UUID, user_id: uuid.UUID
) -> CalendarShare | None:
    """The one place external-sharing access is decided for calendar/event
    visibility — reused by can_view_event/viewer_ids_for_event below so
    reminders and the daily briefing inherit it automatically, and by
    routers.calendar_sharing's own write-permission check. Never trust a
    cached/stale result: revoked_at, status, and expires_at are re-checked on
    every call, so a revocation takes effect on the very next read."""
    share: CalendarShare | None = await db.scalar(
        select(CalendarShare).where(
            CalendarShare.calendar_id == calendar_id,
            CalendarShare.recipient_user_id == user_id,
            CalendarShare.status == CalendarShareStatus.accepted,
            CalendarShare.revoked_at.is_(None),
            CalendarShare.expires_at > datetime.now(UTC),
        )
    )
    return share


def event_matches_share(event: CalendarEvent, share: CalendarShare) -> bool:
    """The category-scoped sharing filter (see CalendarShare.category_ids'
    docstring): `None` shares the entire calendar, unchanged from before this
    filter existed. When set, an event only matches if it carries one of the
    selected categories — *except* an event the share's own recipient
    created through this exact share (see routers.calendar_sharing's
    share-scoped create endpoint, which never assigns a category — a
    "manage" recipient must always see their own work, category filter or
    not). This is the one place that exception is applied; every other
    check in this module calls into it rather than re-deriving the rule."""
    if share.category_ids is None:
        return True
    if event.created_by == share.recipient_user_id:
        return True
    return event.label_id is not None and str(event.label_id) in share.category_ids


async def can_view_event(db: AsyncSession, event: CalendarEvent, user_id: uuid.UUID) -> bool:
    membership = await active_membership(db, event.group_id, user_id)
    if membership is None:
        # Not a Home member — the only other legitimate way to see this
        # event is an active external CalendarShare on its specific
        # calendar (and, if that share is category-scoped, this event must
        # carry one of the selected categories). This never reaches into
        # any *other* calendar in the Home, and is fully independent of
        # Membership/capabilities.
        share = await active_calendar_share(db, event.calendar_id, user_id)
        return share is not None and event_matches_share(event, share)
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
    """Members explicitly attached to the event, plus any active external
    CalendarShare recipient for its calendar whose notification_preference
    isn't "off" — the natural reminder recipient set. (Not the same as
    "everyone who *could* view it" via calendar_view_all — a household admin
    with blanket visibility should not get reminded about an event they
    aren't actually part of; an external share recipient is different: the
    whole point of sharing a calendar is to see everything on it.)"""
    rows = (
        await db.scalars(
            select(CalendarEventMember.user_id).where(CalendarEventMember.event_id == event.id)
        )
    ).all()
    viewer_ids = set(rows)
    for share in (
        await db.scalars(
            select(CalendarShare).where(
                CalendarShare.calendar_id == event.calendar_id,
                CalendarShare.status == CalendarShareStatus.accepted,
                CalendarShare.revoked_at.is_(None),
                CalendarShare.expires_at > datetime.now(UTC),
            )
        )
    ).all():
        if (
            share.recipient_user_id is not None
            and share.notification_preference != "off"
            and event_matches_share(event, share)
        ):
            viewer_ids.add(share.recipient_user_id)
    return viewer_ids
