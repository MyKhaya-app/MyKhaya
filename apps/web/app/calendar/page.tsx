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
  Trash2,
  X,
} from "lucide-react";
import type {
  BirthdayEntry,
  EventLabel,
  EventOccurrence,
  EventPayload,
  Member,
  RecurrencePattern,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { resolveColour } from "@mykhaya/design-tokens";
import { AppShell } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { AvatarStack } from "@/components/avatar";
import { participantsForEvent } from "@/components/avatar-stack-logic";
import { BottomSheet } from "@/components/bottom-sheet";
import { useActiveHome } from "@/components/use-active-home";
import {
  agendaRange,
  applyAllDayToggle,
  canDeleteEvent,
  canEditEvent,
  computeInitialWhen,
  DEFAULT_EVENT_DURATION_MINUTES,
  dateKey,
  dayRange,
  emptyStateMessage,
  eventDateBounds,
  eventsForDay,
  FALLBACK_TIMEZONE,
  filterVisibleEvents,
  groupEventsByDay,
  monthCells,
  monthRange,
  parseLocalInputValue,
  resolveMemberFilter,
  shiftEndWithStart,
  splitZoned,
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
function displayDate(
  value: Date | string,
  options: Intl.DateTimeFormatOptions,
  timeZone: string,
) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    ...options,
  }).format(typeof value === "string" ? new Date(value) : value);
}

function eventTime(event: EventOccurrence, timeZone: string) {
  if (event.is_all_day) return "All day";
  return displayDate(
    event.start_at,
    { hour: "2-digit", minute: "2-digit" },
    event.timezone || timeZone,
  );
}

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

// Sentinel select value for "Personal calendar" — distinct from any real
// label UUID, so the single "Calendar or category" control can represent
// both concepts (which HomeCalendar the event belongs to, and which
// CalendarEventLabel it's tagged with) without them ever colliding. Never
// sent to the API as-is; submit() translates it into calendar_id.
const PERSONAL_CALENDAR_VALUE = "__personal__";

function EventForm({
  labels,
  members,
  initial,
  initialDay,
  timeZone,
  personalCalendarId,
  busy,
  submitLabel,
  sharedEventsEnabled,
  onSubmit,
  onCancel,
  onDelete,
}: {
  labels: EventLabel[];
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
  busy: boolean;
  submitLabel: string;
  sharedEventsEnabled: boolean;
  onSubmit: (payload: EventPayload) => Promise<void>;
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
  // See WhenState.hasTimedValues — a ref, not state, because flipping it
  // must never itself trigger a render; it only gates what onToggleAllDay
  // does the next time the user actually turns All day off.
  const hasTimedValues = useRef(initialWhen.hasTimedValues);
  // The "Calendar or category" select's value — either a real
  // CalendarEventLabel id (unchanged existing behaviour), "" (the existing
  // default/no-label option), or PERSONAL_CALENDAR_VALUE. Controlled (not
  // read from FormData like the rest of this form) so the "Only you can
  // see..." supporting copy can react live to the current selection.
  const [calendarSelection, setCalendarSelection] = useState(() =>
    initial && personalCalendarId && initial.calendar_id === personalCalendarId
      ? PERSONAL_CALENDAR_VALUE
      : (initial?.label?.id ?? ""),
  );

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

    const isPersonal = calendarSelection === PERSONAL_CALENDAR_VALUE;
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
      // checked from before switching to Personal calendar).
      member_ids: isPersonal ? [] : data.getAll("members").map(String),
      label_id: isPersonal ? null : calendarSelection || null,
      calendar_id: isPersonal ? personalCalendarId : null,
      location_text: formText(data, "location") || null,
      reminder_minutes: formText(data, "reminder")
        ? Number(formText(data, "reminder"))
        : null,
      recurrence: (formText(data, "recurrence") || "none") as RecurrencePattern,
      recurrence_interval: 1,
      recurrence_until: null,
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
          People section to offer while it's selected. */}
      {members.length > 0 && calendarSelection !== PERSONAL_CALENDAR_VALUE && (
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
      <label className="form-wide icon-row">
        <span className="icon-row-icon" aria-hidden="true">
          <Layers size={16} />
        </span>
        <span className="sr-only">Calendar or category</span>
        <select
          className="icon-row-control"
          name="label"
          value={calendarSelection}
          onChange={(event) => setCalendarSelection(event.target.value)}
        >
          <option value="">Home calendar</option>
          {personalCalendarId && (
            <option value={PERSONAL_CALENDAR_VALUE}>Personal calendar</option>
          )}
          {labels.map((label) => {
            // Transition-safe, matching update_event's own check: a category
            // already assigned to this event stays selectable (so resaving
            // never breaks), but a different, over-the-plan-limit category
            // preserved past a downgrade can't be newly assigned.
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
      {calendarSelection === PERSONAL_CALENDAR_VALUE && (
        <p className="form-wide quiet-state">Only you can see events in this calendar.</p>
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
              defaultValue={initial?.recurrence ?? "none"}
            >
              <option value="none">Does not repeat</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
              <option value="weekdays">Weekdays</option>
            </select>
          </label>
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
        <button className="danger-link" type="button" onClick={onDelete}>
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
  canDelete,
  onDelete,
}: {
  event: EventOccurrence;
  members: Member[];
  timeZone: string;
  personalCalendarId: string | null;
  canDelete: boolean;
  onDelete: () => Promise<void>;
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
            style={
              { "--swatch-colour": resolveColour(event.label?.color ?? event.calendar_color) } as React.CSSProperties
            }
            aria-hidden="true"
          />
          {personalCalendarId && event.calendar_id === personalCalendarId
            ? "Personal calendar"
            : (event.label?.name ?? "Home calendar")}
        </div>
      </div>

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
          <button className="danger-link" type="button" onClick={onDelete}>
            <Trash2 size={16} aria-hidden="true" />
            Delete event
          </button>
        </div>
      )}
    </div>
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
    const [labelRows, eventRows, memberRows, calendarRows] = await Promise.all([
      api.listLabels(activeHomeId),
      api.listEvents(activeHomeId, {
        start_at: fetchRange.start.toISOString(),
        end_at: fetchRange.end.toISOString(),
        page_size: 300,
      }),
      api.members(activeHomeId).catch(() => []),
      api.listCalendars(activeHomeId).catch(() => null),
    ]);
    setLabels(labelRows);
    setEvents(eventRows.items);
    setMembers(memberRows);
    const primaryCalendar = calendarRows?.items.find((row) => row.is_primary);
    if (primaryCalendar) setCalendarTimezone(primaryCalendar.timezone);
    setPersonalCalendarId(calendarRows?.personal_calendar?.id ?? null);
    api
      .birthdays(activeHomeId)
      .then((response) => setBirthdays(response.items))
      .catch(() => setBirthdays([]));
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
  }

  useEffect(() => {
    setError("");
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  const visibleEvents = useMemo(
    () => filterVisibleEvents(events, memberFilter, labelFilter, query),
    [events, memberFilter, labelFilter, query],
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
    const next = new Date(focusDate);
    if (view === "month") next.setUTCMonth(next.getUTCMonth() + direction);
    else if (view === "week")
      next.setUTCDate(next.getUTCDate() + direction * 7);
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

  async function update(payload: EventPayload) {
    if (!activeHomeId || !selectedEvent) return;
    if (new Date(payload.end_at) <= new Date(payload.start_at)) {
      setError("End must be after start.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const updated = await api.updateEvent(activeHomeId, selectedEvent.event_id, {
        ...payload,
        expected_updated_at: selectedEvent.updated_at,
      });
      // Return to View mode showing the newly persisted values, rather than
      // closing the sheet — the freshly returned event (not a stale local
      // copy) is what View then renders.
      setSelectedEvent(updated);
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

  async function remove() {
    if (
      !activeHomeId ||
      !selectedEvent ||
      !window.confirm("Delete this event?")
    )
      return;
    try {
      await api.deleteEvent(activeHomeId, selectedEvent.event_id);
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

  function openDay(day: Date) {
    hasNavigated.current = true;
    setFocusDate(day);
    setSelectedDay(day);
  }

  if (!featureChecked || !featureEnabled) {
    return (
      <AppShell>
        <main className="standard-page">
          <p role="status">Checking Calendar access...</p>
        </main>
      </AppShell>
    );
  }

  const focusedEvents = eventsForDay(visibleEvents, focusDate, calendarTimezone);
  const birthdaysInRange = birthdays.filter((entry) => {
    const occurrence = new Date(entry.next_occurrence_date);
    return occurrence >= range.start && occurrence < range.end;
  });

  return (
    <AppShell>
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
              <Link
                className="icon-button secondary"
                href="/calendar/calendars"
                aria-label="Manage event categories"
                title="Event categories"
              >
                <Layers size={16} aria-hidden="true" />
              </Link>
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
                  CalendarEventMember), not by a CalendarEventLabel category.
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
                  {/* This filters by CalendarEventLabel — a free-form, unlimited event
                      tag (Family/School/Work/...), not the commercial "event category"
                      (HomeCalendar) concept limited by calendar.max_categories, and not
                      the household-member filter above even when a label happens to
                      share a member's name — see
                      docs/architecture/commercial-entitlements.md#commercial-plan-cleanup. */}
                  <span className="sr-only">Filter by category</span>
                  <select value={labelFilter} onChange={(event) => chooseLabel(event.target.value)} aria-label="Filter by category">
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
          <MonthView
            cells={cells}
            events={visibleEvents}
            focusDate={focusDate}
            timeZone={calendarTimezone}
            onDay={openDay}
            onEvent={openEvent}
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

        {editorDay && (
          <BottomSheet
            title="Add event"
            onDismiss={() => setEditorDay(null)}
            fullHeight
          >
            <EventForm
              labels={labels}
              members={members}
              initialDay={editorDay}
              timeZone={calendarTimezone}
              personalCalendarId={personalCalendarId}
              busy={busy}
              submitLabel="Save event"
              sharedEventsEnabled={sharedEventsEnabled}
              onSubmit={create}
              onCancel={() => setEditorDay(null)}
            />
          </BottomSheet>
        )}

        {selectedEvent && (() => {
          const canEdit = canEditEvent(
            activeHome?.capabilities ?? [],
            selectedEvent,
            currentUserId,
          );
          const canDelete = canDeleteEvent(activeHome?.capabilities ?? []);
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
                  canDelete={canDelete}
                  onDelete={remove}
                />
              )}
            </BottomSheet>
          );
        })()}
      </main>
    </AppShell>
  );
}

// Show at most this many event bars per week before collapsing the rest into a
// "+N more" indicator — a week with nothing more than this stays compact instead of
// reserving space for events it doesn't have.
const MONTH_VISIBLE_ROW_CAP = 3;

function MonthView({
  cells,
  events,
  focusDate,
  timeZone,
  onDay,
  onEvent,
}: {
  cells: Date[];
  events: EventOccurrence[];
  focusDate: Date;
  timeZone: string;
  onDay: (day: Date) => void;
  onEvent: (event: EventOccurrence) => void;
}) {
  const todayKey = zonedDateKey(new Date(), timeZone);
  const bounds = useMemo(
    () => new Map(events.map((event) => [event.occurrence_id, eventDateBounds(event, timeZone)])),
    [events, timeZone],
  );
  return (
    <section className="calendar-month" aria-label="Month view">
      <div className="calendar-weekdays" aria-hidden="true">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label) => <span key={label}>{label}</span>)}
      </div>
      <div className="calendar-weeks">
        {Array.from({ length: 6 }, (_, weekIndex) => {
          const days = cells.slice(weekIndex * 7, weekIndex * 7 + 7);
          const weekStart = dateKey(days[0]!);
          const weekEnd = dateKey(days[6]!);
          const rows: { event: EventOccurrence; start: number; end: number; row: number }[] = [];
          const rowIntervals: { start: number; end: number }[][] = [];
          events
            .filter((event) => {
              const { startKey, endKey } = bounds.get(event.occurrence_id)!;
              return endKey >= weekStart && startKey <= weekEnd;
            })
            .sort((a, b) => bounds.get(a.occurrence_id)!.startKey.localeCompare(bounds.get(b.occurrence_id)!.startKey) || a.title.localeCompare(b.title))
            .forEach((event) => {
              const { startKey, endKey } = bounds.get(event.occurrence_id)!;
              const start = Math.max(0, days.findIndex((day) => dateKey(day) >= startKey));
              const end = Math.min(6, days.reduce((last, day, index) => dateKey(day) <= endKey ? index : last, -1));
              if (end < start) return;
              let row = rowIntervals.findIndex((intervals) => intervals.every((interval) => end < interval.start || start > interval.end));
              if (row === -1) row = rowIntervals.length;
              (rowIntervals[row] ??= []).push({ start, end });
              rows.push({ event, start, end, row });
            });
          const hiddenByDay = days.map((day) => rows.filter((item) => item.row >= MONTH_VISIBLE_ROW_CAP && item.start <= days.indexOf(day) && item.end >= days.indexOf(day)).length);
          // The whole point: a week with 0-1 events only reserves 0-1 event-row
          // tracks, not a fixed 4-row block every week gets regardless of content.
          const visibleRowCount = Math.min(rowIntervals.length, MONTH_VISIBLE_ROW_CAP);
          return (
            <div
              className="calendar-week"
              key={weekStart}
              style={{ gridTemplateRows: `var(--month-day-number-h) repeat(${visibleRowCount}, var(--month-event-row-h))` }}
            >
              {days.map((day, index) => {
                const key = dateKey(day);
                const count = events.filter((event) => {
                  const { startKey, endKey } = bounds.get(event.occurrence_id)!;
                  return startKey <= key && endKey >= key;
                }).length;
                const hidden = hiddenByDay[index] ?? 0;
                return (
                  <article
                    className={`calendar-day${key === todayKey ? " today" : ""}${day.getUTCMonth() !== focusDate.getUTCMonth() ? " outside" : ""}${index === 6 ? " sunday" : ""}`}
                    key={key}
                    style={{ gridColumn: index + 1, gridRow: "1 / -1" }}
                  >
                    <button className="day-number" type="button" onClick={() => onDay(day)} aria-label={`${displayDate(day, { weekday: "long", day: "numeric", month: "long", year: "numeric" }, "UTC")}, ${count} events`}>
                      <span>{day.getUTCDate()}</span>
                    </button>
                    {hidden > 0 && <button className="overflow-events" type="button" onClick={() => onDay(day)}>+{hidden} more</button>}
                  </article>
                );
              })}
              {rows.filter((item) => item.row < MONTH_VISIBLE_ROW_CAP).map(({ event, start, end, row }) => {
                // A multi-day event keeps the same solid-bar treatment on every week
                // segment it touches, even a segment that only covers one day of that
                // week (e.g. an event ending on a week's first day) — styling must key
                // off the event's own duration, not how much of it happens to fall in
                // this particular week, or a continuation segment would silently revert
                // to the lighter single-day chip look and read as a different event.
                const { startKey, endKey } = bounds.get(event.occurrence_id)!;
                const isMultiDay = endKey !== startKey;
                const segmentDays = end - start + 1;
                const isContinuation = startKey < weekStart;
                // A segment too narrow for its title to read as anything but a
                // meaningless fragment ("Te…", "0…") shows no text at all — a blank
                // coloured bar still communicates "this event continues here," which a
                // squeezed fragment does not.
                const showTitle = !isMultiDay || segmentDays >= 2;
                return (
                  <button
                    key={`${event.occurrence_id}-${weekStart}`}
                    type="button"
                    className={`month-event${isMultiDay ? " month-event-span" : ""}`}
                    style={
                      {
                        "--event-color": resolveColour(event.label?.color ?? event.calendar_color),
                        gridColumn: `${start + 1} / ${end + 2}`,
                        gridRow: row + 2,
                      } as React.CSSProperties
                    }
                    onClick={() => onEvent(event)}
                    aria-label={`${eventTime(event, timeZone)} ${event.title}`}
                    title={event.title}
                  >
                    {!isMultiDay && <span aria-hidden="true" />}
                    {showTitle ? `${isContinuation ? "↳ " : ""}${event.title}` : ""}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
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
              <strong>{event.title}</strong>
              <small>
                {[people.join(", "), event.label?.name, event.location_text, event.reminder_minutes !== null ? "Reminder set" : ""]
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
