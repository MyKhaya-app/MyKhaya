"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Bell,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Layers,
  MapPin,
  Plus,
  Search,
  Tag,
  Trash2,
  Users,
  X,
} from "lucide-react";
import type {
  BirthdayEntry,
  CalendarShare,
  EventLabel,
  EventMutationScope,
  EventOccurrence,
  EventPayload,
  HomeCalendar,
  Member,
  RecurrencePattern,
  SharedEventPayload,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { resolveColour } from "@mykhaya/design-tokens";
import { AppShellContent } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { AvatarStack } from "@/components/avatar";
import { participantsForEvent } from "@/components/avatar-stack-logic";
import { BottomSheet } from "@/components/bottom-sheet";
import { useActiveHome } from "@/components/use-active-home";
import { syncWidgetSnapshot } from "@/components/widget-bridge";
import { MonthSwipeView } from "./month-view";
import {
  addMonths,
  agendaRange,
  applyAllDayToggle,
  canDeleteEvent,
  canDeleteSharedEvent,
  canEditEvent,
  canEditSharedEvent,
  computeInitialWhen,
  DEFAULT_EVENT_DURATION_MINUTES,
  dateKey,
  dayRange,
  displayDate,
  emptyStateMessage,
  eventsForDay,
  eventTime,
  FALLBACK_TIMEZONE,
  filterByVisibleCalendars,
  filterVisibleEvents,
  groupEventsByDay,
  monthCells,
  monthRange,
  parseLocalInputValue,
  resolveMemberFilter,
  shiftEndWithStart,
  splitZoned,
  toEventUpdatePayload,
  toSharedEventUpdatePayload,
  weekRange,
  zonedDateKey,
  zonedTimeToUtc,
  zonedToday,
} from "./calendar-utils";

type ViewMode = "month" | "week" | "day" | "agenda";
const VIEW_STORAGE = "mykhaya.calendar.view";
const LABEL_STORAGE = "mykhaya.calendar.label";
// Home-scoped so a member selection never leaks from one Home to another —
// switching Home must never accidentally keep filtering by a member id that
// only means something in the Home the user just left.
const MEMBER_STORAGE_PREFIX = "mykhaya.calendar.member.";
// Per-viewer only (never sent to the backend) — which calendars (Home's own,
// keyed by HomeCalendar.id, or shared, keyed by CalendarShare.id) are
// currently hidden from the calendar views. Not Home-scoped like
// MEMBER_STORAGE_PREFIX: a shared calendar belongs to the *recipient*, not
// to any one Home, so this key is global to the signed-in browser profile.
const HIDDEN_CALENDARS_STORAGE = "mykhaya.calendar.hidden-calendars";

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

// `timeZone` must always be passed explicitly — the calendar grid's active
// timezone (the Home's primary calendar timezone) for headers/day labels, or
// an individual event's own governing timezone (event.timezone) when
// formatting that event's time. Never the browser's local zone, never a
// hardcoded UTC default: the server/browser timezone must never leak into
// what a user sees.
function relativeDayHeading(key: string, timeZone: string) {
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  if (key === zonedDateKey(now, timeZone)) return "Today";
  if (key === zonedDateKey(tomorrow, timeZone)) return "Tomorrow";
  return displayDate(
    `${key}T00:00:00Z`,
    { weekday: "long", day: "numeric", month: "long" },
    "UTC",
  );
}

const REMINDER_LABELS: Record<number, string> = {
  0: "At event time",
  15: "15 minutes before",
  60: "1 hour before",
  1440: "1 day before",
};
function reminderLabel(minutes: number | null): string | null {
  if (minutes === null) return null;
  return REMINDER_LABELS[minutes] ?? `${minutes} minutes before`;
}

const RECURRENCE_LABELS: Record<RecurrencePattern, string | null> = {
  none: null,
  daily: "Every day",
  weekly: "Every week",
  monthly: "Every month",
  yearly: "Every year",
  weekdays: "Every weekday",
};
function recurrenceLabel(recurrence: RecurrencePattern): string | null {
  return RECURRENCE_LABELS[recurrence];
}

// The read-only View mode's date/time line — reuses the exact same
// timezone-correct display utilities as every other calendar view (never a
// separate UTC/browser-local/naive formatting path). All-day boundaries are
// read as plain UTC calendar dates (never re-localized); timed instants are
// read in the event's own governing timezone.
function eventWhenSummary(
  event: EventOccurrence,
  timeZone: string,
): { dateLine: string; timeLine: string | null } {
  const tz = event.timezone || timeZone;
  const dateOptions: Intl.DateTimeFormatOptions = {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  };
  if (event.is_all_day) {
    const endInclusive = new Date(event.end_at);
    endInclusive.setUTCDate(endInclusive.getUTCDate() - 1);
    const startKey = dateKey(event.start_at);
    const endKey = dateKey(endInclusive);
    const dateLine =
      startKey === endKey
        ? displayDate(event.start_at, dateOptions, "UTC")
        : `${displayDate(event.start_at, dateOptions, "UTC")} — ${displayDate(endInclusive, dateOptions, "UTC")}`;
    return { dateLine, timeLine: "All day" };
  }
  const sameDay = zonedDateKey(event.start_at, tz) === zonedDateKey(event.end_at, tz);
  const startTimeLabel = displayDate(event.start_at, { hour: "2-digit", minute: "2-digit" }, tz);
  const endTimeLabel = displayDate(event.end_at, { hour: "2-digit", minute: "2-digit" }, tz);
  if (sameDay) {
    return {
      dateLine: displayDate(event.start_at, dateOptions, tz),
      timeLine: `${startTimeLabel} – ${endTimeLabel}`,
    };
  }
  return {
    dateLine: `${displayDate(event.start_at, dateOptions, tz)} ${startTimeLabel} → ${displayDate(event.end_at, dateOptions, tz)} ${endTimeLabel}`,
    timeLine: null,
  };
}

function combineZoned(date: string, time: string, timeZone: string): Date {
  const { year, month, day } = parseLocalInputValue(date);
  const [hour, minute] = time.split(":").map(Number);
  return zonedTimeToUtc(year, month, day, hour ?? 0, minute ?? 0, timeZone);
}

// A pure UTC-midnight calendar date, independent of any timezone — see
// `_all_day_midnight` on the backend for why all-day boundaries deliberately
// never go through zone conversion.
function utcMidnightOf(dateInput: string): Date {
  const { year, month, day } = parseLocalInputValue(dateInput);
  return new Date(Date.UTC(year, month - 1, day));
}

// Calendar and Calendar Tag are two independent concepts on an event
// (calendar_id / label_id) — this is the frontend's *Calendar* picker's
// sentinel scheme (see the separate `tagSelection` state below for Calendar
// Tag). Home calendars (including secondary ones like "GFOAT") are offered
// by their real HomeCalendar id; Personal Calendar and a writable shared
// calendar aren't in that same list, so they need their own sentinel
// values, never sent to the API as-is — submit() translates them into
// calendar_id (or routes to onSubmitShared entirely).
const PERSONAL_CALENDAR_VALUE = "__personal__";
// Sentinel prefix for a writable (Can add & edit) externally shared
// calendar, appended with its CalendarShare.id. Only ever offered when
// *creating* a brand-new event (see writableShares below); an existing
// event's calendar assignment never changes via edit, matching the Home
// calendar's own "calendar_id is fixed at creation" rule.
const SHARE_VALUE_PREFIX = "__share__:";

// Whether this occurrence's edit/delete should offer the recurring-scope
// chooser (occurrence / this-and-future / entire series) rather than acting
// immediately. Deliberately keyed on the event's own `recurrence` field —
// the base series' recurrence pattern, always populated regardless of
// whether *this* occurrence happens to be overridden or moved — never on
// `occurrence_id` or `is_overridden`: a previously-overridden or moved
// occurrence is still part of a recurring series and must still offer the
// same three choices. Externally shared-calendar events are excluded: the
// share-scoped mutation endpoints (updateSharedEvent/deleteSharedEvent)
// don't accept a scope/occurrence_start yet, so those keep their existing
// whole-event behaviour unconditionally, same as before this feature.
function isRecurringOwnEvent(event: EventOccurrence): boolean {
  return !event.share_id && event.recurrence !== "none";
}

function EventForm({
  labels,
  homeCalendars,
  members,
  initial,
  initialDay,
  timeZone,
  personalCalendarId,
  writableShares = [],
  busy,
  submitLabel,
  sharedEventsEnabled,
  onSubmit,
  onSubmitShared,
  onCancel,
  onDelete,
}: {
  /** Calendar Tags (CalendarEventLabel) — a colour/category tag, entirely
   *  independent of which calendar contains the event. */
  labels: EventLabel[];
  /** This Home's own calendars (the primary "Home calendar" plus any
   *  secondary ones, e.g. "GFOAT") — the canonical list from
   *  GET /homes/{id}/calendars, same source the Calendars overlay/visibility
   *  sheet and Home calendar management already use. Never includes the
   *  Personal Calendar (see personalCalendarId) or shared calendars (see
   *  writableShares) — those are offered as separate picker entries below. */
  homeCalendars: HomeCalendar[];
  members: Member[];
  initial?: EventOccurrence;
  initialDay: Date;
  /** The IANA timezone new Start/End wall-clock values are interpreted in —
   *  the calendar's active (Home) timezone for a new event, or the event's
   *  own governing timezone when editing one that already has a different
   *  one set. Never the browser's local zone, never a hardcoded literal. */
  timeZone: string;
  /** The signed-in user's private Personal Calendar within this Home — null
   *  only in the brief window before it's loaded (see CalendarPage.load) or
   *  for a managed Child, who doesn't have one. */
  personalCalendarId: string | null;
  /** Externally shared calendars the signed-in user may create events on
   *  (permission "manage", accepted) — offered as extra targets in the
   *  Calendar picker only when creating a brand-new event (initial is
   *  undefined). Empty for the edit flow and whenever the user has none. */
  writableShares?: CalendarShare[];
  busy: boolean;
  submitLabel: string;
  sharedEventsEnabled: boolean;
  onSubmit: (payload: EventPayload) => Promise<void>;
  /** Called instead of onSubmit when the user picked a shared calendar as
   *  the target for a *new* event — only relevant during creation. */
  onSubmitShared?: (shareId: string, payload: SharedEventPayload) => Promise<void>;
  onCancel: () => void;
  onDelete?: () => Promise<void>;
}) {
  const eventTimeZone = initial?.timezone || timeZone;
  const [initialWhen] = useState(() =>
    computeInitialWhen(initial, initialDay, eventTimeZone),
  );
  // Moves focus into the form as soon as it mounts — i.e. every time the
  // sheet unlocks from View into Edit (EventForm mounts fresh each time).
  // Focuses the form itself (tabIndex=-1), never a text field directly: the
  // same iOS Safari zoom-on-focus concern BottomSheet's own initial-focus
  // logic already avoids.
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    formRef.current?.focus();
  }, []);
  const [allDay, setAllDay] = useState(initialWhen.allDay);
  const [startDate, setStartDate] = useState(initialWhen.startDate);
  const [startTime, setStartTime] = useState(initialWhen.startTime);
  const [endDate, setEndDate] = useState(initialWhen.endDate);
  const [endTime, setEndTime] = useState(initialWhen.endTime);
  const [multiDay, setMultiDay] = useState(initialWhen.multiDay);
  const [rangeNotice, setRangeNotice] = useState("");
  const [recurrence, setRecurrence] = useState<RecurrencePattern>(
    initial?.recurrence ?? "none",
  );
  const [recurrenceEndMode, setRecurrenceEndMode] = useState<"never" | "on_date">(
    initial?.recurrence_end_date ? "on_date" : "never",
  );
  const [recurrenceEndDate, setRecurrenceEndDate] = useState(
    initial?.recurrence_end_date ?? initialWhen.startDate,
  );
  const [recurrenceNotice, setRecurrenceNotice] = useState("");
  // See WhenState.hasTimedValues — a ref, not state, because flipping it
  // must never itself trigger a render; it only gates what onToggleAllDay
  // does the next time the user actually turns All day off.
  const hasTimedValues = useRef(initialWhen.hasTimedValues);
  // Editing an occurrence merged in from an externally shared calendar (see
  // CalendarPage.load) — People and Calendar Tag never apply: the recipient
  // isn't a Home member (nothing to assign to) and Calendar Tags are
  // Home-owned structure they aren't authorised to use. onSubmit's payload
  // still carries member_ids/label_id (unused fields, always empty/None
  // here) but the parent strips them via toSharedEventPayload before this
  // ever reaches the share-scoped endpoint — see calendar-utils.ts.
  const isSharedEvent = Boolean(initial?.share_id);
  // The Calendar picker's value: a real HomeCalendar id (covers both the
  // primary "Home calendar" and any secondary one, e.g. "GFOAT"),
  // PERSONAL_CALENDAR_VALUE, or a SHARE_VALUE_PREFIX-tagged CalendarShare id
  // (create-only). Controlled (not read from FormData like the rest of this
  // form) so the "Only you can see..."/"shared with you" supporting copy can
  // react live to the current selection. Immutable once editing an existing
  // event — see the Calendar <select>'s `disabled` below — so this only
  // ever reflects, never changes, initial.calendar_id on edit.
  const [calendarTarget, setCalendarTarget] = useState(() => {
    if (initial) {
      return personalCalendarId && initial.calendar_id === personalCalendarId
        ? PERSONAL_CALENDAR_VALUE
        : initial.calendar_id;
    }
    return homeCalendars.find((calendar) => calendar.is_primary)?.id ?? "";
  });
  // The Calendar Tag picker's value — a real CalendarEventLabel id, or ""
  // for "No tag". Entirely independent of calendarTarget: which calendar
  // contains the event never constrains which tag it can carry (or vice
  // versa) — see docs on Calendar vs Calendar Tag.
  const [tagSelection, setTagSelection] = useState(() => initial?.label?.id ?? "");

  function zonedInstant(date: string, time: string): Date {
    return combineZoned(date, time, eventTimeZone);
  }

  // See applyAllDayToggle (calendar-utils.ts) for the rule this applies —
  // toggling All day off must never derive a clock value from the all-day
  // UTC-midnight boundary; it establishes a sensible default only once per
  // session, preserving whatever meaningful timed value already exists
  // otherwise (startDate/endDate — the intended calendar date(s) — are
  // untouched either way).
  function onToggleAllDay(nextAllDay: boolean) {
    const next = applyAllDayToggle(
      {
        allDay,
        startDate,
        startTime,
        endDate,
        endTime,
        multiDay,
        hasTimedValues: hasTimedValues.current,
      },
      nextAllDay,
    );
    setAllDay(next.allDay);
    setStartTime(next.startTime);
    setEndTime(next.endTime);
    hasTimedValues.current = next.hasTimedValues;
  }

  // Duration-aware: moving Start carries End along by the same duration
  // (defaulting new events to 1 hour, preserving whatever duration the user
  // has already established otherwise) — see shiftEndWithStart.
  function applyNewStart(nextStart: Date) {
    const previousStart = zonedInstant(startDate, startTime);
    const previousEnd = zonedInstant(endDate, endTime);
    const nextEnd = shiftEndWithStart(previousStart, previousEnd, nextStart);
    const next = splitZoned(nextEnd, eventTimeZone);
    setEndDate(next.date);
    setEndTime(next.time);
    setRangeNotice("");
  }

  function onStartDateChange(value: string) {
    setStartDate(value);
    if (!multiDay) setEndDate(value);
    applyNewStart(zonedInstant(value, startTime));
  }
  function onStartTimeChange(value: string) {
    setStartTime(value);
    applyNewStart(zonedInstant(startDate, value));
  }
  // End is user-editable directly too, but must never be allowed to precede
  // Start for a same-day event — corrected in place (kept to a sensible
  // minimum duration) rather than silently accepted and only rejected later
  // by the backend.
  function onEndDateChange(value: string) {
    const candidate = zonedInstant(value, endTime);
    const start = zonedInstant(startDate, startTime);
    if (candidate <= start) {
      setRangeNotice("End adjusted to stay after Start.");
      const corrected = new Date(start.getTime() + DEFAULT_EVENT_DURATION_MINUTES * 60_000);
      const next = splitZoned(corrected, eventTimeZone);
      setEndDate(next.date);
      setEndTime(next.time);
      return;
    }
    setRangeNotice("");
    setEndDate(value);
  }
  function onEndTimeChange(value: string) {
    const candidate = zonedInstant(endDate, value);
    const start = zonedInstant(startDate, startTime);
    if (!multiDay && candidate <= start) {
      setRangeNotice("End adjusted to stay after Start.");
      const corrected = new Date(start.getTime() + DEFAULT_EVENT_DURATION_MINUTES * 60_000);
      const next = splitZoned(corrected, eventTimeZone);
      setEndDate(next.date);
      setEndTime(next.time);
      return;
    }
    setRangeNotice("");
    setEndTime(value);
  }
  function onToggleMultiDay(next: boolean) {
    setMultiDay(next);
    if (!next) setEndDate(startDate);
    setRangeNotice("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const title = formText(data, "title").trim();

    let start_at: string;
    let end_at: string;
    if (allDay) {
      const start = utcMidnightOf(startDate);
      const lastCoveredDay = utcMidnightOf(multiDay ? endDate : startDate);
      const end = new Date(lastCoveredDay);
      end.setUTCDate(end.getUTCDate() + 1); // exclusive end, matching backend semantics
      start_at = start.toISOString();
      end_at = end.toISOString();
    } else {
      start_at = zonedInstant(startDate, startTime).toISOString();
      end_at = zonedInstant(multiDay ? endDate : startDate, endTime).toISOString();
    }

    const isPersonal = calendarTarget === PERSONAL_CALENDAR_VALUE;
    const sharedTargetId = calendarTarget.startsWith(SHARE_VALUE_PREFIX)
      ? calendarTarget.slice(SHARE_VALUE_PREFIX.length)
      : null;
    const savedRecurrenceEndDate =
      recurrence !== "none" && recurrenceEndMode === "on_date" ? recurrenceEndDate : null;
    if (savedRecurrenceEndDate && savedRecurrenceEndDate < startDate) {
      setRecurrenceNotice("End date must be on or after the event start date.");
      return;
    }
    setRecurrenceNotice("");

    if (sharedTargetId && onSubmitShared) {
      await onSubmitShared(sharedTargetId, {
        title,
        start_at,
        end_at,
        timezone: eventTimeZone,
        is_all_day: allDay,
        location_text: formText(data, "location") || null,
        reminder_minutes: formText(data, "reminder") ? Number(formText(data, "reminder")) : null,
        recurrence,
        recurrence_interval: 1,
        recurrence_until: null,
        recurrence_end_date: savedRecurrenceEndDate,
        recurrence_count: null,
        description: formText(data, "notes") || null,
      });
      return;
    }

    await onSubmit({
      title,
      start_at,
      end_at,
      timezone: eventTimeZone,
      is_all_day: allDay,
      // A Personal Calendar event can never be assigned to anyone else (the
      // backend rejects this too — see create_event/update_event's
      // Personal-Calendar member check — this just avoids a round-trip
      // rejection when the People section still shows other members
      // checked from before switching to Personal calendar). Calendar Tag
      // is independent of the calendar, though: a Personal Calendar event
      // can still carry a tag (Megan/Activity/Other/...), so this is never
      // forced to null just because the calendar is Personal.
      member_ids: isPersonal ? [] : data.getAll("members").map(String),
      label_id: tagSelection || null,
      calendar_id: isPersonal ? personalCalendarId : calendarTarget || null,
      location_text: formText(data, "location") || null,
      reminder_minutes: formText(data, "reminder")
        ? Number(formText(data, "reminder"))
        : null,
      recurrence,
      recurrence_interval: 1,
      recurrence_until: null,
      recurrence_end_date: savedRecurrenceEndDate,
      recurrence_count: null,
      description: formText(data, "notes") || null,
    });
  }

  return (
    <form className="event-form" onSubmit={submit} ref={formRef} tabIndex={-1}>
      <label className="form-wide">
        Title
        <input
          name="title"
          defaultValue={initial?.title ?? ""}
          required
          maxLength={180}
        />
      </label>
      <div className="form-wide event-section">
        <div className="event-section-heading">
          <span className="eyebrow">When</span>
          <label className="event-when-toggle">
            All day
            <input
              className="switch"
              type="checkbox"
              role="switch"
              aria-checked={allDay}
              checked={allDay}
              onChange={(event) => onToggleAllDay(event.target.checked)}
            />
          </label>
        </div>
        <div className="event-when-grid">
          <label className="form-wide datetime-card">
            <span className="datetime-card-icon" aria-hidden="true">
              <CalendarDays size={18} />
            </span>
            <span className="datetime-card-body">
              <span className="datetime-card-caption">{multiDay ? "Starts" : "Date"}</span>
              <input
                className="datetime-card-input"
                type="date"
                value={startDate}
                onChange={(event) => onStartDateChange(event.target.value)}
                required
              />
            </span>
            <ChevronDown className="datetime-card-chevron" size={16} aria-hidden="true" />
          </label>
          {!allDay && (
            <label>
              Start
              <span className="time-card">
                <Clock className="time-card-icon" size={15} aria-hidden="true" />
                <input
                  className="time-card-input"
                  type="time"
                  value={startTime}
                  onChange={(event) => onStartTimeChange(event.target.value)}
                  required
                />
              </span>
            </label>
          )}
          {!allDay && !multiDay && (
            <label>
              End
              <span className="time-card">
                <Clock className="time-card-icon" size={15} aria-hidden="true" />
                <input
                  className="time-card-input"
                  type="time"
                  value={endTime}
                  onChange={(event) => onEndTimeChange(event.target.value)}
                  required
                />
              </span>
            </label>
          )}
        </div>
        {multiDay && (
          <div className="event-when-grid">
            <label className="form-wide datetime-card">
              <span className="datetime-card-icon" aria-hidden="true">
                <CalendarDays size={18} />
              </span>
              <span className="datetime-card-body">
                <span className="datetime-card-caption">Ends</span>
                <input
                  className="datetime-card-input"
                  type="date"
                  value={endDate}
                  onChange={(event) => onEndDateChange(event.target.value)}
                  required
                />
              </span>
              <ChevronDown className="datetime-card-chevron" size={16} aria-hidden="true" />
            </label>
            {!allDay && (
              <label>
                End time
                <span className="time-card">
                  <Clock className="time-card-icon" size={15} aria-hidden="true" />
                  <input
                    className="time-card-input"
                    type="time"
                    value={endTime}
                    onChange={(event) => onEndTimeChange(event.target.value)}
                    required
                  />
                </span>
              </label>
            )}
          </div>
        )}
        <button
          type="button"
          className="pill-button"
          onClick={() => onToggleMultiDay(!multiDay)}
        >
          {multiDay ? "− Same day event" : "+ Ends on another day"}
        </button>
        {rangeNotice && <p className="quiet-state">{rangeNotice}</p>}
      </div>
      {/* A Personal Calendar event is never shared — see create_event's
          Personal-Calendar member check — so there is nothing for the
          People section to offer while it's selected. Same reasoning for an
          externally shared event: the recipient isn't a Home member, so
          there's no household roster to assign it to. */}
      {members.length > 0 &&
        !isSharedEvent &&
        calendarTarget !== PERSONAL_CALENDAR_VALUE &&
        !calendarTarget.startsWith(SHARE_VALUE_PREFIX) && (
        <div className="form-wide event-section">
          <span className="eyebrow">People</span>
          <div className="member-list">
            {members.map((member) => {
              // Assigning a *new* member is the Family-only "shared event"
              // capability (events.shared.enabled) — a member already on this
              // event stays freely toggleable (so removing one, or simply
              // re-saving other fields, always works) even on Free; only
              // checking a box for someone not already assigned is locked.
              // Disabling (rather than hiding) an already-checked box would
              // drop it from the submitted form data entirely, so this only
              // ever disables boxes that are unchecked to begin with.
              const alreadyIncluded = initial?.member_ids.includes(member.user_id) ?? false;
              const locked = !sharedEventsEnabled && !alreadyIncluded;
              return (
                <label
                  className={`member-row${locked ? " member-row-locked" : ""}`}
                  key={member.user_id}
                >
                  <Avatar
                    id={member.user_id}
                    name={member.display_name}
                    colour={member.colour}
                    avatarVersion={member.avatar_version}
                    size="sm"
                  />
                  <span className="member-row-name">
                    {member.display_name}
                    {locked && <span className="quiet-state"> · Family</span>}
                  </span>
                  <input
                    name="members"
                    type="checkbox"
                    value={member.user_id}
                    defaultChecked={alreadyIncluded}
                    disabled={locked}
                    aria-label={`Include ${member.display_name}`}
                  />
                </label>
              );
            })}
          </div>
          {!sharedEventsEnabled && (
            <p className="quiet-state">
              Assigning this event to other household members is available with MyKhaya Family.
            </p>
          )}
        </div>
      )}
      {isSharedEvent && (
        <p className="form-wide icon-row">
          <span className="icon-row-icon" aria-hidden="true">
            <Layers size={16} />
          </span>
          <span className="icon-row-control quiet-state">
            {initial?.shared_by_home_name
              ? `Shared by ${initial.shared_by_home_name} — no Calendar Tag to choose here.`
              : "Shared calendar — no Calendar Tag to choose here."}
          </span>
        </p>
      )}
      {!isSharedEvent && (
      <label className="form-wide icon-row">
        <span className="icon-row-icon" aria-hidden="true">
          <Layers size={16} />
        </span>
        <span className="sr-only">Calendar</span>
        <select
          className="icon-row-control"
          name="calendar"
          value={calendarTarget}
          onChange={(event) => setCalendarTarget(event.target.value)}
          // Where an event lives is fixed at creation — matching the
          // backend's EventUpdate schema, which has no calendar_id field at
          // all (moving an existing event between calendars isn't
          // supported). Shown (not hidden) on edit so it's still clear
          // which calendar the event belongs to.
          disabled={Boolean(initial)}
        >
          <optgroup label="Home calendars">
            {homeCalendars.map((calendar) => {
              // Transition-safe, matching update_event's own check: the
              // calendar an event already lives on stays selectable (so
              // resaving never breaks), but a different, over-the-plan-limit
              // calendar preserved past a downgrade can't be newly targeted.
              const locked =
                calendar.commercial_access === "read_only_due_to_plan" &&
                initial?.calendar_id !== calendar.id;
              return (
                <option key={calendar.id} value={calendar.id} disabled={locked}>
                  {calendar.is_primary ? "Home calendar" : calendar.name}
                  {locked ? " (Family)" : ""}
                </option>
              );
            })}
          </optgroup>
          {personalCalendarId && (
            <option value={PERSONAL_CALENDAR_VALUE}>Personal calendar</option>
          )}
          {/* Only ever offered when creating a brand-new event — an
              existing event's calendar assignment never changes via edit
              (initial is undefined here whenever writableShares is
              non-empty, since the parent only passes shares for the create
              flow). */}
          {writableShares.length > 0 && (
            <optgroup label="Shared calendars">
              {writableShares.map((share) => (
                <option key={share.id} value={`${SHARE_VALUE_PREFIX}${share.id}`}>
                  {share.calendar_name} · {share.source_group_name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <ChevronDown className="icon-row-chevron" size={16} aria-hidden="true" />
      </label>
      )}
      {calendarTarget === PERSONAL_CALENDAR_VALUE && (
        <p className="form-wide quiet-state">Only you can see events in this calendar.</p>
      )}
      {calendarTarget.startsWith(SHARE_VALUE_PREFIX) && (
        <p className="form-wide quiet-state">
          This event will be created on a calendar shared with you — everyone it's shared with
          can see it.
        </p>
      )}
      {/* Calendar Tag: a colour/category tag, entirely separate from which
          calendar contains the event (see PERSONAL_CALENDAR_VALUE's
          docstring above) — never offered for a shared-calendar event or
          target, since a CalendarEventLabel is Home-owned structure an
          external recipient isn't authorised to use (same reasoning as the
          People section above). */}
      {!isSharedEvent && !calendarTarget.startsWith(SHARE_VALUE_PREFIX) && (
        <label className="form-wide icon-row">
          <span className="icon-row-icon" aria-hidden="true">
            <Tag size={16} />
          </span>
          <span className="sr-only">Calendar Tag</span>
          <select
            className="icon-row-control"
            name="tag"
            value={tagSelection}
            onChange={(event) => setTagSelection(event.target.value)}
          >
            <option value="">No tag</option>
            {labels.map((label) => {
              // Transition-safe, matching update_event's own check: a tag
              // already assigned to this event stays selectable (so
              // resaving never breaks), but a different, over-the-plan-limit
              // tag preserved past a downgrade can't be newly assigned.
              const locked =
                label.commercial_access === "read_only_due_to_plan" &&
                initial?.label?.id !== label.id;
              return (
                <option key={label.id} value={label.id} disabled={locked}>
                  {label.name}
                  {locked ? " (Family)" : ""}
                </option>
              );
            })}
          </select>
          <ChevronDown className="icon-row-chevron" size={16} aria-hidden="true" />
        </label>
      )}
      <label className="form-wide icon-row">
        <span className="icon-row-icon" aria-hidden="true">
          <MapPin size={16} />
        </span>
        <span className="sr-only">Location</span>
        <input
          className="icon-row-control"
          name="location"
          placeholder="Add a location"
          maxLength={200}
          defaultValue={initial?.location_text ?? ""}
        />
      </label>
      <details className="form-wide event-advanced">
        <summary>
          <span className="event-advanced-lead">
            <span className="icon-row-icon" aria-hidden="true">
              <Bell size={16} />
            </span>
            Reminder, repeat and notes
          </span>
          <ChevronRight className="chevron" size={18} aria-hidden="true" />
        </summary>
        <div className="event-form advanced-fields">
          <label>
            Reminder
            <select
              name="reminder"
              defaultValue={initial?.reminder_minutes ?? ""}
            >
              <option value="">None</option>
              <option value="0">At event time</option>
              <option value="15">15 minutes before</option>
              <option value="60">1 hour before</option>
              <option value="1440">1 day before</option>
            </select>
          </label>
          <label>
            Repeat
            <select
              name="recurrence"
              value={recurrence}
              onChange={(event) => {
                const next = event.target.value as RecurrencePattern;
                setRecurrence(next);
                if (next === "none") {
                  setRecurrenceEndMode("never");
                  setRecurrenceEndDate("");
                  setRecurrenceNotice("");
                }
              }}
            >
              <option value="none">Does not repeat</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
              <option value="weekdays">Weekdays</option>
            </select>
          </label>
          {recurrence !== "none" && (
            <>
              <label>
                Ends
                <select
                  name="recurrence_end_mode"
                  value={recurrenceEndMode}
                  onChange={(event) => {
                    const next = event.target.value as "never" | "on_date";
                    setRecurrenceEndMode(next);
                    if (next === "never") {
                      setRecurrenceEndDate("");
                      setRecurrenceNotice("");
                    } else if (!recurrenceEndDate) {
                      setRecurrenceEndDate(startDate);
                    }
                  }}
                >
                  <option value="never">Never</option>
                  <option value="on_date">On date</option>
                </select>
              </label>
              {recurrenceEndMode === "on_date" && (
                <label className="form-wide datetime-card recurrence-end-date-field">
                  <span className="datetime-card-icon" aria-hidden="true">
                    <CalendarDays size={18} />
                  </span>
                  <span className="datetime-card-body">
                    <span className="datetime-card-caption">End date</span>
                    <input
                      className="datetime-card-input"
                      type="date"
                      value={recurrenceEndDate}
                      min={startDate}
                      onChange={(event) => {
                        setRecurrenceEndDate(event.target.value);
                        setRecurrenceNotice("");
                      }}
                      required
                    />
                  </span>
                  <ChevronDown className="datetime-card-chevron" size={16} aria-hidden="true" />
                </label>
              )}
              {recurrenceNotice && <p className="quiet-state form-wide">{recurrenceNotice}</p>}
            </>
          )}
          <label className="form-wide">
            Notes
            <textarea
              name="notes"
              maxLength={2000}
              defaultValue={initial?.description ?? ""}
            />
          </label>
        </div>
      </details>
      <div className="sheet-actions form-wide">
        <button disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
        <button className="secondary" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {onDelete && (
        <button className="danger-link" type="button" disabled={busy} onClick={onDelete}>
          <Trash2 size={16} aria-hidden="true" />
          Delete event
        </button>
      )}
    </form>
  );
}

// The read-only View state a tapped event opens into. Deliberately a
// separate component from EventForm (rather than one form with every field
// disabled) — presentation and editing are different user actions with
// different visual languages (see the design brief: no input borders, no
// disabled-looking controls, just information). Nothing here can mutate the
// event; the only interactive elements are Edit/Delete, both gated by the
// same permission rules the backend enforces.
function EventDetails({
  event,
  members,
  timeZone,
  personalCalendarId,
  homeName,
  canDelete,
  onDelete,
  busy = false,
}: {
  event: EventOccurrence;
  members: Member[];
  timeZone: string;
  personalCalendarId: string | null;
  /** The active Home's own name — "Calendar: {homeName}" for an event on
   *  the Home calendar itself, matching how a Personal or Shared
   *  calendar's own identity is shown. Never used for a Personal or Shared
   *  event, which show their own identity instead — see the Calendar
   *  section below. */
  homeName: string;
  canDelete: boolean;
  onDelete: () => Promise<void>;
  busy?: boolean;
}) {
  const { dateLine, timeLine } = eventWhenSummary(event, timeZone);
  const people = event.member_ids
    .map((id) => members.find((member) => member.user_id === id))
    .filter((member): member is Member => Boolean(member));
  const reminder = reminderLabel(event.reminder_minutes);
  const repeat = recurrenceLabel(event.recurrence);

  return (
    <div className="event-view">
      <div className="event-view-when">
        <strong>{dateLine}</strong>
        {timeLine && <span>{timeLine}</span>}
      </div>

      {event.location_text && (
        <div className="event-view-section">
          <span className="eyebrow">Location</span>
          <div className="event-view-value">
            <MapPin size={16} aria-hidden="true" />
            {event.location_text}
          </div>
        </div>
      )}

      {people.length > 0 && (
        <div className="event-view-section">
          <span className="eyebrow">People</span>
          <div className="event-view-people">
            {people.map((member) => (
              <div className="event-view-person" key={member.user_id}>
                <Avatar
                  id={member.user_id}
                  name={member.display_name}
                  colour={member.colour}
                  avatarVersion={member.avatar_version}
                  size="sm"
                />
                {member.display_name}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="event-view-section">
        <span className="eyebrow">Calendar</span>
        <div className="event-view-value">
          <span
            className="colour-dot"
            style={{ "--swatch-colour": resolveColour(event.calendar_color) } as React.CSSProperties}
            aria-hidden="true"
          />
          {event.shared_by_home_name
            ? event.shared_by_home_name
            : personalCalendarId && event.calendar_id === personalCalendarId
              ? "Personal calendar"
              : homeName}
        </div>
        {event.shared_by_home_name && (
          <p className="quiet-state shared-calendar-attribution">
            <Users size={13} aria-hidden="true" />
            Shared calendar · {event.share_permission === "manage" ? "Can add & edit" : "Can view"}
          </p>
        )}
      </div>

      {/* Calendar Tag is a separate concept from Calendar (see docs on the
          calendar types vs Calendar Tags) — a CalendarEventLabel, never
          shown as if it were the calendar's own identity. Any event on a
          Home calendar or the Personal Calendar can carry one; only an
          externally shared event never has one (Calendar Tags are
          Home-owned structure the recipient isn't authorised to use). */}
      {event.label && (
        <div className="event-view-section">
          <span className="eyebrow">Calendar Tag</span>
          <div className="event-view-value">
            <span
              className="colour-dot"
              style={{ "--swatch-colour": resolveColour(event.label.color) } as React.CSSProperties}
              aria-hidden="true"
            />
            {event.label.name}
          </div>
        </div>
      )}

      {reminder && (
        <div className="event-view-section">
          <span className="eyebrow">Reminder</span>
          <p>{reminder}</p>
        </div>
      )}

      {repeat && (
        <div className="event-view-section">
          <span className="eyebrow">Repeat</span>
          <p>{repeat}</p>
          {event.recurrence_end_date && (
            <p>Ends {displayDate(`${event.recurrence_end_date}T00:00:00Z`, { dateStyle: "long" }, "UTC")}</p>
          )}
        </div>
      )}

      {event.description && (
        <div className="event-view-section">
          <span className="eyebrow">Notes</span>
          <p className="event-view-notes">{event.description}</p>
        </div>
      )}

      {canDelete && (
        <div className="event-view-actions">
          <button className="danger-link" type="button" disabled={busy} onClick={onDelete}>
            <Trash2 size={16} aria-hidden="true" />
            Delete event
          </button>
        </div>
      )}
    </div>
  );
}

// The recurring-event scope chooser shown before an edit or delete on a
// series' own occurrence actually reaches the API — see isRecurringOwnEvent.
// Deliberately worded without any of the backend's internal vocabulary
// ("exception", "override", "split", "canonical occurrence"): the three
// choices map 1:1 onto EventMutationScope but are named the way an end user
// thinks about a recurring event.
function RecurrenceScopeSheet({
  mode,
  onChoose,
  onCancel,
  busy,
  error,
}: {
  mode: "edit" | "delete";
  onChoose: (scope: EventMutationScope) => void;
  onCancel: () => void;
  busy: boolean;
  error: string;
}) {
  const options: { scope: EventMutationScope; label: string }[] =
    mode === "edit"
      ? [
          { scope: "occurrence", label: "This occurrence only" },
          { scope: "future", label: "This and future occurrences" },
          { scope: "series", label: "Entire series" },
        ]
      : [
          { scope: "occurrence", label: "Delete this occurrence" },
          { scope: "future", label: "Delete this and future occurrences" },
          { scope: "series", label: "Delete entire series" },
        ];
  return (
    <BottomSheet
      title={mode === "edit" ? "Apply changes to" : "Delete recurring event"}
      onDismiss={busy ? () => {} : onCancel}
    >
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <nav className={mode === "delete" ? "sheet-menu recurrence-delete-menu" : "sheet-menu"}>
        {options.map((option) => (
          <button
            key={option.scope}
            type="button"
            className={mode === "delete" ? "sheet-menu-item danger" : "sheet-menu-item"}
            disabled={busy}
            onClick={() => onChoose(option.scope)}
          >
            {option.label}
          </button>
        ))}
        <button
          type="button"
          className="sheet-menu-item"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </button>
      </nav>
    </BottomSheet>
  );
}

export default function CalendarPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { activeHome, activeHomeId } = useActiveHome();
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [featureChecked, setFeatureChecked] = useState(false);
  const [view, setView] = useState<ViewMode>("month");
  const [focusDate, setFocusDate] = useState(() => zonedToday(FALLBACK_TIMEZONE));
  // True once the user has actually navigated (prev/next, tapping a day, or
  // jumping to today) — until then, focusDate keeps re-anchoring to "today"
  // as soon as the real calendarTimezone loads, so the initial render (which
  // only has FALLBACK_TIMEZONE to go on) doesn't strand the user looking at
  // the wrong calendar date for their Home's actual timezone.
  const hasNavigated = useRef(false);
  const [events, setEvents] = useState<EventOccurrence[]>([]);
  const [birthdays, setBirthdays] = useState<BirthdayEntry[]>([]);
  const [labels, setLabels] = useState<EventLabel[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [sharedEventsEnabled, setSharedEventsEnabled] = useState(false);
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [editorDay, setEditorDay] = useState<Date | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<EventOccurrence | null>(
    null,
  );
  // Whether the currently open existing-event sheet is unlocked for editing.
  // Always starts false — tapping an event opens it read-only (View); Edit
  // is an explicit, separate action. Reset by openEvent/closeEventSheet so
  // an event's draft state can never leak into the next event opened.
  const [editingSelected, setEditingSelected] = useState(false);
  // Set the instant Save/Delete is pressed on a recurring event's own
  // occurrence (never a shared-calendar one — see isRecurringOwnEvent), and
  // cleared on Cancel/success/failure-that-should-restart. Holding the
  // already-extracted EventPayload here (rather than re-reading the form)
  // is what lets a failed occurrence/future mutation retry without losing
  // the user's edits, and is also why Cancel never needs to touch the API:
  // no request has been sent yet at the point this is set.
  const [pendingEditPayload, setPendingEditPayload] = useState<EventPayload | null>(null);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [scopeBusy, setScopeBusy] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [labelFilter, setLabelFilter] = useState("");
  const [memberFilter, setMemberFilter] = useState("");
  // The Home's primary calendar's IANA timezone — the default/shared
  // timezone for household calendar events (never the server's or the
  // browser's own timezone). FALLBACK_TIMEZONE only covers the brief window
  // before the first successful load.
  const [calendarTimezone, setCalendarTimezone] = useState(FALLBACK_TIMEZONE);
  // The signed-in user's own private Personal Calendar within this Home —
  // null before the first load resolves, or for a managed Child (see
  // apps/api/mykhaya/calendar_provisioning.py). Never another member's.
  const [personalCalendarId, setPersonalCalendarId] = useState<string | null>(null);
  const [personalCalendar, setPersonalCalendar] = useState<HomeCalendar | null>(null);
  // "My calendars" (this Home's own, shared/Home + the viewer's Personal
  // Calendar) and "Shared with me" (accepted external CalendarShares) — see
  // CalendarSelector below. Both are always fetched regardless of visibility
  // toggles, same convention as member/label filters: fetch everything,
  // filter client-side (see visibleEvents/filterByVisibleCalendars).
  const [homeCalendars, setHomeCalendars] = useState<HomeCalendar[]>([]);
  const [sharedCalendars, setSharedCalendars] = useState<CalendarShare[]>([]);
  const [hiddenCalendarIds, setHiddenCalendarIds] = useState<Set<string>>(new Set());
  const [calendarSelectorOpen, setCalendarSelectorOpen] = useState(false);
  const agendaAnchorRef = useRef<HTMLElement | null>(null);
  const agendaEntryToken = useRef(0);
  const positionedAgendaToken = useRef(-1);

  useEffect(() => {
    setLabelFilter(window.localStorage.getItem(LABEL_STORAGE) ?? "");
  }, []);

  function chooseLabel(next: string) {
    setLabelFilter(next);
    window.localStorage.setItem(LABEL_STORAGE, next);
  }

  useEffect(() => {
    const stored = window.localStorage.getItem(HIDDEN_CALENDARS_STORAGE);
    if (!stored) return;
    try {
      const parsed: unknown = JSON.parse(stored);
      if (Array.isArray(parsed)) setHiddenCalendarIds(new Set(parsed.map(String)));
    } catch {
      // Corrupt/legacy value — fall back to "everything visible" rather than
      // blocking the calendar from loading at all.
    }
  }, []);

  function toggleCalendarVisibility(id: string) {
    setHiddenCalendarIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      window.localStorage.setItem(HIDDEN_CALENDARS_STORAGE, JSON.stringify([...next]));
      return next;
    });
  }

  // Restore the previously selected household member for *this* Home as soon
  // as we know which Home is active, and re-restore whenever the active Home
  // changes — a stored id for Home A must never carry over when the user
  // switches to Home B.
  useEffect(() => {
    if (!activeHomeId) return;
    setMemberFilter(
      window.localStorage.getItem(MEMBER_STORAGE_PREFIX + activeHomeId) ?? "",
    );
  }, [activeHomeId]);

  function chooseMember(next: string) {
    setMemberFilter(next);
    if (activeHomeId)
      window.localStorage.setItem(MEMBER_STORAGE_PREFIX + activeHomeId, next);
  }

  // Guards against a persisted member id that no longer belongs to this
  // Home's roster (the member left, was deleted, or the id was left over
  // from a different Home) — falls back to "Everyone" rather than leaving
  // the calendar silently filtered to a member that can never match again.
  // `members` starts empty until the first load resolves, so this only acts
  // once a real roster is in hand.
  useEffect(() => {
    if (!memberFilter || members.length === 0) return;
    const resolved = resolveMemberFilter(members, memberFilter);
    if (resolved !== memberFilter) chooseMember(resolved);
  }, [members, memberFilter, activeHomeId]);

  useEffect(() => {
    const stored = window.localStorage.getItem(VIEW_STORAGE) as ViewMode | null;
    if (stored && ["month", "week", "day", "agenda"].includes(stored))
      setView(stored);
    else setView("month");
  }, []);

  function chooseView(next: ViewMode) {
    if (next === "agenda" && view !== "agenda") {
      agendaEntryToken.current += 1;
      hasNavigated.current = true;
      setFocusDate(zonedToday(calendarTimezone));
    }
    setView(next);
    window.localStorage.setItem(VIEW_STORAGE, next);
  }

  const range = useMemo(() => {
    if (view === "month") return monthRange(focusDate);
    if (view === "week") return weekRange(focusDate);
    if (view === "day") return dayRange(focusDate);
    return agendaRange(focusDate);
  }, [focusDate, view]);

  const cells = useMemo(() => monthCells(focusDate), [focusDate]);

  // Month view renders 6 weeks (42 cells) padded with days from the adjacent months,
  // but `range` above is the exact calendar month (1st to last day) — a multi-day
  // event that starts in the trailing days of last month or ends in the leading days
  // of next month, yet is still visible in the padded grid, was never fetched at all.
  // Fetch the full padded range for month view specifically; other views are
  // unaffected.
  const fetchRange = useMemo(() => {
    if (view !== "month") return range;
    const start = cells[0]!;
    const end = new Date(cells[cells.length - 1]!);
    end.setUTCDate(end.getUTCDate() + 1);
    return { start, end };
  }, [view, range, cells]);

  const load = useCallback(async () => {
    if (!activeHomeId || !featureEnabled) return;
    const [labelRows, eventRows, memberRows, calendarRows, shares] = await Promise.all([
      api.listLabels(activeHomeId),
      api.listEvents(activeHomeId, {
        start_at: fetchRange.start.toISOString(),
        end_at: fetchRange.end.toISOString(),
        page_size: 300,
      }),
      api.members(activeHomeId).catch(() => []),
      api.listCalendars(activeHomeId).catch(() => null),
      api.sharedCalendars().catch(() => ({ items: [] })),
    ]);
    setLabels(labelRows);
    setMembers(memberRows);
    setHomeCalendars(calendarRows?.items ?? []);
    setSharedCalendars(shares.items);
    const primaryCalendar = calendarRows?.items.find((row) => row.is_primary);
    if (primaryCalendar) setCalendarTimezone(primaryCalendar.timezone);
    setPersonalCalendarId(calendarRows?.personal_calendar?.id ?? null);
    setPersonalCalendar(calendarRows?.personal_calendar ?? null);
    api
      .birthdays(activeHomeId)
      .then((response) => setBirthdays(response.items))
      .catch(() => setBirthdays([]));

    // Merge in every accepted external share's events for the same visible
    // range, tagged with where they came from — see EventOccurrence's
    // share_id/share_permission/shared_by_home_name docstring in
    // shared-types. Fetched regardless of the calendar-selector's hide/show
    // toggle (same "fetch everything, filter client-side" convention as
    // member/label filters — see filterByVisibleCalendars), so toggling
    // visibility back on never needs a fresh network round trip.
    const sharedEventLists = await Promise.all(
      shares.items.map((share) =>
        api
          .listSharedEvents(share.id, {
            start_at: fetchRange.start.toISOString(),
            end_at: fetchRange.end.toISOString(),
          })
          .then((response) =>
            response.items.map(
              (item): EventOccurrence => ({
                ...item,
                share_id: share.id,
                share_permission: share.permission,
                shared_by_home_name: share.source_group_name,
              }),
            ),
          )
          .catch(() => []),
      ),
    );
    setEvents([...eventRows.items, ...sharedEventLists.flat()]);
    // Widget event data may be stale after any create/update/delete that
    // routes through this loader (see widget-bridge.ts's own fetch, which
    // covers a wider date range than this page's visible window).
    void syncWidgetSnapshot();
  }, [activeHomeId, featureEnabled, fetchRange.end, fetchRange.start]);

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => setSharedEventsEnabled(billing.shared_events_enabled))
      .catch(() => setSharedEventsEnabled(false));
  }, [activeHomeId]);

  useEffect(() => {
    if (!activeHomeId) return;
    setFeatureChecked(false);
    api
      .featureMatrix(activeHomeId)
      .then((matrix) => {
        const enabled = matrix.features.some(
          (item) => item.feature === "calendar" && item.enabled,
        );
        setFeatureEnabled(enabled);
        setFeatureChecked(true);
        if (!enabled) router.replace("/home");
      })
      .catch(() => router.replace("/home"));
  }, [activeHomeId, router]);

  useEffect(() => {
    // Deep-linked from a reminder notification (?event=<id>) — open it directly rather
    // than requiring the user to find it in the calendar list. Independent of the
    // visible date range/view, since a reminder can point at an occurrence outside it.
    const deepLinkedEventId = searchParams.get("event");
    if (!activeHomeId || !deepLinkedEventId) return;
    api
      .eventDetail(activeHomeId, deepLinkedEventId)
      .then((detail) => openEvent(detail.event))
      .catch(() => {
        // The event may have been deleted since the reminder was sent — fail quietly,
        // the user just lands on the calendar with nothing pre-opened.
      });
  }, [activeHomeId, searchParams]);

  // Needed to evaluate the same "edit your own event" rule the backend
  // enforces (calendar.edit_own vs calendar.edit_all — see canEditEvent) —
  // Home.capabilities alone can't tell created-by-me apart from
  // created-by-someone-else.
  useEffect(() => {
    api
      .me()
      .then((user) => setCurrentUserId(user.id))
      .catch(() => setCurrentUserId(null));
  }, []);

  // Opening an existing event always starts in read-only View mode — Edit is
  // a separate, explicit action (see EventDetails/EventForm below). Routing
  // every "select an event" call site through this (rather than calling
  // setSelectedEvent directly) guarantees a freshly opened event can never
  // inherit a previous event's edit-mode state.
  function openEvent(event: EventOccurrence) {
    setSelectedEvent(event);
    setEditingSelected(false);
  }
  function closeEventSheet() {
    setSelectedEvent(null);
    setEditingSelected(false);
    setPendingEditPayload(null);
    setPendingDelete(false);
  }

  useEffect(() => {
    setError("");
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  // Calendars the signed-in user may create *new* events on, beyond their
  // own Home calendar/Personal calendar — offered in EventForm's Calendar
  // picker only when creating (see writableShares there). "view"-only
  // shares are deliberately excluded; per-event write authority is
  // re-checked server-side regardless (see calendar-utils.canEditSharedEvent).
  const writableShares = useMemo(
    () => sharedCalendars.filter((share) => share.permission === "manage"),
    [sharedCalendars],
  );

  const visibleEvents = useMemo(
    () =>
      filterByVisibleCalendars(
        filterVisibleEvents(events, memberFilter, labelFilter, query),
        hiddenCalendarIds,
      ),
    [events, memberFilter, labelFilter, query, hiddenCalendarIds],
  );
  const byDay = useMemo(
    () => groupEventsByDay(visibleEvents, calendarTimezone),
    [visibleEvents, calendarTimezone],
  );
  const memberNames = useMemo(
    () =>
      new Map(members.map((member) => [member.user_id, member.display_name])),
    [members],
  );
  const selectedMemberName = memberFilter
    ? (memberNames.get(memberFilter) ?? null)
    : null;
  const selectedLabelName = labelFilter
    ? (labels.find((label) => label.id === labelFilter)?.name ?? null)
    : null;
  const scheduleEmptyMessage = emptyStateMessage(
    selectedMemberName,
    selectedLabelName,
  );

  const agendaKeys = useMemo(
    () => Array.from(byDay.keys()).sort((left, right) => left.localeCompare(right)),
    [byDay],
  );
  const agendaTodayKey = dateKey(zonedToday(calendarTimezone));
  const agendaAnchorKey =
    agendaKeys.find((key) => key >= agendaTodayKey) ?? agendaKeys[0] ?? null;

  useEffect(() => {
    if (view !== "agenda" || positionedAgendaToken.current === agendaEntryToken.current) return;
    if (!agendaAnchorRef.current) return;
    positionedAgendaToken.current = agendaEntryToken.current;
    agendaAnchorRef.current.scrollIntoView({ block: "start", behavior: "auto" });
  }, [view, agendaAnchorKey, agendaEntryToken.current]);

  // Re-anchor to "today" (in the Home calendar's real timezone) once it's
  // known — but only until the user actually navigates; see hasNavigated.
  useEffect(() => {
    if (!hasNavigated.current) setFocusDate(zonedToday(calendarTimezone));
  }, [calendarTimezone]);

  function move(direction: -1 | 1) {
    hasNavigated.current = true;
    if (view === "month") {
      setFocusDate(addMonths(focusDate, direction));
      return;
    }
    const next = new Date(focusDate);
    if (view === "week") next.setUTCDate(next.getUTCDate() + direction * 7);
    else next.setUTCDate(next.getUTCDate() + direction);
    setFocusDate(next);
  }

  async function create(payload: EventPayload) {
    if (!activeHomeId) return;
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.createEvent(activeHomeId, payload);
      setEditorDay(null);
      setSelectedDay(null);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "We could not save your event.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createShared(shareId: string, payload: SharedEventPayload) {
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.createSharedEvent(shareId, payload);
      setEditorDay(null);
      setSelectedDay(null);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "We could not save your event.");
    } finally {
      setBusy(false);
    }
  }

  async function update(payload: EventPayload) {
    if (!activeHomeId || !selectedEvent) return;
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    // A recurring event owned by this Home offers occurrence/future/series
    // choices before anything is sent — hand off to the scope chooser
    // instead of mutating immediately. Shared-calendar events never reach
    // here (isRecurringOwnEvent excludes them) since their update endpoint
    // has no scope support yet.
    if (isRecurringOwnEvent(selectedEvent)) {
      setError("");
      setPendingEditPayload(payload);
      return;
    }
    setError("");
    setBusy(true);
    try {
      // An occurrence merged in from an externally shared calendar (see
      // load()) is never edited through the Home-scoped endpoint — the
      // viewer may have no Membership in that Home at all. Its own
      // share-scoped endpoint enforces "manage" permission independently
      // (see routers.calendar_sharing.update_shared_event); canEdit already
      // hid the Edit action entirely for a "view"-only share, this is the
      // request-shape branch, not a second permission check.
      const updated = selectedEvent.share_id
        ? await api.updateSharedEvent(
            selectedEvent.share_id,
            selectedEvent.event_id,
            toSharedEventUpdatePayload(payload, selectedEvent.updated_at),
          )
        : await api.updateEvent(
            activeHomeId,
            selectedEvent.event_id,
            toEventUpdatePayload(payload, selectedEvent.updated_at),
          );
      // Return to View mode showing the newly persisted values, rather than
      // closing the sheet — the freshly returned event (not a stale local
      // copy) is what View then renders.
      setSelectedEvent(
        selectedEvent.share_id
          ? {
              ...updated,
              share_id: selectedEvent.share_id,
              share_permission: selectedEvent.share_permission,
              shared_by_home_name: selectedEvent.shared_by_home_name,
            }
          : updated,
      );
      setEditingSelected(false);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "This event changed. Reload and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  // Runs the actual PATCH for a recurring event once the user has picked a
  // scope in the chooser. `occurrence_start` is always read from
  // `selectedEvent.occurrence_start` — the canonical identity — never
  // derived from `payload.start_at`, so re-editing an occurrence already
  // moved or overridden keeps updating the same exception row instead of
  // creating a new one at the (wrong) effective time.
  async function applyEventUpdate(payload: EventPayload, scope: EventMutationScope) {
    if (!activeHomeId || !selectedEvent) return;
    setError("");
    setScopeBusy(true);
    try {
      const updated = await api.updateEvent(
        activeHomeId,
        selectedEvent.event_id,
        toEventUpdatePayload(
          payload,
          selectedEvent.updated_at,
          scope,
          selectedEvent.occurrence_start,
        ),
      );
      setSelectedEvent(updated);
      setEditingSelected(false);
      setPendingEditPayload(null);
      await load();
    } catch (cause) {
      // Keep pendingEditPayload set so the chooser stays open with the
      // user's edits intact and they can retry — never silently fall back
      // to a different scope.
      setError(
        cause instanceof ApiError
          ? cause.message
          : "This event changed. Reload and try again.",
      );
    } finally {
      setScopeBusy(false);
    }
  }

  async function remove() {
    if (!activeHomeId || !selectedEvent) return;
    if (isRecurringOwnEvent(selectedEvent)) {
      setError("");
      setPendingDelete(true);
      return;
    }
    if (!window.confirm("Delete this event?")) return;
    try {
      if (selectedEvent.share_id) {
        await api.deleteSharedEvent(selectedEvent.share_id, selectedEvent.event_id);
      } else {
        await api.deleteEvent(activeHomeId, selectedEvent.event_id);
      }
      closeEventSheet();
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The event could not be deleted.",
      );
    }
  }

  // Runs the actual DELETE for a recurring event once the user has picked a
  // scope. Same canonical-identity rule as applyEventUpdate.
  async function applyDelete(scope: EventMutationScope) {
    if (!activeHomeId || !selectedEvent) return;
    setError("");
    setScopeBusy(true);
    try {
      await api.deleteEvent(
        activeHomeId,
        selectedEvent.event_id,
        scope,
        selectedEvent.occurrence_start,
      );
      setPendingDelete(false);
      closeEventSheet();
      await load();
    } catch (cause) {
      // Keep the event open/recoverable — pendingDelete stays true so the
      // chooser stays open and the user can retry.
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The event could not be deleted.",
      );
    } finally {
      setScopeBusy(false);
    }
  }

  function openDay(day: Date) {
    hasNavigated.current = true;
    setFocusDate(day);
    setSelectedDay(day);
  }

  if (!featureChecked || !featureEnabled) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Checking Calendar access...</p>
        </main>
      </AppShellContent>
    );
  }

  const focusedEvents = eventsForDay(visibleEvents, focusDate, calendarTimezone);
  const birthdaysInRange = birthdays.filter((entry) => {
    const occurrence = new Date(entry.next_occurrence_date);
    return occurrence >= range.start && occurrence < range.end;
  });

  return (
    <AppShellContent>
      <main className="standard-page calendar-page">
        <header className="calendar-toolbar-compact">
          <div className="calendar-month-row">
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(-1)}
              aria-label="Previous period"
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <h1 className="calendar-month-label">
              {view === "day"
                ? displayDate(focusDate, { weekday: "short", day: "numeric", month: "short" }, "UTC")
                : displayDate(focusDate, { month: "long", year: "numeric" }, "UTC")}
            </h1>
            <button
              className="icon-button secondary"
              type="button"
              onClick={() => move(1)}
              aria-label="Next period"
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
            <div className="calendar-month-row-actions">
              <button
                className="icon-button secondary"
                type="button"
                onClick={() => setFocusDate(zonedToday(calendarTimezone))}
                aria-label="Jump to today"
                title="Today"
              >
                <CalendarDays size={16} aria-hidden="true" />
              </button>
              <button
                className="icon-button secondary"
                type="button"
                onClick={() => setSearchOpen((open) => !open)}
                aria-pressed={searchOpen}
                aria-label="Search events"
              >
                <Search size={16} aria-hidden="true" />
              </button>
              {/* Pre-existing mislabel fixed alongside the Calendar Tag
                  rename: this always navigated to /calendar/calendars (Home
                  calendar management + sharing), never to the Calendar Tag
                  management screen (/settings/home) — the old "Manage event
                  categories" label just described the wrong destination. */}
              <Link
                className="icon-button secondary"
                href="/calendar/calendars"
                aria-label="Manage calendars"
                title="Manage calendars"
              >
                <Layers size={16} aria-hidden="true" />
              </Link>
              <button
                className="icon-button secondary"
                type="button"
                onClick={() => setCalendarSelectorOpen(true)}
                aria-label="Calendars"
                title="Calendars"
              >
                <Users size={16} aria-hidden="true" />
              </button>
              <button className="calendar-add-desktop" type="button" onClick={() => setEditorDay(focusDate)}>
                <Plus size={16} aria-hidden="true" />
                Add
              </button>
            </div>
          </div>

          <div className="calendar-selectors-row">
            <label className="calendar-selector">
              {/* The household member to view the calendar as — filters by the
                  canonical event-membership relationship (member_ids, backed by
                  CalendarEventMember), not by a CalendarEventLabel Calendar Tag.
                  "Everyone" (value "") applies no member filter. */}
              <span className="sr-only">Filter by household member</span>
              <select value={memberFilter} onChange={(event) => chooseMember(event.target.value)} aria-label="Filter by household member">
                <option value="">Everyone</option>
                {members.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.display_name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
            <label className="calendar-selector calendar-view-selector">
              <span className="sr-only">Calendar view</span>
              <select
                value={view}
                onChange={(event) => chooseView(event.target.value as ViewMode)}
                aria-label="Calendar view"
              >
                <option value="month">Month</option>
                <option value="week">Week</option>
                <option value="day">Day</option>
                <option value="agenda">Schedule</option>
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
          </div>

          {birthdaysInRange.length > 0 && (
            <p className="notice calendar-birthday-banner">
              🎂{" "}
              {birthdaysInRange
                .map(
                  (entry) =>
                    `${entry.display_name}'s birthday (${new Date(
                      entry.next_occurrence_date,
                    ).toLocaleDateString("en-GB", { day: "numeric", month: "short" })})`,
                )
                .join(" · ")}
            </p>
          )}

          {searchOpen && (
            <>
              <div className="calendar-search">
                <Search size={16} aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Search events"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  autoFocus
                  aria-label="Search events by title"
                />
                {query && (
                  <button
                    type="button"
                    className="icon-button secondary"
                    onClick={() => setQuery("")}
                    aria-label="Clear search"
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
              <div className="calendar-selectors-row">
                <label className="calendar-selector">
                  {/* This filters by CalendarEventLabel, user-facing "Calendar Tag" — a
                      free-form, unlimited tag (Family/School/Work/...), not a Calendar
                      (HomeCalendar) itself, and not the household-member filter above
                      even when a tag happens to share a member's name — see
                      docs/architecture/commercial-entitlements.md#commercial-plan-cleanup. */}
                  <span className="sr-only">Filter by Calendar Tag</span>
                  <select value={labelFilter} onChange={(event) => chooseLabel(event.target.value)} aria-label="Filter by Calendar Tag">
                    <option value="">{activeHome?.name ?? "Household"} calendar</option>
                    {labels.map((label) => <option key={label.id} value={label.id}>{label.name}</option>)}
                  </select>
                  <ChevronDown size={14} aria-hidden="true" />
                </label>
              </div>
            </>
          )}
        </header>

        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {view === "month" && (
          <MonthSwipeView
            cells={cells}
            events={visibleEvents}
            focusDate={focusDate}
            timeZone={calendarTimezone}
            onDay={openDay}
            onEvent={openEvent}
            onNavigate={move}
          />
        )}

        {view === "week" && (
          <section className="week-grid" aria-label="Week view">
            {Array.from({ length: 7 }, (_, index) => {
              const day = new Date(range.start);
              day.setUTCDate(day.getUTCDate() + index);
              const dayEvents = eventsForDay(visibleEvents, day, calendarTimezone);
              return (
                <article
                  className={
                    dateKey(day) === zonedDateKey(new Date(), calendarTimezone)
                      ? "today"
                      : ""
                  }
                  key={dateKey(day)}
                >
                  <button
                    className="week-day-heading"
                    type="button"
                    onClick={() => openDay(day)}
                  >
                    <span>{displayDate(day, { weekday: "short" }, "UTC")}</span>
                    <strong>{day.getUTCDate()}</strong>
                  </button>
                  <EventList
                    events={dayEvents}
                    members={members}
                    memberNames={memberNames}
                    timeZone={calendarTimezone}
                    onSelect={openEvent}
                    compact
                  />
                </article>
              );
            })}
          </section>
        )}

        {view === "day" && (
          <section className="day-view card" aria-label="Day view">
            <EventList
              events={focusedEvents}
              members={members}
              memberNames={memberNames}
              timeZone={calendarTimezone}
                    onSelect={openEvent}
            />
          </section>
        )}

        {view === "agenda" && (
          <section className="agenda-view" aria-label="Upcoming events">
            {visibleEvents.length === 0 ? (
              <p className="card hint">{scheduleEmptyMessage}</p>
            ) : (
              Array.from(byDay.entries())
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, rows]) => (
                  <article
                    className="agenda-day"
                    key={key}
                    ref={key === agendaAnchorKey ? agendaAnchorRef : undefined}
                  >
                    <h2>{relativeDayHeading(key, calendarTimezone)}</h2>
                    <EventList
                      events={rows}
                      members={members}
                      memberNames={memberNames}
                      timeZone={calendarTimezone}
                    onSelect={openEvent}
                    />
                  </article>
                ))
            )}
          </section>
        )}

        <button
          className="calendar-fab"
          type="button"
          onClick={() => setEditorDay(focusDate)}
          aria-label="Add calendar event"
        >
          +
        </button>

        {selectedDay && (
          <BottomSheet
            title={displayDate(
              selectedDay,
              { weekday: "long", day: "numeric", month: "long" },
              "UTC",
            )}
            onDismiss={() => setSelectedDay(null)}
          >
            <EventList
              events={eventsForDay(visibleEvents, selectedDay, calendarTimezone)}
              members={members}
              memberNames={memberNames}
              timeZone={calendarTimezone}
              onSelect={(event) => {
                setSelectedDay(null);
                openEvent(event);
              }}
            />
            <button
              className="sheet-primary"
              type="button"
              onClick={() => {
                setEditorDay(selectedDay);
                setSelectedDay(null);
              }}
            >
              Add event on this day
            </button>
          </BottomSheet>
        )}

        {calendarSelectorOpen && (
          <BottomSheet title="Calendars" onDismiss={() => setCalendarSelectorOpen(false)}>
            <div className="calendar-visibility-list">
              <div className="calendar-visibility-group">
                <span className="eyebrow calendar-visibility-heading">My calendars</span>
                {[...homeCalendars, ...(personalCalendar ? [personalCalendar] : [])].map(
                  (calendar) => {
                    const name = calendar.owner_user_id ? "Personal calendar" : calendar.name;
                    const visible = !hiddenCalendarIds.has(calendar.id);
                    return (
                      <label className="calendar-visibility-row" key={calendar.id}>
                        <span
                          className="colour-dot calendar-visibility-dot"
                          style={
                            { "--swatch-colour": resolveColour(calendar.color) } as React.CSSProperties
                          }
                          aria-hidden="true"
                        />
                        <span className="calendar-visibility-name">
                          <span className="calendar-visibility-name-primary">{name}</span>
                        </span>
                        <input
                          className="switch"
                          type="checkbox"
                          role="switch"
                          checked={visible}
                          aria-checked={visible}
                          onChange={() => toggleCalendarVisibility(calendar.id)}
                          aria-label={`Show ${name}`}
                        />
                      </label>
                    );
                  },
                )}
              </div>

              {sharedCalendars.length > 0 && (
                <div className="calendar-visibility-group">
                  <span className="eyebrow calendar-visibility-heading">Shared with you</span>
                  {sharedCalendars.map((share) => {
                    const visible = !hiddenCalendarIds.has(share.id);
                    return (
                      <label className="calendar-visibility-row" key={share.id}>
                        <span
                          className="colour-dot calendar-visibility-dot"
                          style={
                            {
                              "--swatch-colour": resolveColour(share.calendar_color ?? "teal"),
                            } as React.CSSProperties
                          }
                          aria-hidden="true"
                        />
                        <span className="calendar-visibility-name">
                          <span className="calendar-visibility-name-primary">
                            {share.calendar_name}
                          </span>
                          <small>{share.source_group_name}</small>
                        </span>
                        <input
                          className="switch"
                          type="checkbox"
                          role="switch"
                          checked={visible}
                          aria-checked={visible}
                          onChange={() => toggleCalendarVisibility(share.id)}
                          aria-label={`Show ${share.calendar_name}, shared by ${share.source_group_name}`}
                        />
                      </label>
                    );
                  })}
                </div>
              )}

              <Link
                className="button secondary calendar-visibility-manage-link"
                href="/calendar/shared"
                onClick={() => setCalendarSelectorOpen(false)}
              >
                Manage sharing
              </Link>
            </div>
          </BottomSheet>
        )}

        {editorDay && (
          <BottomSheet
            title="Add event"
            onDismiss={() => setEditorDay(null)}
            fullHeight
          >
            <EventForm
              labels={labels}
              homeCalendars={homeCalendars}
              members={members}
              initialDay={editorDay}
              timeZone={calendarTimezone}
              personalCalendarId={personalCalendarId}
              writableShares={writableShares}
              busy={busy}
              submitLabel="Save event"
              sharedEventsEnabled={sharedEventsEnabled}
              onSubmit={create}
              onSubmitShared={createShared}
              onCancel={() => setEditorDay(null)}
            />
          </BottomSheet>
        )}

        {selectedEvent && !pendingEditPayload && !pendingDelete && (() => {
          // An occurrence merged in from an externally shared calendar has
          // its own authority (CalendarShare.permission), independent of —
          // and usually entirely absent from — the viewer's Home
          // capabilities (see canEditSharedEvent/canDeleteSharedEvent's
          // docstring in calendar-utils.ts).
          const canEdit = selectedEvent.share_id
            ? canEditSharedEvent(selectedEvent)
            : canEditEvent(activeHome?.capabilities ?? [], selectedEvent, currentUserId);
          const canDelete = selectedEvent.share_id
            ? canDeleteSharedEvent(selectedEvent)
            : canDeleteEvent(activeHome?.capabilities ?? []);
          return (
            <BottomSheet
              title={editingSelected ? "Edit event" : selectedEvent.title}
              onDismiss={closeEventSheet}
              headerAction={
                !editingSelected && canEdit ? (
                  <button
                    className="tertiary"
                    type="button"
                    onClick={() => setEditingSelected(true)}
                  >
                    Edit
                  </button>
                ) : undefined
              }
              fullHeight
            >
              {editingSelected ? (
                <EventForm
                  labels={labels}
                  homeCalendars={homeCalendars}
                  members={members}
                  initial={selectedEvent}
                  initialDay={new Date(selectedEvent.start_at)}
                  timeZone={calendarTimezone}
                  personalCalendarId={personalCalendarId}
                  busy={busy}
                  submitLabel="Save changes"
                  sharedEventsEnabled={sharedEventsEnabled}
                  onSubmit={update}
                  onCancel={() => setEditingSelected(false)}
                  onDelete={canDelete ? remove : undefined}
                />
              ) : (
                <EventDetails
                  event={selectedEvent}
                  members={members}
                  timeZone={calendarTimezone}
                  personalCalendarId={personalCalendarId}
                  homeName={activeHome?.name ?? "Home calendar"}
                  canDelete={canDelete}
                  onDelete={remove}
                  busy={busy}
                />
              )}
            </BottomSheet>
          );
        })()}

        {selectedEvent && pendingEditPayload && (
          <RecurrenceScopeSheet
            mode="edit"
            busy={scopeBusy}
            error={error}
            onCancel={() => {
              setPendingEditPayload(null);
              setError("");
            }}
            onChoose={(scope) => applyEventUpdate(pendingEditPayload, scope)}
          />
        )}

        {selectedEvent && pendingDelete && (
          <RecurrenceScopeSheet
            mode="delete"
            busy={scopeBusy}
            error={error}
            onCancel={() => {
              setPendingDelete(false);
              setError("");
            }}
            onChoose={(scope) => applyDelete(scope)}
          />
        )}
      </main>
    </AppShellContent>
  );
}

function EventList({
  events,
  members,
  memberNames,
  timeZone,
  onSelect,
  compact = false,
}: {
  events: EventOccurrence[];
  members: Member[];
  memberNames: Map<string, string>;
  timeZone: string;
  onSelect: (event: EventOccurrence) => void;
  compact?: boolean;
}) {
  if (!events.length) return <p className="hint">No events</p>;
  return (
    <div className={`event-list${compact ? " compact" : ""}`}>
      {events.map((event) => {
        const people = event.member_ids
          .map((id) => memberNames.get(id))
          .filter(Boolean);
        const participants = participantsForEvent(members, event.member_ids);
        return (
          <button
            className="event-row"
            type="button"
            key={event.occurrence_id}
            onClick={() => onSelect(event)}
          >
            <span
              className="event-colour"
              style={{ background: resolveColour(event.label?.color ?? event.calendar_color) }}
              aria-label={event.label?.name ?? "Home calendar"}
            />
            <span className="event-time">{eventTime(event, timeZone)}</span>
            <span className="event-copy">
              <strong>
                {event.title}
                {event.shared_by_home_name && (
                  <span
                    className="shared-calendar-badge"
                    title={`Shared by ${event.shared_by_home_name}`}
                  >
                    <Users size={12} aria-hidden="true" />
                  </span>
                )}
              </strong>
              <small>
                {[
                  people.join(", "),
                  event.label?.name,
                  event.location_text,
                  event.reminder_minutes !== null ? "Reminder set" : "",
                  event.shared_by_home_name ? `Shared by ${event.shared_by_home_name}` : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </span>
            <AvatarStack people={participants} size="sm" />
          </button>
        );
      })}
    </div>
  );
}
