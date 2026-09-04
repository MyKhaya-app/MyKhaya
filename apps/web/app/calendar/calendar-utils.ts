import type {
  EventMutationScope,
  EventOccurrence,
  EventPayload,
  EventUpdatePayload,
  Member,
  SharedEventPayload,
  SharedEventUpdatePayload,
} from "@mykhaya/shared-types";

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

// The one place a Date/instant becomes user-facing text — always given an
// explicit IANA zone: either the Home's primary calendar timezone (headers,
// day labels), an individual event's own governing timezone
// (event.timezone), or literal "UTC" for a plain calendar-date label. Never
// the browser's local zone, never a silent default — see the timed-vs-all-day
// note above for why that distinction matters here too.
export function displayDate(
  value: Date | string,
  options: Intl.DateTimeFormatOptions,
  timeZone: string,
) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    ...options,
  }).format(typeof value === "string" ? new Date(value) : value);
}

export function eventTime(event: EventOccurrence, timeZone: string) {
  if (event.is_all_day) return "All day";
  return displayDate(
    event.start_at,
    { hour: "2-digit", minute: "2-digit" },
    event.timezone || timeZone,
  );
}

// The one place month-to-month date arithmetic happens — used both by the
// Previous/Next month controls and by the month-view swipe gesture's
// prev/next preview panels, so the two can never drift into two different
// ideas of "next month".
export function addMonths(base: Date, delta: number): Date {
  const next = new Date(base);
  next.setUTCMonth(next.getUTCMonth() + delta);
  return next;
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
export function zonedToday(timeZone: string, now: Date = new Date()): Date {
  const { year, month, day } = zonedParts(now, timeZone);
  return new Date(Date.UTC(year, month - 1, day));
}

export function calendarDateAfter(key: string, days: number): string {
  const date = new Date(`${key}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return dateKey(date);
}

/** Whether `event`'s occurrence hasn't finished yet, as of `now` — the
 *  eligibility test Home -> "Coming up" applies to whatever candidate
 *  occurrences the backend already selected. Deliberately a plain instant
 *  comparison against the occurrence's own `end_at`, never a calendar-date
 *  comparison: comparing calendar dates (as this used to, via a "starts on
 *  or after tomorrow's date" rule) can't distinguish "already finished
 *  earlier today" from "still to come later today" — both fall on the same
 *  date — which is exactly what caused Coming Up to skip every remaining
 *  event on the current day. `end_at` is a real UTC instant for a timed
 *  event, and (per the timed-vs-all-day note above) an equally real,
 *  timezone-independent instant for an all-day event's stored exclusive-end
 *  boundary, so no separate all-day case or `timeZone` parameter is needed
 *  here — comparing two real instants is inherently timezone-correct.
 *  Naturally includes an occurrence currently in progress (started before
 *  `now`, ends after it) and excludes one that has already ended, whatever
 *  day it falls on. No upper bound: this only ever checks "not yet over",
 *  never "not too far in the future" — see
 *  calendar_occurrences.upcoming_candidate_filter on the backend for the
 *  matching "no horizon" rule its own cursor-based query already applies. */
export function isEventStillUpcoming(
  event: EventOccurrence,
  now: Date = new Date(),
): boolean {
  return new Date(event.end_at).getTime() > now.getTime();
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

export interface WeekEventLayoutRow {
  event: EventOccurrence;
  /** 0-6 column index (Mon=0) of this event's segment within the week. */
  start: number;
  end: number;
  /** 0-based display lane within the week. */
  row: number;
}

/**
 * Assigns each event overlapping a visible month-view week to a display
 * lane (row) and column span. Multi-day events (endKey !== startKey — the
 * same definition MonthView already uses for "isMultiDay" styling) are
 * packed into the lowest lanes first; single-day events are packed
 * afterwards, strictly beneath every lane a multi-day event used that week
 * — never sharing a lane with one, even where a multi-day event's own
 * column span leaves a same-row gap on another day. This is what keeps a
 * multi-day bar reading as continuous top-priority content instead of
 * fragmenting into whichever lane happened to be free when its turn in
 * start-date order came up.
 *
 * The packing rule within each group (single-day, same as before this
 * function existed; multi-day, new) is greedy first-fit: the lowest lane
 * whose already-placed column intervals don't overlap this event's
 * [start, end]. Pure and DOM-free — MonthView (month-view.tsx) is the only
 * caller, once per visible week.
 */
export function layoutWeekEvents(
  events: EventOccurrence[],
  days: Date[],
  bounds: Map<string, { startKey: string; endKey: string }>,
): WeekEventLayoutRow[] {
  const weekStart = dateKey(days[0]!);
  const weekEnd = dateKey(days[6]!);

  const overlapping = events.filter((event) => {
    const { startKey, endKey } = bounds.get(event.occurrence_id)!;
    return endKey >= weekStart && startKey <= weekEnd;
  });

  const multiDay = overlapping.filter((event) => {
    const { startKey, endKey } = bounds.get(event.occurrence_id)!;
    return endKey !== startKey;
  });
  const singleDay = overlapping.filter((event) => {
    const { startKey, endKey } = bounds.get(event.occurrence_id)!;
    return endKey === startKey;
  });

  // Column span [0-6] this event actually occupies in *this* visible week
  // — clipped at the week boundary, so an event that started three weeks
  // ago and an event that started yesterday can both show, say, a 2-day
  // visible bar this week and be compared like-for-like. Used for both
  // lane-priority ordering (below) and actual grid placement (place()),
  // so the two can never disagree about what "this event's bar" spans.
  function visibleColumns(event: EventOccurrence): { start: number; end: number } {
    const { startKey, endKey } = bounds.get(event.occurrence_id)!;
    const start = Math.max(0, days.findIndex((day) => dateKey(day) >= startKey));
    const end = Math.min(6, days.reduce((last, day, index) => (dateKey(day) <= endKey ? index : last), -1));
    return { start, end };
  }

  // Deterministic ordering for overlapping multi-day events: longer VISIBLE
  // span within this week wins the higher (lower-numbered) lane first —
  // this is the actual bar the user sees this week, not the event's full
  // underlying duration, so an event only entering this week for its last
  // two days competes on those two days, not on however many weeks it ran
  // for in total. Ties broken by earlier visible start, then the stable
  // occurrence_id so render order never depends on array/fetch order.
  const multiDayWithColumns = multiDay.map((event) => ({ event, ...visibleColumns(event) }));
  multiDayWithColumns.sort((a, b) => {
    const spanA = a.end - a.start;
    const spanB = b.end - b.start;
    if (spanA !== spanB) return spanB - spanA;
    if (a.start !== b.start) return a.start - b.start;
    return a.event.occurrence_id.localeCompare(b.event.occurrence_id);
  });

  // Unchanged from the pre-existing single sort: start date, then title.
  singleDay.sort((a, b) => {
    const boundsA = bounds.get(a.occurrence_id)!;
    const boundsB = bounds.get(b.occurrence_id)!;
    return boundsA.startKey.localeCompare(boundsB.startKey) || a.title.localeCompare(b.title);
  });

  const rowIntervals: { start: number; end: number }[][] = [];
  const rows: WeekEventLayoutRow[] = [];

  // Corrective follow-up: an earlier version of this function floored
  // single-day placement at however many lanes multi-day events used
  // *anywhere* in the week, so a day with no multi-day event of its own
  // still lost that many lanes' worth of vertical space to nothing — blank
  // rows above/between real events on days a multi-day bar never touched.
  // Lane search is column-aware (below), so there is no need for a global
  // floor to get multi-day priority: processing every multi-day event
  // before any single-day event already means that wherever a single-day
  // event's own day genuinely competes with a multi-day event for a lane
  // (the multi-day event's [start, end] column range includes that day),
  // the multi-day event — placed first — has already claimed the lowest
  // available lane there, so the competing single-day event is naturally
  // pushed to the next one. On a day the multi-day event's range doesn't
  // reach, that lane was never occupied for that day's column in the first
  // place, so a single-day event there is free to use it — exactly the
  // per-day compaction this fix restores.
  function place(event: EventOccurrence, columns: { start: number; end: number }) {
    const { start, end } = columns;
    if (end < start) return;
    let row = rowIntervals.findIndex((intervals) => intervals.every((interval) => end < interval.start || start > interval.end));
    if (row === -1) row = rowIntervals.length;
    (rowIntervals[row] ??= []).push({ start, end });
    rows.push({ event, start, end, row });
  }

  // Multi-day first, in the visible-span-priority order computed above, so
  // a genuine lane contest on a shared day always resolves in the longer
  // (or, on a tie, earlier-starting) bar's favour; single-day afterwards,
  // free to reuse any lane a multi-day event left untouched on that
  // particular day.
  multiDayWithColumns.forEach(({ event, start, end }) => place(event, { start, end }));
  singleDay.forEach((event) => place(event, visibleColumns(event)));

  return rows;
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

/** An externally shared occurrence's edit/delete authority comes from its
 *  own CalendarShare.permission, never from the viewer's Home capabilities
 *  (they may have none — they're not a Home member at all). Mirrors
 *  routers.calendar_sharing's `_require_my_share(..., need_manage=True)`
 *  exactly: "manage" can create/edit/delete, "view" can do neither. Only
 *  meaningful for an occurrence carrying `share_id` — see EventOccurrence's
 *  docstring in shared-types. */
export function canEditSharedEvent(event: EventOccurrence): boolean {
  return event.share_permission === "manage";
}
export function canDeleteSharedEvent(event: EventOccurrence): boolean {
  return event.share_permission === "manage";
}

/** Builds the exact body POST/PATCH .../calendar-shares/{id}/events accepts
 *  from the same EventPayload EventForm already produces — deliberately
 *  drops member_ids/label_id/calendar_id (SharedEventCreate/Update are
 *  StrictModel and 422 on any unrecognised field): an externally shared
 *  event can never be assigned to Home members or a Home-owned category the
 *  recipient isn't authorised to use. See EventForm's isSharedEvent branch,
 *  which hides the People/Category controls that would otherwise produce
 *  these fields in the first place. */
export function toSharedEventPayload(payload: EventPayload): SharedEventPayload {
  return {
    title: payload.title,
    start_at: payload.start_at,
    end_at: payload.end_at,
    timezone: payload.timezone,
    is_all_day: payload.is_all_day,
    description: payload.description,
    location_text: payload.location_text,
    reminder_minutes: payload.reminder_minutes,
    recurrence: payload.recurrence,
    recurrence_interval: payload.recurrence_interval,
    recurrence_until: payload.recurrence_until,
    recurrence_end_date: payload.recurrence_end_date,
    recurrence_count: payload.recurrence_count,
  };
}

export function toSharedEventUpdatePayload(
  payload: EventPayload,
  expectedUpdatedAt: string,
): SharedEventUpdatePayload {
  return { ...toSharedEventPayload(payload), expected_updated_at: expectedUpdatedAt };
}

// ---------------------------------------------------------------------------
// Calendar selector visibility — a purely client-side, per-viewer show/hide
// toggle (localStorage only, never sent to the backend) covering both a
// Home's own calendars (keyed by HomeCalendar.id) and calendars shared with
// the viewer (keyed by CalendarShare.id, via EventOccurrence.share_id) — see
// CalendarSelector in app/calendar/page.tsx. Hiding a calendar here never
// revokes/mutes anything server-side; it only affects what this browser
// currently renders, exactly like muting is independent of access in the
// backend model (CalendarShare.notification_preference/include_in_briefing).
// ---------------------------------------------------------------------------

export function isCalendarVisible(
  event: EventOccurrence,
  hiddenIds: ReadonlySet<string>,
): boolean {
  const key = event.share_id ?? event.calendar_id;
  return !hiddenIds.has(key);
}

export function filterByVisibleCalendars(
  events: EventOccurrence[],
  hiddenIds: ReadonlySet<string>,
): EventOccurrence[] {
  if (hiddenIds.size === 0) return events;
  return events.filter((event) => isCalendarVisible(event, hiddenIds));
}

/** Builds the exact body PATCH /events/{id} accepts from the same
 *  EventPayload EventForm already produces for create — deliberately drops
 *  `calendar_id` (EventUpdatePayload has no such field; the backend's
 *  EventUpdate schema is a StrictModel and 422s with `extra_forbidden` on
 *  any unrecognised field). An event's calendar assignment is fixed at
 *  creation and always resolved server-side from the existing row; sending
 *  it here broke every edit regardless of what actually changed —
 *  regression covered by calendar-utils.test.ts. */
// `scope`/`occurrenceStart` are omitted entirely (not even sent as
// undefined) for the default "series" case — matches the backend's own
// default exactly, so an ordinary non-recurring edit's request body is
// byte-for-byte unchanged from before this feature existed. `occurrenceStart`
// must always be the CANONICAL EventOccurrence.occurrence_start captured
// when the sheet was opened, never derived from `payload.start_at` (the
// just-edited value) — see EventOccurrence.occurrence_start's docstring in
// shared-types.
export function toEventUpdatePayload(
  payload: EventPayload,
  expectedUpdatedAt: string,
  scope?: EventMutationScope,
  occurrenceStart?: string,
): EventUpdatePayload {
  return {
    title: payload.title,
    start_at: payload.start_at,
    end_at: payload.end_at,
    timezone: payload.timezone,
    is_all_day: payload.is_all_day,
    description: payload.description,
    location_text: payload.location_text,
    label_id: payload.label_id,
    member_ids: payload.member_ids,
    reminder_minutes: payload.reminder_minutes,
    recurrence: payload.recurrence,
    recurrence_interval: payload.recurrence_interval,
    recurrence_until: payload.recurrence_until,
    ...(payload.recurrence_end_date !== undefined
      ? { recurrence_end_date: payload.recurrence_end_date }
      : {}),
    recurrence_count: payload.recurrence_count,
    expected_updated_at: expectedUpdatedAt,
    ...(scope && scope !== "series" ? { scope, occurrence_start: occurrenceStart } : {}),
  };
}
