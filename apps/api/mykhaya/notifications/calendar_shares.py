"""Notifies active external `CalendarShare` recipients about activity on their shared
calendar — the calendar-share analogue of routers.calendar's per-event-member
notifications (`_notify_members_added` etc.). A share recipient is never a
`CalendarEventMember` (they don't belong to the Home), so those functions never reach
them; this is the one additional recipient-resolution path that extends `notify()` to
cover them. Reused by both `routers.calendar` (Home-side event mutations) and
`routers.calendar_sharing` (an external "Can add & edit" recipient's own mutations on
their shared calendar), so a shared calendar's watchers are notified the same way no
matter which side created/changed the event.
"""

from __future__ import annotations

import uuid
from datetime import UTC, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import CalendarEvent, CalendarShare, CalendarShareStatus
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify

_TITLES = {
    "created": "New event",
    "updated": "Event updated",
    "cancelled": "Event cancelled",
}
_NOTIFICATION_TYPES = {
    "created": "event_invitation",
    "updated": "event_updated",
    "cancelled": "event_cancelled",
}


async def active_share_recipients(db: AsyncSession, calendar_id: uuid.UUID) -> list[CalendarShare]:
    rows = (
        await db.scalars(
            select(CalendarShare).where(
                CalendarShare.calendar_id == calendar_id,
                CalendarShare.status == CalendarShareStatus.accepted,
                CalendarShare.revoked_at.is_(None),
            )
        )
    ).all()
    return list(rows)


def _format_event_when(event: CalendarEvent) -> str:
    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    local_start = event.start_at.astimezone(tz)
    if event.is_all_day:
        return local_start.strftime("%A, %d %B")
    return local_start.strftime("%A, %d %B at %H:%M")


async def notify_calendar_share_recipients(
    db: AsyncSession,
    settings: Settings,
    event: CalendarEvent,
    *,
    actor_user_id: uuid.UUID,
    actor_name: str,
    action: str,
    version_marker: int | None = None,
) -> None:
    """`action` is one of "created" / "updated" / "cancelled". Honors each
    recipient's own `notification_preference` ("off" suppresses everything,
    "important" suppresses only the low-signal "created" notice) — on top of
    (not instead of) their normal event_invitation/event_updated/
    event_cancelled category toggles, which `notify()` still applies."""
    when = _format_event_when(event)
    if action == "created":
        body = f"{actor_name} added {event.title}. {when}."
    elif action == "updated":
        body = f"{actor_name} updated {event.title}. {when}."
    else:
        body = f"{actor_name} cancelled {event.title}."
    marker = f":{version_marker}" if version_marker is not None else ""

    for share in await active_share_recipients(db, event.calendar_id):
        if share.recipient_user_id is None or share.recipient_user_id == actor_user_id:
            continue
        if share.notification_preference == "off":
            continue
        if share.notification_preference == "important" and action == "created":
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=share.recipient_user_id,
            notification_type=_NOTIFICATION_TYPES[action],
            title=_TITLES[action],
            body=body,
            idempotency_key=f"calendar_share_event_{action}:{event.id}:{share.id}{marker}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )
