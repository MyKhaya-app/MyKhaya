import { describe, expect, it } from "vitest";
import type { EventOccurrence, Home, Reminder, Routine } from "@mykhaya/shared-types";
import {
  WIDGET_SNAPSHOT_SCHEMA_VERSION,
  buildWidgetSnapshot,
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
    ...overrides,
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
      start_at: "2026-09-03T18:00:00.000Z",
      end_at: "2026-09-03T19:00:00.000Z",
    });
    const snapshot = buildWidgetSnapshot({ activeHome: HOME, occurrences: [laterToday], routines: [], reminders: [], now: NOW });
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

  it("excludes an event entirely in the following month", () => {
    const event = occurrence({ occurrence_id: "occ-october", start_at: "2026-10-05T09:00:00.000Z", end_at: "2026-10-05T10:00:00.000Z" });
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
