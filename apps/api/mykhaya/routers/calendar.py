from __future__ import annotations

import calendar as month_calendar
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
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
    RecurrencePattern,
)
from mykhaya.schemas import (
    EventActivityResponse,
    EventCreate,
    EventDetailResponse,
    EventLabelCreate,
    EventLabelResponse,
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
MAX_RANGE_DAYS = 93
SYSTEM_LABELS = [
    ("Family", "#456B76"),
    ("School", "#7A5C99"),
    ("Work", "#476A3A"),
    ("Appointment", "#A05A2C"),
    ("Birthday", "#A03F6A"),
    ("Activity", "#336D9A"),
    ("Other", "#666666"),
]


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid timezone") from exc


def _month_increment(value: datetime, step: int) -> datetime:
    target_month = value.month + step
    year = value.year + (target_month - 1) // 12
    month = ((target_month - 1) % 12) + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _expand_occurrences(
    event: CalendarEvent, range_start: datetime, range_end: datetime
) -> list[tuple[datetime, datetime]]:
    occurrences: list[tuple[datetime, datetime]] = []
    duration = event.end_at - event.start_at
    limit_end = min(range_end, range_start + timedelta(days=MAX_RANGE_DAYS))

    if event.recurrence == RecurrencePattern.none:
        if event.start_at < limit_end and event.end_at > range_start:
            return [(event.start_at, event.end_at)]
        return []

    current_start = event.start_at
    generated = 0
    while current_start < limit_end:
        current_end = current_start + duration
        if current_end > range_start and current_start < limit_end:
            occurrences.append((current_start, current_end))
        generated += 1
        if event.recurrence_count and generated >= event.recurrence_count:
            break
        if event.recurrence_until and current_start > event.recurrence_until:
            break

        if event.recurrence == RecurrencePattern.daily:
            current_start = current_start + timedelta(days=event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.weekly:
            current_start = current_start + timedelta(weeks=event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.monthly:
            current_start = _month_increment(current_start, event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.yearly:
            current_start = _month_increment(current_start, 12 * event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.weekdays:
            next_day = current_start + timedelta(days=1)
            while next_day.weekday() > 4:
                next_day = next_day + timedelta(days=1)
            current_start = next_day
        else:
            break

    return occurrences


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


@router.post("/{home_id}/event-labels", response_model=EventLabelResponse, status_code=201)
async def create_label(
    home_id: uuid.UUID,
    body: EventLabelCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventLabelResponse:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    row = CalendarEventLabel(
        group_id=home_id,
        name=" ".join(body.name.strip().split()),
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
        CalendarEvent.start_at < end_at,
        CalendarEvent.end_at > start_at,
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
        for occurrence_start, occurrence_end in _expand_occurrences(event, start_at, end_at):
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
    await db.commit()

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
) -> EventOccurrence:
    membership = await require_capability(
        home_id, Capability.calendar_edit_own, auth, db
    )
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

    await db.execute(
        select(CalendarEventMember)
        .where(CalendarEventMember.event_id == event.id)
        .with_for_update()
    )
    await db.execute(delete(CalendarEventMember).where(CalendarEventMember.event_id == event.id))
    for user_id in requested_members:
        db.add(CalendarEventMember(group_id=home_id, event_id=event.id, user_id=user_id))

    await _record_activity(db, event, auth.user.id, "event.updated", "updated this event")
    audit(db, request, "calendar.event.updated", auth.user.id, home_id, "event", event.id)
    await db.commit()

    label = await db.get(CalendarEventLabel, event.label_id) if event.label_id else None
    return _occurrence(event, event.start_at, event.end_at, label, requested_members)


@router.delete("/{home_id}/events/{event_id}", status_code=204)
async def delete_event(
    home_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
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
    event.deleted_at = datetime.now(UTC)
    event.deleted_by = auth.user.id
    event.last_edited_by = auth.user.id
    await _record_activity(db, event, auth.user.id, "event.deleted", "deleted this event")
    audit(db, request, "calendar.event.deleted", auth.user.id, home_id, "event", event.id)
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
