import type { EventOccurrence, Member } from "@mykhaya/shared-types";

// Last-resort fallback only — used when no Home calendar timezone has loaded
// yet (e.g. the very first render before the API responds). Matches the
// backend's own HomeCalendar.timezone ORM default, so it's never a source of
// drift once real data arrives; it must never be treated as "the" timezone.
export const FALLBACK_TIMEZONE = "Europe/London";

// ---------------------------------------------------------------------------
// Timed events vs all-day events are two different concepts and must never
// be converted into one another by reinterpreting the other's storage
// representation:
//
// - A TIMED event is an instant with timezone semantics: e.g.
//   "2026-08-20T08:30:00Z" + "Europe/London" means "09:30 local" — see
//   zonedTimeToUtc/utcToZonedInputValue below, the only functions that ever
//   convert between an instant and a wall-clock time in a real IANA zone.
// - An ALL-DAY event is a calendar-date *range*, with UTC-midnight instants
//   used purely as a storage/API convention (see dateKey/eventDateBounds,
//   and the backend's `_all_day_midnight`). Its start_at/end_at must only
//   ever be read with plain UTC digits — running an all-day boundary through
//   zonedTimeToUtc/utcToZonedInputValue would reinterpret "this is calendar
//   date 20 Aug" as "this is 00:00Z", which during BST displays as 01:00
//   local: a real time-of-day that was never entered by anyone and carries
//   no meaningful intent. Toggling an event between All day and timed must
//   establish a fresh, sensible clock value (see DEFAULT_EVENT_START_TIME
//   below and EventForm's computeInitialWhen/onToggleAllDay in page.tsx),
//   never derive one from the other representation's boundary.
export const DEFAULT_EVENT_START_HOUR = 9;
function pad2(value: number): string {
  return String(value).padStart(2, "0");
}
// The sensible, deterministic wall-clock default a fresh timed Start/End
// gets — for a brand-new event, and for a persisted all-day event that has
// never had a meaningful clock value established in this editing session.
// Kept as plain "HH:mm" strings (not derived via any instant/timezone
// conversion) since establishing a *new* default clock value is exactly the
// case where no real instant exists yet to convert from.
export const DEFAULT_EVENT_START_TIME = `${pad2(DEFAULT_EVENT_START_HOUR)}:00`;

export function dateKey(value: Date | string): string {
  return (typeof value === "string" ? value : value.toISOString()).slice(0, 10);
}

export function monthRange(base: Date) {
  return {
    start: new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1)),
    end: new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 1)),
  };
}

export function weekRange(base: Date) {
  const offset = (base.getUTCDay() + 6) % 7;
  const start = new Date(
    Date.UTC(
      base.getUTCFullYear(),
      base.getUTCMonth(),
      base.getUTCDate() - offset,
    ),
  );
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 7);
  return { start, end };
}

export function dayRange(base: Date) {
  const start = new Date(
    Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate()),
  );
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 1);
  return { start, end };
}

export function agendaRange(base: Date) {
  // Anchored to the start of the browsed month (same as monthRange) rather than
  // `base` itself, so Schedule always covers at least everything Month view shows
  // for the period the user is looking at — switching Month -> Schedule must not
  // silently drop events that are still within the visible month just because
  // they fall before "today" (or before `base`'s exact day). The +45 day
  // extension keeps the "look ahead" agenda behaviour beyond the current month.
  const start = monthRange(base).start;
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 45);
  return { start, end };
}

export function monthCells(base: Date): Date[] {
  const start = monthRange(base).start;
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setUTCDate(day.getUTCDate() + index);
    return day;
  });
}

// ---------------------------------------------------------------------------
// Timezone-aware instant <-> wall-clock conversion.
//
// The calendar grid (monthCells/monthRange/etc. above) works with plain
// UTC-midnight-anchored Date objects purely as *calendar date labels* — that
// needs no timezone, a calendar date is a calendar date. But an event's
// start_at/end_at from the API are real UTC instants, and turning those into
// "what day/time does a person actually see" requires knowing which IANA
// timezone governs that event (CalendarEvent.timezone, normally inherited
// from the Home's primary calendar) — never the server's or the browser's
// own timezone. These helpers are the single place that conversion happens;
// every display/bucketing function below and the event picker in page.tsx
// both go through them, so there is exactly one implementation of "instant
// <-> local wall clock in an IANA zone" in the whole app.
// ---------------------------------------------------------------------------

interface ZonedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

function zonedParts(date: Date, timeZone: string): ZonedParts {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const raw: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== "literal") raw[part.type] = part.value;
  }
  return {
    year: Number(raw.year),
    month: Number(raw.month),
    day: Number(raw.day),
    hour: Number(raw.hour),
    minute: Number(raw.minute),
    second: Number(raw.second),
  };
}

/** The calendar date (YYYY-MM-DD) a real instant falls on for someone in
 *  `timeZone` — e.g. an event just before local midnight can be "tomorrow"
 *  in UTC but still "today" locally, and vice versa. Used for day-bucketing
 *  timed events; all-day events use `dateKey` directly instead (see
 *  `occurrenceDateKey`) since they're stored as literal UTC-midnight calendar
 *  dates that must never be re-localized. */
export function zonedDateKey(value: Date | string, timeZone: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const { year, month, day } = zonedParts(date, timeZone);
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** "Today" as a UTC-midnight-anchored calendar-date placeholder Date, per
 *  the calendar's own timezone — never the browser's local "now". The
 *  calendar grid (monthRange/monthCells/weekRange/dayRange/move()) works
 *  entirely in UTC-digit calendar-date arithmetic on top of a cursor like
 *  this one; what must be timezone-correct is *which* calendar date "today"
 *  names, not the arithmetic itself. */
export function zonedToday(timeZone: string): Date {
  const { year, month, day } = zonedParts(new Date(), timeZone);
  return new Date(Date.UTC(year, month - 1, day));
}

/** Converts a wall-clock date/time as seen in `timeZone` (e.g. "14 Aug 2026,
 *  09:30 Europe/London") to the real UTC instant it names. Handles DST via a
 *  standard guess-and-correct pass: an initial UTC guess is re-localized,
 *  the mismatch against the requested wall-clock fields becomes a
 *  correction, and a second pass converges even across a transition. If the
 *  requested wall-clock time is nonexistent (the "spring forward" gap) or
 *  ambiguous (the "fall back" repeated hour), the loop settles on whichever
 *  side of the transition the platform's IANA data resolves to — a
 *  deterministic, documented choice rather than silent corruption. */
export function zonedTimeToUtc(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): Date {
  const targetAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0);
  let utcGuess = targetAsUtc;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const zoned = zonedParts(new Date(utcGuess), timeZone);
    const zonedAsUtc = Date.UTC(
      zoned.year,
      zoned.month - 1,
      zoned.day,
      zoned.hour,
      zoned.minute,
      zoned.second,
    );
    const diff = targetAsUtc - zonedAsUtc;
    if (diff === 0) break;
    utcGuess += diff;
  }
  return new Date(utcGuess);
}

/** The inverse of `zonedTimeToUtc`, formatted for a `<input type="datetime-
 *  local">` value: the wall-clock digits a person in `timeZone` would read
 *  off a clock at this real instant — e.g. an 08:30Z instant during British
 *  Summer Time renders as "09:30", never "08:30". */
export function utcToZonedInputValue(
  value: Date | string,
  timeZone: string,
): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const { year, month, day, hour, minute } = zonedParts(date, timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}`;
}

/** Splits a `zonedTimeToUtc`-ready instant into the separate `date`
 *  ("YYYY-MM-DD") and `time` ("HH:mm") strings the combined picker's native
 *  `<input type="date">`/`<input type="time">` fields need, always read in
 *  `timeZone` (never the browser's own local zone). Only ever call this on a
 *  TIMED event's real instant — see the timed-vs-all-day comment block
 *  above; an all-day boundary must go through `dateKey` instead. */
export function splitZoned(
  instant: Date,
  timeZone: string,
): { date: string; time: string } {
  const [date, time] = utcToZonedInputValue(instant, timeZone).split("T");
  return { date: date ?? "", time: time ?? "00:00" };
}

/** Parses a `<input type="datetime-local">` value's literal digits (never
 *  through `new Date(string)`, which the browser would reinterpret as *its
 *  own* local timezone) into the components `zonedTimeToUtc` expects. */
export function parseLocalInputValue(value: string): {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
} {
  const [datePart, timePart = "00:00"] = value.split("T");
  const [year, month, day] = (datePart ?? "").split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  return {
    year: year ?? 1970,
    month: month ?? 1,
    day: day ?? 1,
    hour: hour ?? 0,
    minute: minute ?? 0,
  };
}

// The calendar date an occurrence's start/end boundary falls on, for day-
// bucketing purposes. All-day events are literal UTC-midnight calendar
// dates (see the backend's `_all_day_midnight`) and must be read with plain
// UTC digits, never re-localized — converting a UTC-midnight all-day
// boundary into a non-UTC timezone would push it onto the wrong calendar
// date. Timed events are read in their own governing timezone (falling back
// to the calendar's timezone if the event somehow has none).
function occurrenceDateKey(
  value: string,
  event: EventOccurrence,
  timeZone: string,
): string {
  return event.is_all_day
    ? dateKey(value)
    : zonedDateKey(value, event.timezone || timeZone);
}

/** The single place that resolves "which calendar date(s) does this event
 *  occupy" — used identically by Month's grid placement, `eventsForDay`, and
 *  `groupEventsByDay`, so there is exactly one implementation of the
 *  all-day-exclusive-end / timed-event-local-date rules the whole calendar
 *  UI depends on. */
export function eventDateBounds(
  event: EventOccurrence,
  timeZone: string,
): { startKey: string; endKey: string } {
  const startKey = occurrenceDateKey(event.start_at, event, timeZone);
  let endKey = occurrenceDateKey(event.end_at, event, timeZone);
  if (event.is_all_day && event.end_at.endsWith("T00:00:00+00:00")) {
    const endDate = new Date(event.end_at);
    endDate.setUTCDate(endDate.getUTCDate() - 1);
    endKey = dateKey(endDate);
  }
  return { startKey, endKey };
}

export function eventsForDay(
  events: EventOccurrence[],
  day: Date | string,
  timeZone: string,
): EventOccurrence[] {
  const target = dateKey(day);
  return events
    .filter((event) => {
      const { startKey, endKey } = eventDateBounds(event, timeZone);
      return startKey <= target && endKey >= target;
    })
    .sort((left, right) => {
      if (left.is_all_day !== right.is_all_day) return left.is_all_day ? -1 : 1;
      return (
        left.start_at.localeCompare(right.start_at) ||
        left.title.localeCompare(right.title)
      );
    });
}

// Two independent, composable filters, applied in the same order and the same
// way regardless of which view (Month/Week/Day/Schedule) is rendering the
// resulting list, so all views stay in sync for a given selection:
//
// - `memberFilter` is a household member's stable user_id (the canonical
//   event-membership relationship, EventOccurrence.member_ids, backed by
//   CalendarEventMember) — "who is this event for", independent of who
//   created it. Empty string means no member filter ("Everyone").
// - `labelFilter` is a household-defined CalendarEventLabel id (a free-form
//   category/tag, e.g. "Family", "Work", or a personal label someone
//   named after a household member such as "Megan") — a category filter, NOT
//   a participant/member filter, even when its name happens to match a
//   person's name. Empty string means no category filter.
export function filterVisibleEvents(
  events: EventOccurrence[],
  memberFilter: string,
  labelFilter: string,
  query: string,
): EventOccurrence[] {
  let filtered = memberFilter
    ? events.filter((event) => event.member_ids.includes(memberFilter))
    : events;
  filtered = labelFilter
    ? filtered.filter((event) => (event.label?.id ?? "") === labelFilter)
    : filtered;
  const needle = query.trim().toLowerCase();
  if (!needle) return filtered;
  return filtered.filter((event) => event.title.toLowerCase().includes(needle));
}

// A persisted member-filter selection is only trustworthy while it still
// names a real member of the *currently active* Home — a member who left,
// was deleted, or belongs to a different Home (persistence is home-scoped,
// see MEMBER_STORAGE_PREFIX in page.tsx, but this guards the load-race and
// deletion cases too) must fall back to "Everyone" rather than silently
// filtering the calendar down to nothing forever.
export function resolveMemberFilter(
  members: Member[],
  persisted: string,
): string {
  if (!persisted) return "";
  return members.some((member) => member.user_id === persisted) ? persisted : "";
}

// Empty-state copy for a filtered, otherwise-empty list. Deliberately simple
// (member clause, then category clause) rather than generating full
// sentences for every combination.
export function emptyStateMessage(
  memberName: string | null,
  labelName: string | null,
): string {
  const clauses = [
    memberName ? `for ${memberName}` : "",
    labelName ? `in ${labelName}` : "",
  ].filter(Boolean);
  if (clauses.length === 0) return "No upcoming events.";
  return `No upcoming events ${clauses.join(" ")}.`;
}

export function groupEventsByDay(
  events: EventOccurrence[],
  timeZone: string,
): Map<string, EventOccurrence[]> {
  const result = new Map<string, EventOccurrence[]>();
  for (const event of events) {
    const { startKey, endKey } = eventDateBounds(event, timeZone);
    const start = new Date(`${startKey}T00:00:00.000Z`);
    const end = new Date(`${endKey}T00:00:00.000Z`);
    for (
      const cursor = new Date(start);
      cursor <= end;
      cursor.setUTCDate(cursor.getUTCDate() + 1)
    ) {
      const key = dateKey(cursor);
      result.set(
        key,
        eventsForDay([...(result.get(key) ?? []), event], key, timeZone),
      );
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Start/End picker duration logic — shared by the combined date/time control
// so "preserve duration when Start changes" and "default new events to a
// 1-hour duration" are implemented once, not per call site.
// ---------------------------------------------------------------------------

export const DEFAULT_EVENT_DURATION_MINUTES = 60;

// Same deterministic-default convention as DEFAULT_EVENT_START_TIME above,
// one full default duration later. Assumes DEFAULT_EVENT_DURATION_MINUTES is
// a whole number of hours (currently 60) — both are plain "HH:mm" strings,
// not instants, so this stays correct regardless of timezone/DST.
export const DEFAULT_EVENT_END_TIME = `${pad2(
  DEFAULT_EVENT_START_HOUR + DEFAULT_EVENT_DURATION_MINUTES / 60,
)}:00`;

/** When Start moves, End moves with it by the same amount so the event's
 *  duration is preserved (a user who deliberately shortened/lengthened an
 *  event keeps that custom duration; a fresh event keeps its 1-hour
 *  default). Never lets End end up at or before the new Start. */
export function shiftEndWithStart(
  previousStart: Date,
  previousEnd: Date,
  nextStart: Date,
): Date {
  const previousDurationMs = previousEnd.getTime() - previousStart.getTime();
  const durationMs =
    previousDurationMs > 0
      ? previousDurationMs
      : DEFAULT_EVENT_DURATION_MINUTES * 60_000;
  return new Date(nextStart.getTime() + durationMs);
}

export interface WhenState {
  allDay: boolean;
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
  multiDay: boolean;
  /** Whether startTime/endTime currently hold a real, user-meaningful clock
   *  value — true for a timed event (existing, or new with a sensible
   *  default), false for a persisted all-day event, which has never had
   *  one. Session-scoped: once a meaningful value is established (either
   *  because one already existed, or the picker's All-day toggle handler
   *  just synthesized one), it must be preserved across any further All
   *  day <-> timed toggling within the same edit, never re-derived from
   *  the all-day boundary. */
  hasTimedValues: boolean;
}

// The one place that decides the picker's starting values for an edit
// session — see the timed-vs-all-day comment block above. A persisted
// all-day event's calendar date(s) are read with plain UTC digits
// (dateKey), never zoned, and deliberately get no clock value yet
// (DEFAULT_EVENT_START_TIME/END_TIME are placeholders, only actually shown
// to the user once they turn All day off — see the picker's All-day toggle
// handler, which checks hasTimedValues before touching startTime/endTime).
export function computeInitialWhen(
  initial: EventOccurrence | undefined,
  initialDay: Date,
  eventTimeZone: string,
): WhenState {
  if (initial?.is_all_day) {
    const startDate = dateKey(initial.start_at);
    // end_at is stored exclusive (the day after the last covered date) —
    // resolve the inclusive last day the user actually intended.
    const endExclusive = new Date(initial.end_at);
    endExclusive.setUTCDate(endExclusive.getUTCDate() - 1);
    const endDate = dateKey(endExclusive);
    return {
      allDay: true,
      startDate,
      startTime: DEFAULT_EVENT_START_TIME,
      endDate,
      endTime: DEFAULT_EVENT_END_TIME,
      multiDay: startDate !== endDate,
      hasTimedValues: false,
    };
  }

  if (!initial) {
    // initialDay is itself a UTC-midnight-anchored calendar-date
    // placeholder (from monthCells/openDay/focusDate) — its date digits
    // are the intended calendar date directly, no zoned conversion needed.
    const startDate = dateKey(initialDay);
    return {
      allDay: false,
      startDate,
      startTime: DEFAULT_EVENT_START_TIME,
      endDate: startDate,
      endTime: DEFAULT_EVENT_END_TIME,
      multiDay: false,
      hasTimedValues: true,
    };
  }

  const startParts = splitZoned(new Date(initial.start_at), eventTimeZone);
  const endParts = splitZoned(new Date(initial.end_at), eventTimeZone);
  return {
    allDay: false,
    startDate: startParts.date,
    startTime: startParts.time,
    endDate: endParts.date,
    endTime: endParts.time,
    multiDay: startParts.date !== endParts.date,
    hasTimedValues: true,
  };
}

/** Applies the picker's All-day toggle to the current WhenState. Toggling
 *  on never touches startTime/endTime (they stay hidden, not discarded).
 *  Toggling off only ever *establishes* a fresh, sensible clock value
 *  (DEFAULT_EVENT_START_TIME/END_TIME, the same convention a brand-new
 *  event gets) the first time this session has no meaningful one yet
 *  (`!hasTimedValues`, i.e. the event was persisted as all-day and the user
 *  hasn't turned All day off before in this edit) — startDate/endDate (the
 *  intended calendar date(s)) are left untouched either way, and once a
 *  meaningful timed value exists, further toggling always preserves it
 *  exactly, whether it's the synthesized default or something the user has
 *  since edited. See the timed-vs-all-day comment block above for why this
 *  must never derive a clock value from the all-day UTC-midnight
 *  boundary. */
export function applyAllDayToggle(when: WhenState, nextAllDay: boolean): WhenState {
  if (!nextAllDay && !when.hasTimedValues) {
    return {
      ...when,
      allDay: false,
      startTime: DEFAULT_EVENT_START_TIME,
      endTime: DEFAULT_EVENT_END_TIME,
      hasTimedValues: true,
    };
  }
  return { ...when, allDay: nextAllDay };
}

// ---------------------------------------------------------------------------
// Event View/Edit permissions — mirrors the backend's authorization rule
// exactly (apps/api/mykhaya/routers/calendar.py update_event/delete_event)
// so the Edit/Delete actions are only ever *shown* when the backend would
// actually allow them. This is a UI convenience only: the backend remains
// the sole source of truth and re-checks on every request regardless of
// what the frontend decided to render.
// ---------------------------------------------------------------------------

/** An event is editable by the current user when they hold the household-
 *  wide `calendar.edit_all` capability, or hold `calendar.edit_own` *and*
 *  created the event themselves — the same two-tier rule `update_event`
 *  enforces server-side. */
export function canEditEvent(
  capabilities: string[],
  event: EventOccurrence,
  currentUserId: string | null,
): boolean {
  if (capabilities.includes("calendar.edit_all")) return true;
  if (!capabilities.includes("calendar.edit_own")) return false;
  return currentUserId !== null && event.created_by === currentUserId;
}

/** Delete has no ownership tier server-side — any member holding
 *  `calendar.delete` may delete any event in the Home (see delete_event). */
export function canDeleteEvent(capabilities: string[]): boolean {
  return capabilities.includes("calendar.delete");
}
