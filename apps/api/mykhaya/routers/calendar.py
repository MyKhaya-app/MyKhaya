from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.calendar_occurrences import (
    MAX_RANGE_DAYS,
    expand_occurrences,
    recurrence_candidate_filter,
)
from mykhaya.colour_palette import ColourToken
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, capabilities_for, require_capability
from mykhaya.models import (
    CalendarEvent,
    CalendarEventActivity,
    CalendarEventLabel,
    CalendarEventMember,
    FeatureKey,
    Group,
    HomeCalendar,
    Invitation,
    Membership,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.schemas import (
    EventActivityResponse,
    EventCreate,
    EventDetailResponse,
    EventLabelCreate,
    EventLabelResponse,
    EventLabelUpdate,
    EventListResponse,
    EventOccurrence,
    EventUpdate,
    HomeSummaryResponse,
)


async def require_calendar_feature(
    home_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_feature(db, FeatureKey.calendar, home_id)


router = APIRouter(
    prefix="/homes",
    tags=["calendar"],
    dependencies=[Depends(require_calendar_feature)],
)
SYSTEM_LABELS = [
    ("Family", ColourToken.teal),
    ("School", ColourToken.purple),
    ("Work", ColourToken.emerald),
    ("Appointment", ColourToken.orange),
    ("Birthday", ColourToken.rose),
    ("Activity", ColourToken.blue),
    ("Other", ColourToken.slate),
]


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid timezone") from exc


async def _ensure_home_calendar(db: AsyncSession, group_id: uuid.UUID) -> HomeCalendar:
    calendar = await db.scalar(
        select(HomeCalendar).where(
            HomeCalendar.group_id == group_id,
            HomeCalendar.is_primary.is_(True),
        )
    )
    if calendar is not None:
        return calendar

    calendar = HomeCalendar(group_id=group_id, name="Home Calendar")
    db.add(calendar)
    await db.flush()

    for index, (name, color) in enumerate(SYSTEM_LABELS):
        db.add(
            CalendarEventLabel(
                group_id=group_id,
                name=name,
                color=color,
                is_system=True,
                sort_order=(index + 1) * 10,
            )
        )
    await db.flush()
    return calendar


async def _label_map(db: AsyncSession, group_id: uuid.UUID) -> dict[uuid.UUID, CalendarEventLabel]:
    labels = (
        await db.scalars(
            select(CalendarEventLabel)
            .where(CalendarEventLabel.group_id == group_id, CalendarEventLabel.is_active.is_(True))
            .order_by(CalendarEventLabel.sort_order, CalendarEventLabel.name)
            .limit(100)
        )
    ).all()
    return {label.id: label for label in labels}


async def _event_members_map(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not event_ids:
        return {}
    rows = (
        await db.scalars(
            select(CalendarEventMember).where(CalendarEventMember.event_id.in_(event_ids))
        )
    ).all()
    data: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in rows:
        data.setdefault(row.event_id, []).append(row.user_id)
    return data


def _to_label_response(label: CalendarEventLabel | None) -> EventLabelResponse | None:
    if label is None:
        return None
    return EventLabelResponse(
        id=label.id,
        name=label.name,
        color=label.color,
        is_active=label.is_active,
        sort_order=label.sort_order,
    )


def _occurrence(
    event: CalendarEvent,
    start_at: datetime,
    end_at: datetime,
    label: CalendarEventLabel | None,
    member_ids: list[uuid.UUID],
) -> EventOccurrence:
    return EventOccurrence(
        occurrence_id=f"{event.id}:{start_at.isoformat()}",
        event_id=event.id,
        title=event.title,
        start_at=start_at,
        end_at=end_at,
        is_all_day=event.is_all_day,
        timezone=event.timezone,
        description=event.description,
        location_text=event.location_text,
        label=_to_label_response(label),
        member_ids=member_ids,
        recurrence=event.recurrence,
        reminder_minutes=event.reminder_minutes,
        created_by=event.created_by,
        updated_at=event.updated_at,
    )


async def _record_activity(
    db: AsyncSession,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    action: str,
    summary: str,
) -> None:
    db.add(
        CalendarEventActivity(
            group_id=event.group_id,
            event_id=event.id,
            actor_user_id=actor_id,
            action=action,
            summary=summary,
        )
    )


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


async def _notify_members_added(
    db: AsyncSession,
    settings: Settings,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    actor_name: str,
    recipient_ids: set[uuid.UUID],
    version_marker: int,
) -> None:
    """One "added to an event" notification per newly-assigned member, never
    the actor themselves. `version_marker` (CalendarEvent.version, already
    incremented for this mutation before this is called) makes the
    idempotency key distinct per actual mutation — a retried/duplicate
    request that re-applies the *same* version never reaches here twice
    anyway, since update_event's optimistic-concurrency check
    (expected_updated_at) rejects it before any of this runs; this is
    belt-and-braces against NotificationDelivery's own unique constraint,
    consistent with mykhaya.notifications.reminders' key construction."""
    when = _format_event_when(event)
    for recipient_id in recipient_ids:
        if recipient_id == actor_id:
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_invitation",
            title="Added to an event",
            body=f"{actor_name} added you to {event.title}. {when}.",
            idempotency_key=f"calendar_event_member_added:{event.id}:{recipient_id}:{version_marker}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )


async def _notify_members_removed(
    db: AsyncSession,
    settings: Settings,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    actor_name: str,
    recipient_ids: set[uuid.UUID],
    version_marker: int,
) -> None:
    for recipient_id in recipient_ids:
        if recipient_id == actor_id:
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_updated",
            title="Removed from an event",
            body=f"{actor_name} removed you from {event.title}.",
            idempotency_key=f"calendar_event_member_removed:{event.id}:{recipient_id}:{version_marker}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )


async def _notify_members_event_updated(
    db: AsyncSession,
    settings: Settings,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    actor_name: str,
    recipient_ids: set[uuid.UUID],
    version_marker: int,
) -> None:
    when = _format_event_when(event)
    for recipient_id in recipient_ids:
        if recipient_id == actor_id:
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_updated",
            title="Event updated",
            body=f"{actor_name} updated {event.title}. {when}.",
            idempotency_key=f"calendar_event_updated:{event.id}:{recipient_id}:{version_marker}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )


async def _notify_members_event_cancelled(
    db: AsyncSession,
    settings: Settings,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    actor_name: str,
    recipient_ids: set[uuid.UUID],
) -> None:
    for recipient_id in recipient_ids:
        if recipient_id == actor_id:
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_cancelled",
            title="Event cancelled",
            body=f"{actor_name} cancelled {event.title}.",
            idempotency_key=f"calendar_event_cancelled:{event.id}:{recipient_id}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )


@router.get("/{home_id}/event-labels", response_model=list[EventLabelResponse])
async def labels(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[EventLabelResponse]:
    await require_capability(home_id, Capability.calendar_view, auth, db)
    await _ensure_home_calendar(db, home_id)
    rows = (
        await db.scalars(
            select(CalendarEventLabel)
            .where(CalendarEventLabel.group_id == home_id, CalendarEventLabel.is_active.is_(True))
            .order_by(CalendarEventLabel.sort_order, CalendarEventLabel.name)
            .limit(100)
        )
    ).all()
    return [
        EventLabelResponse(
            id=row.id,
            name=row.name,
            color=row.color,
            is_active=row.is_active,
            sort_order=row.sort_order,
        )
        for row in rows
    ]


async def _label_name_taken(
    db: AsyncSession, home_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    query = select(CalendarEventLabel.id).where(
        CalendarEventLabel.group_id == home_id, CalendarEventLabel.name == name
    )
    if exclude_id is not None:
        query = query.where(CalendarEventLabel.id != exclude_id)
    return await db.scalar(query) is not None


@router.post("/{home_id}/event-labels", response_model=EventLabelResponse, status_code=201)
async def create_label(
    home_id: uuid.UUID,
    body: EventLabelCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventLabelResponse:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    if await _label_name_taken(db, home_id, body.name):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A calendar or category with that name already exists."
        )
    row = CalendarEventLabel(
        group_id=home_id,
        name=body.name,
        color=body.color,
        is_system=False,
    )
    db.add(row)
    await db.flush()
    audit(db, request, "calendar.label.created", auth.user.id, home_id, "label", row.id)
    await db.commit()
    return EventLabelResponse(
        id=row.id,
        name=row.name,
        color=row.color,
        is_active=row.is_active,
        sort_order=row.sort_order,
    )


@router.patch("/{home_id}/event-labels/{label_id}", response_model=EventLabelResponse)
async def update_label(
    home_id: uuid.UUID,
    label_id: uuid.UUID,
    body: EventLabelUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventLabelResponse:
    # calendar_edit_all, not calendar_edit_own: a calendar/category is shared
    # household structure, not any one person's content — the same capability
    # already gates creating one.
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    label = await db.get(CalendarEventLabel, label_id)
    if label is None or label.group_id != home_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That calendar or category could not be found."
        )
    if body.name is not None and body.name != label.name:
        if await _label_name_taken(db, home_id, body.name, exclude_id=label.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A calendar or category with that name already exists."
            )
        label.name = body.name
    if body.color is not None:
        label.color = body.color
    if body.is_active is not None:
        label.is_active = body.is_active
    await db.flush()
    audit(db, request, "calendar.label.updated", auth.user.id, home_id, "label", label.id)
    await db.commit()
    return EventLabelResponse(
        id=label.id,
        name=label.name,
        color=label.color,
        is_active=label.is_active,
        sort_order=label.sort_order,
    )


@router.get("/{home_id}/events", response_model=EventListResponse)
async def list_events(
    home_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=200, ge=1, le=400),
    q: str | None = Query(default=None, max_length=80),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventListResponse:
    membership = await require_capability(home_id, Capability.calendar_view, auth, db)
    capabilities = await capabilities_for(db, membership)
    if end_at <= start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid date range")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Date range is too large")

    filters = [
        CalendarEvent.group_id == home_id,
        CalendarEvent.deleted_at.is_(None),
        recurrence_candidate_filter(start_at, end_at),
    ]
    if Capability.calendar_view_all not in capabilities:
        filters.append(
            or_(
                CalendarEvent.created_by == auth.user.id,
                CalendarEvent.id.in_(
                    select(CalendarEventMember.event_id).where(
                        CalendarEventMember.user_id == auth.user.id
                    )
                ),
            )
        )
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                CalendarEvent.title.ilike(term),
                CalendarEvent.description.ilike(term),
                CalendarEvent.location_text.ilike(term),
            )
        )

    rows = (
        await db.scalars(
            select(CalendarEvent)
            .where(and_(*filters))
            .order_by(CalendarEvent.start_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )
    ).all()
    has_more = len(rows) > page_size
    events = rows[:page_size]
    label_by_id = await _label_map(db, home_id)
    members_by_event = await _event_members_map(db, [event.id for event in events])

    items: list[EventOccurrence] = []
    for event in events:
        label = label_by_id.get(event.label_id) if event.label_id else None
        member_ids = members_by_event.get(event.id, [])
        for occurrence_start, occurrence_end in expand_occurrences(event, start_at, end_at):
            items.append(_occurrence(event, occurrence_start, occurrence_end, label, member_ids))

    items.sort(key=lambda item: item.start_at)
    return EventListResponse(items=items, next_page=page + 1 if has_more else None)


@router.post("/{home_id}/events", response_model=EventOccurrence, status_code=201)
async def create_event(
    home_id: uuid.UUID,
    body: EventCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EventOccurrence:
    await require_capability(home_id, Capability.calendar_create, auth, db)
    _validate_timezone(body.timezone)
    if body.end_at <= body.start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be after start")

    calendar_row = await _ensure_home_calendar(db, home_id)
    if body.label_id is not None:
        label = await db.scalar(
            select(CalendarEventLabel).where(
                CalendarEventLabel.id == body.label_id,
                CalendarEventLabel.group_id == home_id,
                CalendarEventLabel.is_active.is_(True),
            )
        )
        if label is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That label could not be found")

    requested_members = sorted(set(body.member_ids + [auth.user.id]))
    if requested_members:
        rows = (
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == home_id,
                    Membership.removed_at.is_(None),
                    Membership.user_id.in_(requested_members),
                )
            )
        ).all()
        if set(rows) != set(requested_members):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A selected member is invalid",
            )

    event = CalendarEvent(
        group_id=home_id,
        calendar_id=calendar_row.id,
        label_id=body.label_id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        start_at=body.start_at,
        end_at=body.end_at,
        is_all_day=body.is_all_day,
        timezone=body.timezone,
        location_text=body.location_text,
        reminder_minutes=body.reminder_minutes,
        recurrence=body.recurrence,
        recurrence_interval=body.recurrence_interval,
        recurrence_until=body.recurrence_until,
        recurrence_count=body.recurrence_count,
        created_by=auth.user.id,
        last_edited_by=auth.user.id,
    )
    db.add(event)
    await db.flush()

    for user_id in requested_members:
        db.add(CalendarEventMember(group_id=home_id, event_id=event.id, user_id=user_id))

    await _record_activity(db, event, auth.user.id, "event.created", "created this event")
    audit(db, request, "calendar.event.created", auth.user.id, home_id, "event", event.id)
    await _notify_members_added(
        db,
        settings,
        event,
        auth.user.id,
        auth.user.display_name,
        set(requested_members),
        event.version,
    )
    await db.commit()
    await db.refresh(event)

    label = await db.get(CalendarEventLabel, event.label_id) if event.label_id else None
    return _occurrence(event, event.start_at, event.end_at, label, requested_members)


@router.get("/{home_id}/events/{event_id}", response_model=EventDetailResponse)
async def event_detail(
    home_id: uuid.UUID,
    event_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventDetailResponse:
    membership = await require_capability(home_id, Capability.calendar_view, auth, db)
    capabilities = await capabilities_for(db, membership)
    event = await db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.group_id == home_id,
            CalendarEvent.deleted_at.is_(None),
        )
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    if Capability.calendar_view_all not in capabilities:
        assigned = await db.scalar(
            select(CalendarEventMember.id).where(
                CalendarEventMember.event_id == event.id,
                CalendarEventMember.user_id == auth.user.id,
            )
        )
        if event.created_by != auth.user.id and assigned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")

    label = await db.get(CalendarEventLabel, event.label_id) if event.label_id else None
    member_ids = [
        row.user_id
        for row in (
            await db.scalars(
                select(CalendarEventMember).where(CalendarEventMember.event_id == event.id)
            )
        ).all()
    ]
    activity_rows = (
        await db.scalars(
            select(CalendarEventActivity)
            .where(CalendarEventActivity.event_id == event.id)
            .order_by(CalendarEventActivity.created_at.desc())
            .limit(50)
        )
    ).all()
    return EventDetailResponse(
        event=_occurrence(event, event.start_at, event.end_at, label, member_ids),
        activity=[
            EventActivityResponse(
                id=row.id,
                action=row.action,
                summary=row.summary,
                actor_user_id=row.actor_user_id,
                created_at=row.created_at,
            )
            for row in activity_rows
        ],
    )


@router.patch("/{home_id}/events/{event_id}", response_model=EventOccurrence)
async def update_event(
    home_id: uuid.UUID,
    event_id: uuid.UUID,
    body: EventUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EventOccurrence:
    membership = await require_capability(home_id, Capability.calendar_edit_own, auth, db)
    _validate_timezone(body.timezone)
    if body.end_at <= body.start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be after start")

    event = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.group_id == home_id,
            CalendarEvent.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    if event.created_by != membership.user_id:
        await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    if event.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This event changed. Reload and try again.")

    requested_members = sorted(set(body.member_ids + [event.created_by]))
    if requested_members:
        rows = (
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == home_id,
                    Membership.removed_at.is_(None),
                    Membership.user_id.in_(requested_members),
                )
            )
        ).all()
        if set(rows) != set(requested_members):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A selected member is invalid",
            )

    previous_member_ids = {
        row.user_id
        for row in (
            await db.scalars(
                select(CalendarEventMember)
                .where(CalendarEventMember.event_id == event.id)
                .with_for_update()
            )
        ).all()
    }
    material_change = (
        event.title.strip() != body.title.strip()
        or event.start_at != body.start_at
        or event.end_at != body.end_at
        or event.is_all_day != body.is_all_day
        or event.location_text != body.location_text
    )

    event.title = " ".join(body.title.strip().split())
    event.description = body.description
    event.start_at = body.start_at
    event.end_at = body.end_at
    event.is_all_day = body.is_all_day
    event.timezone = body.timezone
    event.location_text = body.location_text
    event.label_id = body.label_id
    event.reminder_minutes = body.reminder_minutes
    event.recurrence = body.recurrence
    event.recurrence_interval = body.recurrence_interval
    event.recurrence_until = body.recurrence_until
    event.recurrence_count = body.recurrence_count
    event.last_edited_by = auth.user.id
    event.version += 1

    await db.execute(delete(CalendarEventMember).where(CalendarEventMember.event_id == event.id))
    for user_id in requested_members:
        db.add(CalendarEventMember(group_id=home_id, event_id=event.id, user_id=user_id))

    await _record_activity(db, event, auth.user.id, "event.updated", "updated this event")
    audit(db, request, "calendar.event.updated", auth.user.id, home_id, "event", event.id)

    new_member_ids = set(requested_members) - previous_member_ids
    removed_member_ids = previous_member_ids - set(requested_members)
    unchanged_member_ids = set(requested_members) & previous_member_ids
    await _notify_members_added(
        db, settings, event, auth.user.id, auth.user.display_name, new_member_ids, event.version
    )
    await _notify_members_removed(
        db,
        settings,
        event,
        auth.user.id,
        auth.user.display_name,
        removed_member_ids,
        event.version,
    )
    if material_change:
        await _notify_members_event_updated(
            db,
            settings,
            event,
            auth.user.id,
            auth.user.display_name,
            unchanged_member_ids,
            event.version,
        )

    await db.commit()
    # Async SQLAlchemy expires every attribute on commit; touching one
    # without an explicit refresh first (updated_at, server-computed via
    # onupdate=func.now()) can fail with MissingGreenlet rather than
    # silently lazy-loading the way sync SQLAlchemy would. Explicit refresh
    # is the correct async-safe way to read it back.
    await db.refresh(event)

    label = await db.get(CalendarEventLabel, event.label_id) if event.label_id else None
    return _occurrence(event, event.start_at, event.end_at, label, requested_members)


@router.delete("/{home_id}/events/{event_id}", status_code=204)
async def delete_event(
    home_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    await require_capability(home_id, Capability.calendar_delete, auth, db)
    event = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.group_id == home_id,
            CalendarEvent.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    member_ids = {
        row.user_id
        for row in (
            await db.scalars(
                select(CalendarEventMember).where(CalendarEventMember.event_id == event.id)
            )
        ).all()
    }
    event.deleted_at = datetime.now(UTC)
    event.deleted_by = auth.user.id
    event.last_edited_by = auth.user.id
    await _record_activity(db, event, auth.user.id, "event.deleted", "deleted this event")
    audit(db, request, "calendar.event.deleted", auth.user.id, home_id, "event", event.id)
    await _notify_members_event_cancelled(
        db, settings, event, auth.user.id, auth.user.display_name, member_ids
    )
    await db.commit()


@router.get("/{home_id}/events/{event_id}/activity", response_model=list[EventActivityResponse])
async def event_activity(
    home_id: uuid.UUID,
    event_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[EventActivityResponse]:
    membership = await require_capability(home_id, Capability.calendar_view, auth, db)
    capabilities = await capabilities_for(db, membership)
    if Capability.calendar_view_all not in capabilities:
        visible = await db.scalar(
            select(CalendarEvent.id).where(
                CalendarEvent.id == event_id,
                CalendarEvent.group_id == home_id,
                CalendarEvent.deleted_at.is_(None),
                or_(
                    CalendarEvent.created_by == auth.user.id,
                    CalendarEvent.id.in_(
                        select(CalendarEventMember.event_id).where(
                            CalendarEventMember.user_id == auth.user.id
                        )
                    ),
                ),
            )
        )
        if visible is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    rows = (
        await db.scalars(
            select(CalendarEventActivity)
            .where(
                CalendarEventActivity.group_id == home_id,
                CalendarEventActivity.event_id == event_id,
            )
            .order_by(CalendarEventActivity.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        EventActivityResponse(
            id=row.id,
            action=row.action,
            summary=row.summary,
            actor_user_id=row.actor_user_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{home_id}/summary", response_model=HomeSummaryResponse)
async def home_summary(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> HomeSummaryResponse:
    membership = await require_capability(home_id, Capability.calendar_view, auth, db)
    capabilities = await capabilities_for(db, membership)
    now = datetime.now(UTC)
    day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    labels = await _label_map(db, home_id)
    visibility_filters = []
    if Capability.calendar_view_all not in capabilities:
        visibility_filters.append(
            or_(
                CalendarEvent.created_by == auth.user.id,
                CalendarEvent.id.in_(
                    select(CalendarEventMember.event_id).where(
                        CalendarEventMember.user_id == auth.user.id
                    )
                ),
            )
        )
    today_rows = (
        await db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.group_id == home_id,
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.start_at < day_end,
                CalendarEvent.end_at > day_start,
                *visibility_filters,
            )
            .order_by(CalendarEvent.start_at)
            .limit(20)
        )
    ).all()
    member_map = await _event_members_map(db, [event.id for event in today_rows])
    today_events = [
        _occurrence(
            event,
            event.start_at,
            event.end_at,
            labels.get(event.label_id) if event.label_id else None,
            member_map.get(event.id, []),
        )
        for event in today_rows
    ]

    next_event_row = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.group_id == home_id,
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.end_at >= now,
            *visibility_filters,
        )
        .order_by(CalendarEvent.start_at)
        .limit(1)
    )
    next_event = None
    if next_event_row is not None:
        next_event = _occurrence(
            next_event_row,
            next_event_row.start_at,
            next_event_row.end_at,
            labels.get(next_event_row.label_id) if next_event_row.label_id else None,
            member_map.get(next_event_row.id, []),
        )

    pending_count = None
    if Capability.members_invite in await capabilities_for(db, membership):
        pending_count = await db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.group_id == home_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
        )
    member_count = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == home_id, Membership.removed_at.is_(None))
    )
    home = await db.get(Group, home_id)
    assert home is not None
    return HomeSummaryResponse(
        home_name=home.name,
        member_count=member_count or 0,
        pending_invitations=pending_count,
        today_events=today_events,
        next_event=next_event,
    )
