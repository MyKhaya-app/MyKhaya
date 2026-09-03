import type { EventOccurrence, Home, Reminder, Routine } from "@mykhaya/shared-types";

/**
 * The iOS Home Screen widgets' entire data contract (native widget work,
 * Phase 5). This is a deliberately small, versioned, display-only
 * projection of already-authorised data the signed-in user can already see
 * in MyKhaya — never a serialisation of the raw API models, and never
 * anything that could authenticate a request (no tokens, no cookies, no
 * PINs). See docs/mobile/ios-widgets.md for the full security model.
 *
 * `WidgetSnapshotStore.swift` decodes this exact JSON shape from the App
 * Group container. Bump `WIDGET_SNAPSHOT_SCHEMA_VERSION` (and the mirrored
 * `schemaVersion` constant in Shared/WidgetSnapshot.swift) for any
 * breaking field change; the widget extension must treat an unknown/older
 * version as "no data" rather than guessing at a shape it wasn't built for.
 */
export const WIDGET_SNAPSHOT_SCHEMA_VERSION = 1;

export interface WidgetHome {
  id: string;
  displayName: string;
}

export interface WidgetEvent {
  /** EventOccurrence.occurrence_id — unique even for an expanded recurrence. */
  id: string;
  title: string;
  /** ISO-8601, UTC. Native side converts to the device's local timezone. */
  startAt: string;
  endAt: string;
  isAllDay: boolean;
  /** IANA timezone the event was authored in (EventOccurrence.timezone). */
  timezone: string;
  /** Category colour if the event carries a label, else the calendar's own colour. */
  colorHex: string;
  /** App-relative path, resolved the same way the notification deep-link
   *  registry resolves `calendar_event` (apps/api/mykhaya/notifications/deep_links.py). */
  deepLink: string;
}

export type WidgetTodoKind = "routine" | "reminder";

export interface WidgetTodoItem {
  id: string;
  kind: WidgetTodoKind;
  title: string;
  /** ISO date (routines) or date+time (reminders with a due_time), or null
   *  if the item has no concrete next occurrence. */
  dueAt: string | null;
  overdue: boolean;
  scope: "personal" | "household";
  deepLink: string;
}

export interface WidgetSnapshot {
  schemaVersion: number;
  /** ISO-8601 UTC — when this snapshot was produced, for staleness display. */
  generatedAt: string;
  signedIn: boolean;
  activeHome: WidgetHome | null;
  /** Next few not-yet-finished events (may include one currently running),
   *  soonest first. Capped at MAX_UPCOMING_EVENTS. */
  upcomingEvents: WidgetEvent[];
  /** Every event whose local day is today (all-day and multi-day events that
   *  span today included), soonest first. */
  todayEvents: WidgetEvent[];
  /** Every event overlapping the current local month, capped at
   *  MAX_MONTH_EVENTS — the Calendar widget renders a condensed
   *  representation itself if a day has more than it can show. */
  monthEvents: WidgetEvent[];
  /** Overdue first, then due today, then upcoming; completed items excluded. */
  todoItems: WidgetTodoItem[];
}

export const MAX_UPCOMING_EVENTS = 3;
export const MAX_MONTH_EVENTS = 250;
export const MAX_TODO_ITEMS = 12;

/** The state written to the App Group after logout, or before any snapshot
 * has ever been produced. Widgets render "Open MyKhaya to sign in". */
export function signedOutWidgetSnapshot(now: Date = new Date()): WidgetSnapshot {
  return {
    schemaVersion: WIDGET_SNAPSHOT_SCHEMA_VERSION,
    generatedAt: now.toISOString(),
    signedIn: false,
    activeHome: null,
    upcomingEvents: [],
    todayEvents: [],
    monthEvents: [],
    todoItems: [],
  };
}

/** Signed in, but nothing to show yet (no Home selected, or feature-flagged
 * off) — distinct from signed-out so the widget can word it differently. */
export function emptyHomeWidgetSnapshot(now: Date = new Date()): WidgetSnapshot {
  return {
    ...signedOutWidgetSnapshot(now),
    signedIn: true,
  };
}

function eventColor(occurrence: EventOccurrence): string {
  return occurrence.label?.color ?? occurrence.calendar_color;
}

// Mirrors apps/api/mykhaya/notifications/deep_links.py's resolve_path() for
// the "calendar_event" target — the same registry a push notification tap
// resolves through, so a widget tap and a notification tap land on the
// exact same app path for the same event.
function eventDeepLink(occurrence: EventOccurrence): string {
  return `/calendar?event=${encodeURIComponent(occurrence.event_id)}`;
}

function routineDeepLink(routine: Routine): string {
  return `/home?routine=${encodeURIComponent(routine.id)}`;
}

function reminderDeepLink(reminder: Reminder): string {
  return `/settings/reminders?reminder=${encodeURIComponent(reminder.id)}`;
}

function toWidgetEvent(occurrence: EventOccurrence): WidgetEvent {
  return {
    id: occurrence.occurrence_id,
    title: occurrence.title,
    startAt: occurrence.start_at,
    endAt: occurrence.end_at,
    isAllDay: occurrence.is_all_day,
    timezone: occurrence.timezone,
    colorHex: eventColor(occurrence),
    deepLink: eventDeepLink(occurrence),
  };
}

function localDayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function eventSpansLocalDay(occurrence: EventOccurrence, dayKey: string): boolean {
  // All-day and multi-day events are stored as a start/end range; comparing
  // day keys (not instants) avoids the classic "all-day event treated as a
  // midnight-timed event" bug — an all-day event's stored end_at is
  // typically the exclusive start of the following day, so this compares
  // whether `dayKey` falls within [startDay, endDay).
  const startKey = localDayKey(occurrence.start_at);
  const endDate = new Date(occurrence.end_at);
  // Exclusive end for all-day/multi-day ranges; inclusive-of-start-day for
  // a same-day timed event whose end_at is later the same day.
  const endKeyExclusive = occurrence.is_all_day || endDate.getTime() - new Date(occurrence.start_at).getTime() >= 86_400_000
    ? localDayKey(new Date(endDate.getTime() - 1).toISOString())
    : localDayKey(occurrence.end_at);
  return dayKey >= startKey && dayKey <= endKeyExclusive;
}

export interface BuildWidgetSnapshotInput {
  activeHome: Home;
  /** Occurrences already visibility-filtered by the normal calendar fetch
   *  (own Home calendars + accepted shares) — this function does no
   *  additional authorisation filtering of its own. */
  occurrences: EventOccurrence[];
  routines: Routine[];
  reminders: Reminder[];
  now?: Date;
}

/** Pure, deterministic snapshot construction — no network/storage access,
 * so this is fully unit-testable. `widget-bridge.ts` is the only caller
 * that fetches data and hands it in. */
export function buildWidgetSnapshot(input: BuildWidgetSnapshotInput): WidgetSnapshot {
  const now = input.now ?? new Date();
  const todayKey = localDayKey(now.toISOString());
  const nowMs = now.getTime();

  const sortedEvents = [...input.occurrences].sort(
    (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
  );

  const upcomingEvents = sortedEvents
    .filter((e) => new Date(e.end_at).getTime() > nowMs)
    .slice(0, MAX_UPCOMING_EVENTS)
    .map(toWidgetEvent);

  const todayEvents = sortedEvents
    .filter((e) => eventSpansLocalDay(e, todayKey))
    .map(toWidgetEvent);

  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  const monthEvents = sortedEvents
    .filter((e) => {
      const start = new Date(e.start_at);
      const end = new Date(e.end_at);
      return end > monthStart && start < monthEnd;
    })
    .slice(0, MAX_MONTH_EVENTS)
    .map(toWidgetEvent);

  const todoItems = buildTodoItems(input.routines, input.reminders, todayKey);

  return {
    schemaVersion: WIDGET_SNAPSHOT_SCHEMA_VERSION,
    generatedAt: now.toISOString(),
    signedIn: true,
    activeHome: { id: input.activeHome.id, displayName: input.activeHome.name },
    upcomingEvents,
    todayEvents,
    monthEvents,
    todoItems,
  };
}

function todoRank(item: WidgetTodoItem, todayKey: string): number {
  if (item.overdue) return 0;
  if (item.dueAt && item.dueAt.slice(0, 10) === todayKey) return 1;
  return 2;
}

function buildTodoItems(routines: Routine[], reminders: Reminder[], todayKey: string): WidgetTodoItem[] {
  const items: WidgetTodoItem[] = [];

  for (const routine of routines) {
    if (!routine.enabled || routine.completed_today) continue;
    const dueAt = routine.next_occurrence_date;
    items.push({
      id: routine.id,
      kind: "routine",
      title: routine.title,
      dueAt,
      overdue: Boolean(dueAt && dueAt < todayKey),
      scope: routine.scope,
      deepLink: routineDeepLink(routine),
    });
  }

  for (const reminder of reminders) {
    if (!reminder.enabled || reminder.completed_today) continue;
    const dueAt = reminder.next_occurrence_date
      ? `${reminder.next_occurrence_date}T${reminder.due_time}`
      : null;
    items.push({
      id: reminder.id,
      kind: "reminder",
      title: reminder.title,
      dueAt,
      overdue: Boolean(reminder.next_occurrence_date && reminder.next_occurrence_date < todayKey),
      scope: reminder.scope,
      deepLink: reminderDeepLink(reminder),
    });
  }

  items.sort((a, b) => {
    const rankDiff = todoRank(a, todayKey) - todoRank(b, todayKey);
    if (rankDiff !== 0) return rankDiff;
    const aDue = a.dueAt ?? "9999";
    const bDue = b.dueAt ?? "9999";
    if (aDue !== bDue) return aDue < bDue ? -1 : 1;
    return a.title.localeCompare(b.title);
  });

  return items.slice(0, MAX_TODO_ITEMS);
}
