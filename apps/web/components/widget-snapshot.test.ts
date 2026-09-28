import { describe, expect, it } from "vitest";
import type { EventOccurrence, Home, Reminder, Routine } from "@mykhaya/shared-types";
import {
  WIDGET_SNAPSHOT_SCHEMA_VERSION,
  buildWidgetSnapshot,
  eventOverlapsWidgetRange,
  fallbackWidgetCalendarRange,
  type WidgetCalendarRange,
  emptyHomeWidgetSnapshot,
  signedOutWidgetSnapshot,
} from "./widget-snapshot";

const HOME: Home = {
  id: "home-1",
  name: "The Hales",
  role: "owner",
  relationship: "adult",
  permission_profile: "home_admin",
  capabilities: [],
  member_count: 2,
  child_login_code: "AB12",
};

function occurrence(overrides: Partial<EventOccurrence>): EventOccurrence {
  return {
    occurrence_id: "occ-1",
    event_id: "evt-1",
    calendar_id: "cal-1",
    title: "Event",
    start_at: "2026-09-03T10:00:00.000Z",
    end_at: "2026-09-03T11:00:00.000Z",
    is_all_day: false,
    timezone: "Europe/London",
    description: null,
    location_text: null,
    label: null,
    calendar_color: "#4287f5",
    member_ids: [],
    recurrence: "none",
    reminder_minutes: null,
    created_by: "user-1",
    updated_at: "2026-09-01T00:00:00.000Z",
    is_overridden: false,
    ...overrides,
    occurrence_start:
      overrides.occurrence_start ?? overrides.start_at ?? "2026-09-03T10:00:00.000Z",
  };
}

function routine(overrides: Partial<Routine>): Routine {
  return {
    id: "routine-1",
    title: "Take the bins out",
    description: null,
    scope: "household",
    owner_user_id: null,
    interval_weeks: 1,
    repeat_unit: "weekly",
    week_anchor_date: "2026-09-01",
    reminder_timing: "same_day",
    is_critical: false,
    pinned: false,
    enabled: true,
    start_date: "2026-01-01",
    end_date: null,
    member_ids: [],
    next_occurrence_date: "2026-09-03",
    completed_today: false,
    created_by: "user-1",
    updated_at: "2026-09-01T00:00:00.000Z",
    ...overrides,
  };
}

function reminder(overrides: Partial<Reminder>): Reminder {
  return {
    id: "reminder-1",
    title: "Pay water bill",
    description: null,
    scope: "personal",
    owner_user_id: "user-1",
    due_date: "2026-09-03",
    due_time: "09:00:00",
    repeat: "never",
    cadence: "once",
    enabled: true,
    member_ids: [],
    next_occurrence_date: "2026-09-03",
    completed_today: false,
    created_by: "user-1",
    updated_at: "2026-09-01T00:00:00.000Z",
    ...overrides,
  };
}

// Fixed "now" mid-morning on 2026-09-03 (local = UTC in the test runner).
const NOW = new Date("2026-09-03T09:30:00.000Z");

describe("signedOutWidgetSnapshot / emptyHomeWidgetSnapshot", () => {
  it("signed-out snapshot has no household data and signedIn=false", () => {
    const snapshot = signedOutWidgetSnapshot(NOW);
    expect(snapshot.signedIn).toBe(false);
    expect(snapshot.activeHome).toBeNull();
    expect(snapshot.upcomingEvents).toEqual([]);
    expect(snapshot.todoItems).toEqual([]);
    expect(snapshot.schemaVersion).toBe(WIDGET_SNAPSHOT_SCHEMA_VERSION);
  });

  it("empty-home snapshot is signed in but still carries no Home", () => {
    const snapshot = emptyHomeWidgetSnapshot(NOW);
    expect(snapshot.signedIn).toBe(true);
    expect(snapshot.activeHome).toBeNull();
  });
});

describe("buildWidgetSnapshot — Next Event selection", () => {
  it("returns an empty upcoming list when there are no events", () => {
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [], reminders: [], now: NOW });
    expect(snapshot.upcomingEvents).toEqual([]);
    expect(snapshot.todayEvents).toEqual([]);
  });

  it("includes an event currently in progress, not just future ones", () => {
    const current = occurrence({
      occurrence_id: "occ-current",
      start_at: "2026-09-03T09:00:00.000Z",
      end_at: "2026-09-03T10:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [current], routines: [], reminders: [], now: NOW });
    expect(snapshot.upcomingEvents.map((e) => e.id)).toEqual(["occ-current"]);
  });

  it("excludes an event that already finished earlier today", () => {
    const finished = occurrence({
      occurrence_id: "occ-finished",
      start_at: "2026-09-03T07:00:00.000Z",
      end_at: "2026-09-03T08:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [finished], routines: [], reminders: [], now: NOW });
    expect(snapshot.upcomingEvents).toEqual([]);
    // But it must still appear in today's list — a finished event does not
    // disappear from "today", only from "what's next".
    expect(snapshot.todayEvents.map((e) => e.id)).toEqual(["occ-finished"]);
  });

  it("does not skip an event still to come later today (regression: today's events must not be dropped)", () => {
    const laterToday = occurrence({
      occurrence_id: "occ-later",
      start_at: new Date(2026, 8, 3, 18).toISOString(),
      end_at: new Date(2026, 8, 3, 19).toISOString(),
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [laterToday], routines: [], reminders: [], now: new Date(2026, 8, 3, 9, 30) });
    expect(snapshot.upcomingEvents.map((e) => e.id)).toEqual(["occ-later"]);
    expect(snapshot.todayEvents.map((e) => e.id)).toEqual(["occ-later"]);
  });

  it("orders upcoming events soonest-first and caps at MAX_UPCOMING_EVENTS", () => {
    const events = [
      occurrence({ occurrence_id: "c", start_at: "2026-09-03T14:00:00.000Z", end_at: "2026-09-03T15:00:00.000Z" }),
      occurrence({ occurrence_id: "a", start_at: "2026-09-03T10:00:00.000Z", end_at: "2026-09-03T11:00:00.000Z" }),
      occurrence({ occurrence_id: "b", start_at: "2026-09-03T12:00:00.000Z", end_at: "2026-09-03T13:00:00.000Z" }),
      occurrence({ occurrence_id: "d", start_at: "2026-09-04T09:00:00.000Z", end_at: "2026-09-04T10:00:00.000Z" }),
      occurrence({ occurrence_id: "e", start_at: "2026-09-05T09:00:00.000Z", end_at: "2026-09-05T10:00:00.000Z" }),
    ];
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: events, routines: [], reminders: [], now: NOW });
    expect(snapshot.upcomingEvents.map((e) => e.id)).toEqual(["a", "b", "c"]);
  });

  it("an all-day event today appears in today's list, not treated as midnight-only", () => {
    const allDay = occurrence({
      occurrence_id: "occ-allday",
      is_all_day: true,
      start_at: "2026-09-03T00:00:00.000Z",
      end_at: "2026-09-04T00:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [allDay], routines: [], reminders: [], now: NOW });
    expect(snapshot.todayEvents.map((e) => e.id)).toEqual(["occ-allday"]);
  });

  it("a multi-day event spanning today appears in today's list", () => {
    const multiDay = occurrence({
      occurrence_id: "occ-multiday",
      is_all_day: true,
      start_at: "2026-09-02T00:00:00.000Z",
      end_at: "2026-09-05T00:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [multiDay], routines: [], reminders: [], now: NOW });
    expect(snapshot.todayEvents.map((e) => e.id)).toEqual(["occ-multiday"]);
  });

  it("does not include tomorrow's event in today's list", () => {
    const tomorrow = occurrence({
      occurrence_id: "occ-tomorrow",
      start_at: "2026-09-04T09:00:00.000Z",
      end_at: "2026-09-04T10:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [tomorrow], routines: [], reminders: [], now: NOW });
    expect(snapshot.todayEvents).toEqual([]);
    expect(snapshot.upcomingEvents.map((e) => e.id)).toEqual(["occ-tomorrow"]);
  });

  it("a long title is preserved verbatim — native side owns truncation", () => {
    const longTitle = "A".repeat(200);
    const event = occurrence({ occurrence_id: "occ-long", title: longTitle });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.todayEvents[0]?.title).toBe(longTitle);
  });

  it("uses the category colour when a label is present, else the calendar colour", () => {
    const withLabel = occurrence({
      occurrence_id: "occ-label",
      label: { id: "l1", name: "Family", color: "#ff0000", is_active: true, sort_order: 0, commercial_access: null },
      calendar_color: "#00ff00",
    });
    const withoutLabel = occurrence({ occurrence_id: "occ-no-label", calendar_color: "#00ff00" });
    const snapshot = buildWidgetSnapshot({
      activeHome: HOME,
      occurrences: [withLabel, withoutLabel],
      routines: [],
      reminders: [],
      now: NOW,
    });
    const byId = Object.fromEntries(snapshot.todayEvents.map((e) => [e.id, e.colorHex]));
    expect(byId["occ-label"]).toBe("#ff0000");
    expect(byId["occ-no-label"]).toBe("#00ff00");
  });

  it("deep-links to the canonical /calendar?event= path used by the notification resolver", () => {
    const event = occurrence({ occurrence_id: "occ-x", event_id: "evt-42" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.todayEvents[0]?.deepLink).toBe("/calendar?event=evt-42");
  });
});

describe("buildWidgetSnapshot — Calendar (month) shaping", () => {
  it("includes an event at the very start of the month", () => {
    const event = occurrence({ occurrence_id: "occ-start", start_at: "2026-09-01T00:30:00.000Z", end_at: "2026-09-01T01:00:00.000Z" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.monthEvents.map((e) => e.id)).toContain("occ-start");
  });

  it("includes an event at the very end of the month", () => {
    const event = occurrence({ occurrence_id: "occ-end", start_at: "2026-09-30T22:00:00.000Z", end_at: "2026-09-30T23:00:00.000Z" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.monthEvents.map((e) => e.id)).toContain("occ-end");
  });

  it("excludes an event beyond the visible grid (not merely beyond the month)", () => {
    const event = occurrence({ occurrence_id: "occ-october", start_at: "2026-10-20T09:00:00.000Z", end_at: "2026-10-20T10:00:00.000Z" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.monthEvents.map((e) => e.id)).not.toContain("occ-october");
  });

  it("includes a multi-day event that crosses into this month from the previous one", () => {
    const event = occurrence({
      occurrence_id: "occ-crossing",
      is_all_day: true,
      start_at: "2026-08-30T00:00:00.000Z",
      end_at: "2026-09-02T00:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [event], routines: [], reminders: [], now: NOW });
    expect(snapshot.monthEvents.map((e) => e.id)).toContain("occ-crossing");
  });

  it("keeps several events on the same day, all present", () => {
    const events = Array.from({ length: 5 }, (_, i) =>
      occurrence({ occurrence_id: `occ-day-${i}`, start_at: `2026-09-10T0${i}:00:00.000Z`, end_at: `2026-09-10T0${i}:30:00.000Z` }),
    );
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: events, routines: [], reminders: [], now: NOW });
    expect(snapshot.monthEvents).toHaveLength(5);
  });
});

function visibleRange(startDate: string, endDate: string): WidgetCalendarRange {
  const localMidnight = (key: string) => {
    const [year, month, day] = key.split("-").map(Number);
    return new Date(year!, month! - 1, day).toISOString();
  };
  return { startDate, endDate, startAt: localMidnight(startDate), endAt: localMidnight(endDate) };
}

describe("Calendar widget visible range regressions", () => {
  const week = visibleRange("2026-09-28", "2026-10-05");
  const allDay = (start: string, end: string, id = start) => occurrence({
    occurrence_id: id, is_all_day: true,
    start_at: `${start}T00:00:00Z`, end_at: `${end}T00:00:00Z`,
  });
  const build = (occurrences: EventOccurrence[], calendarRange = week) => buildWidgetSnapshot({
    activeHome: HOME, occurrences, routines: [], reminders: [], calendarRange,
    now: new Date(2026, 8, 28, 12),
  });

  it("A: retains September and October dates in the same week", () => {
    const events = [allDay("2026-09-28", "2026-09-29"), allDay("2026-09-30", "2026-10-01"),
      allDay("2026-10-01", "2026-10-02"), allDay("2026-10-02", "2026-10-03"), allDay("2026-10-03", "2026-10-04")];
    expect(build(events).monthEvents.map((e) => e.id)).toEqual(events.map((e) => e.occurrence_id));
  });

  it("B/E: a 1–5 October exclusive trip covers only 1, 2, 3 and 4 October", () => {
    const trip = allDay("2026-10-01", "2026-10-05", "trip");
    expect(build([trip]).monthEvents).toHaveLength(1);
    for (let day = 1; day <= 5; day++) {
      expect(eventOverlapsWidgetRange(trip, visibleRange(`2026-10-0${day}`, `2026-10-0${day + 1}`))).toBe(day < 5);
    }
    expect(eventOverlapsWidgetRange(trip, visibleRange("2026-09-30", "2026-10-01"))).toBe(false);
  });

  it("C: excludes all-day and timed events on 5 October and those ending at the range start", () => {
    const events = [allDay("2026-10-05", "2026-10-06"), allDay("2026-09-27", "2026-09-28"),
      occurrence({ start_at: week.endAt, end_at: new Date(Date.parse(week.endAt) + 3600000).toISOString() }),
      occurrence({ start_at: new Date(Date.parse(week.startAt) - 3600000).toISOString(), end_at: week.startAt })];
    expect(build(events).monthEvents).toEqual([]);
  });

  it.each([
    ["2026-12-28", "2027-01-04", "2026-12-31", "2027-01-01", "2027-01-02"],
    ["2026-10-26", "2026-11-02", "2026-10-31", "2026-11-01", "2026-11-02"],
    ["2026-09-07", "2026-09-14", "2026-09-09", "2026-09-10", "2026-09-11"],
  ])("D/F: covers both years/months and ordinary weeks (%s)", (start, end, first, second, third) => {
    expect(build([allDay(first, second), allDay(second, third)], visibleRange(start, end)).monthEvents).toHaveLength(2);
  });

  it("retains timed multi-day events starting before the week", () => {
    const event = occurrence({ start_at: new Date(Date.parse(week.startAt) - 3600000).toISOString(),
      end_at: new Date(Date.parse(week.startAt) + 3600000).toISOString() });
    expect(build([event]).monthEvents).toHaveLength(1);
  });

  it("does not truncate the visible range at 250 events", () => {
    const events = Array.from({ length: 301 }, (_, i) => allDay("2026-10-01", "2026-10-02", `event-${i}`));
    expect(build(events).monthEvents).toHaveLength(301);
  });

  it("supports previous-month events when refreshed in October, and old-shell grid coverage", () => {
    const range = fallbackWidgetCalendarRange(new Date(2026, 9, 1, 12));
    expect(eventOverlapsWidgetRange(allDay("2026-09-28", "2026-09-29"), range)).toBe(true);
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [allDay("2026-10-01", "2026-10-02")],
      routines: [], reminders: [], now: new Date(2026, 9, 2, 0, 1) });
    expect(snapshot.todayEvents).toEqual([]);
  });
});

describe("buildWidgetSnapshot — To-do (routines + reminders)", () => {
  it("marks a routine due before today as overdue", () => {
    const overdue = routine({ id: "r-overdue", next_occurrence_date: "2026-09-01" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [overdue], reminders: [], now: NOW });
    expect(snapshot.todoItems[0]).toMatchObject({ id: "r-overdue", overdue: true });
  });

  it("marks a reminder due today as not overdue", () => {
    const dueToday = reminder({ id: "rem-today", next_occurrence_date: "2026-09-03" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [], reminders: [dueToday], now: NOW });
    expect(snapshot.todoItems[0]).toMatchObject({ id: "rem-today", overdue: false });
  });

  it("orders a future item after an overdue and a today item", () => {
    const future = routine({ id: "r-future", next_occurrence_date: "2026-09-10" });
    const today = reminder({ id: "rem-today", next_occurrence_date: "2026-09-03" });
    const overdue = routine({ id: "r-overdue", next_occurrence_date: "2026-08-20" });
    const snapshot = buildWidgetSnapshot({
      activeHome: HOME,
      occurrences: [],
      routines: [future, overdue],
      reminders: [today],
      now: NOW,
    });
    expect(snapshot.todoItems.map((i) => i.id)).toEqual(["r-overdue", "rem-today", "r-future"]);
  });

  it("excludes items completed today", () => {
    const completed = routine({ id: "r-done", completed_today: true });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [completed], reminders: [], now: NOW });
    expect(snapshot.todoItems).toEqual([]);
  });

  it("excludes a disabled routine/reminder", () => {
    const disabled = reminder({ id: "rem-disabled", enabled: false });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [], reminders: [disabled], now: NOW });
    expect(snapshot.todoItems).toEqual([]);
  });

  it("represents both a routine and a reminder with their own kind", () => {
    const r = routine({ id: "r-1" });
    const rem = reminder({ id: "rem-1" });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [r], reminders: [rem], now: NOW });
    const kinds = Object.fromEntries(snapshot.todoItems.map((i) => [i.id, i.kind]));
    expect(kinds["r-1"]).toBe("routine");
    expect(kinds["rem-1"]).toBe("reminder");
  });
});

describe("buildWidgetSnapshot — no secrets, schema", () => {
  it("never includes fields resembling tokens/credentials", () => {
    const snapshot = buildWidgetSnapshot({
      activeHome: HOME,
      occurrences: [occurrence({})],
      routines: [routine({})],
      reminders: [reminder({})],
      now: NOW,
    });
    const serialized = JSON.stringify(snapshot).toLowerCase();
    for (const forbidden of ["token", "password", "cookie", "secret", "pin", "bearer"]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it("stamps the current schema version", () => {
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [], routines: [], reminders: [], now: NOW });
    expect(snapshot.schemaVersion).toBe(WIDGET_SNAPSHOT_SCHEMA_VERSION);
  });
});
