import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { localIsoDate, nudgeCardDateLabel, routineDueLabel } from "./routine-utils";

// Regression coverage for the Home "To do" card's due-date label. It used to
// compute "today" via `new Date().toISOString().slice(0, 10)` — an ISO
// string is always UTC, so for any Home not in UTC that could label a
// routine "Overdue" or roll it over to "Tomorrow" up to a day early/late
// around local midnight. localIsoDate()/routineDueLabel() use Date's local
// getters instead, matching the todayIso() convention already used by
// meal-plans/page.tsx and settings/routines/page.tsx.

describe("routineDueLabel — pure label logic", () => {
  it("returns 'Scheduled' when there is no occurrence date", () => {
    expect(routineDueLabel(null, "2026-08-21")).toBe("Scheduled");
    expect(routineDueLabel(undefined, "2026-08-21")).toBe("Scheduled");
  });

  it("returns 'Overdue' for a date before today", () => {
    expect(routineDueLabel("2026-08-20", "2026-08-21")).toBe("Overdue");
  });

  it("returns 'Today' for today's date", () => {
    expect(routineDueLabel("2026-08-21", "2026-08-21")).toBe("Today");
  });

  it("returns 'Tomorrow' for the day immediately after today", () => {
    expect(routineDueLabel("2026-08-22", "2026-08-21")).toBe("Tomorrow");
  });

  it("returns the raw date for anything further than tomorrow", () => {
    expect(routineDueLabel("2026-08-25", "2026-08-21")).toBe("2026-08-25");
  });

  it("handles a month/year boundary when computing 'tomorrow'", () => {
    expect(routineDueLabel("2027-01-01", "2026-12-31")).toBe("Tomorrow");
  });
});

describe("nudgeCardDateLabel — Home Nudges card's weekday-aware due-date line", () => {
  it("returns 'Scheduled' when there is no occurrence date", () => {
    expect(nudgeCardDateLabel(null, "2026-08-21")).toBe("Scheduled");
    expect(nudgeCardDateLabel(undefined, "2026-08-21")).toBe("Scheduled");
  });

  it("names today's actual weekday", () => {
    // 2026-08-21 is a Friday.
    expect(nudgeCardDateLabel("2026-08-21", "2026-08-21")).toBe("Today · Friday");
  });

  it("names tomorrow's actual weekday", () => {
    // 2026-08-22 is a Saturday.
    expect(nudgeCardDateLabel("2026-08-22", "2026-08-21")).toBe("Tomorrow · Saturday");
  });

  it("shows weekday and day/month for anything further than tomorrow, never a raw ISO date", () => {
    // 2026-08-25 is a Tuesday.
    expect(nudgeCardDateLabel("2026-08-25", "2026-08-21")).toBe("Tuesday · 25 Aug");
    expect(nudgeCardDateLabel("2026-08-25", "2026-08-21")).not.toContain("2026-08-25");
  });

  it("prefixes an overdue date with 'Overdue' and still names its actual weekday", () => {
    // 2026-08-20 is a Thursday.
    expect(nudgeCardDateLabel("2026-08-20", "2026-08-21")).toBe("Overdue · Thursday · 20 Aug");
  });

  it("handles a month/year boundary when computing 'tomorrow'", () => {
    // 2027-01-01 is a Friday.
    expect(nudgeCardDateLabel("2027-01-01", "2026-12-31")).toBe("Tomorrow · Friday");
  });
});

describe("localIsoDate — local-timezone date boundary", () => {
  const originalTz = process.env.TZ;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    process.env.TZ = originalTz;
  });

  it("uses the local calendar date, not the UTC date, near a local midnight boundary", () => {
    // UTC+14 (Pacific/Kiritimati) — local date is a full day ahead of UTC
    // for most of the day. 23:00 UTC on Jan 1 is already 13:00 local on
    // Jan 2 there.
    process.env.TZ = "Pacific/Kiritimati";
    vi.setSystemTime(new Date("2026-01-01T23:00:00Z"));

    expect(localIsoDate()).toBe("2026-01-02");
    // The bug this guards against: naively slicing toISOString() would give
    // the UTC date instead.
    expect(new Date().toISOString().slice(0, 10)).toBe("2026-01-01");
  });

  it("uses the local calendar date in a negative-offset timezone too", () => {
    // UTC-10 (Pacific/Honolulu) — local date lags UTC for most of the day.
    // 02:00 UTC on Jan 2 is still 16:00 local on Jan 1 there.
    process.env.TZ = "Pacific/Honolulu";
    vi.setSystemTime(new Date("2026-01-02T02:00:00Z"));

    expect(localIsoDate()).toBe("2026-01-01");
    expect(new Date().toISOString().slice(0, 10)).toBe("2026-01-02");
  });
});
