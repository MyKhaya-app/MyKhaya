import { describe, expect, it } from "vitest";
import type { CalendarUsage, HomeCalendar } from "@mykhaya/shared-types";
import {
  atLimitMessage,
  calendarBadgeLabel,
  calendarIsWritable,
  canCreateCalendar,
  overLimitExplanation,
} from "./calendar-entitlement-logic";

function usage(overrides: Partial<CalendarUsage> = {}): CalendarUsage {
  return { count: 1, limit: 1, over_limit: false, ...overrides };
}

function calendar(overrides: Partial<HomeCalendar> = {}): HomeCalendar {
  return {
    id: "cal-1",
    name: "Home Calendar",
    timezone: "Europe/London",
    is_primary: true,
    owner_user_id: null,
    color: "teal",
    commercial_access: "normal",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("canCreateCalendar", () => {
  it("allows creation when unlimited", () => {
    expect(canCreateCalendar(usage({ count: 5, limit: null }))).toBe(true);
  });

  it("allows creation when below the limit", () => {
    expect(canCreateCalendar(usage({ count: 0, limit: 1 }))).toBe(true);
  });

  it("blocks creation at the limit", () => {
    expect(canCreateCalendar(usage({ count: 1, limit: 1 }))).toBe(false);
  });

  it("blocks creation over the limit", () => {
    expect(canCreateCalendar(usage({ count: 3, limit: 1 }))).toBe(false);
  });
});

describe("calendarBadgeLabel", () => {
  it("labels a read-only calendar", () => {
    expect(calendarBadgeLabel(calendar({ commercial_access: "read_only_due_to_plan" }))).toBe(
      "Read-only on Free",
    );
  });

  it("shows no badge for a normal calendar", () => {
    expect(calendarBadgeLabel(calendar({ commercial_access: "normal" }))).toBeNull();
  });
});

describe("calendarIsWritable", () => {
  it("is true for a normal calendar", () => {
    expect(calendarIsWritable(calendar({ commercial_access: "normal" }))).toBe(true);
  });

  it("is false for a restricted calendar", () => {
    expect(calendarIsWritable(calendar({ commercial_access: "read_only_due_to_plan" }))).toBe(
      false,
    );
  });
});

describe("atLimitMessage", () => {
  it("is null when there's still room", () => {
    expect(atLimitMessage(usage({ count: 0, limit: 1 }))).toBeNull();
  });

  it("is null when unlimited", () => {
    expect(atLimitMessage(usage({ count: 10, limit: null }))).toBeNull();
  });

  it("names the limit once reached, singular", () => {
    expect(atLimitMessage(usage({ count: 1, limit: 1 }))).toBe(
      "You've reached the Free plan limit of 1 event category.",
    );
  });

  it("names the limit once reached, plural", () => {
    expect(atLimitMessage(usage({ count: 2, limit: 2 }))).toBe(
      "You've reached the Free plan limit of 2 event categories.",
    );
  });
});

describe("overLimitExplanation", () => {
  it("is null when within the limit", () => {
    expect(overLimitExplanation(usage({ count: 1, limit: 1, over_limit: false }))).toBeNull();
  });

  it("explains the over-limit state without deleting anything or naming a price", () => {
    const message = overLimitExplanation(usage({ count: 3, limit: 1, over_limit: true }));
    expect(message).toBe(
      "Your Home has 3 event categories. The Free plan includes 1 category. " +
        "Your calendars and events are safe. Upgrade to Family to restore full access to all categories.",
    );
    expect(message).not.toMatch(/[£$€]/);
  });
});
