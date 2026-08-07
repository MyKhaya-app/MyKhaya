import { describe, expect, it } from "vitest";
import type { BirthdayEntry } from "@mykhaya/shared-types";
import {
  birthdayDateLabel,
  daysUntilThisYear,
  isBirthdayThisMonthAndUpcoming,
  upcomingBirthdayIcon,
  upcomingBirthdayLabel,
} from "./birthday-utils";

function entry(overrides: Partial<BirthdayEntry>): BirthdayEntry {
  return {
    owner_type: "user",
    owner_id: crypto.randomUUID(),
    display_name: "Anthony Hales",
    month: 8,
    day: 24,
    next_occurrence_date: "2026-08-24",
    ...overrides,
  };
}

describe("isBirthdayThisMonthAndUpcoming", () => {
  it("includes a birthday later this month", () => {
    const now = new Date("2026-08-07T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 8, day: 24 }), now)).toBe(true);
  });

  it("excludes a birthday in a future month", () => {
    const now = new Date("2026-08-07T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 2, day: 14 }), now)).toBe(false);
  });

  it("excludes a birthday earlier this month that has already passed", () => {
    const now = new Date("2026-08-20T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 8, day: 7 }), now)).toBe(false);
  });

  it("includes today's birthday", () => {
    const now = new Date("2026-08-07T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 8, day: 7 }), now)).toBe(true);
  });

  it("handles the December -> January year boundary without using the birth year", () => {
    const now = new Date("2026-12-30T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 12, day: 31 }), now)).toBe(true);
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 1, day: 5 }), now)).toBe(false);
  });

  it("does not show a January birthday while still in December, even though it is 'next'", () => {
    const now = new Date("2026-12-15T09:00:00Z");
    expect(isBirthdayThisMonthAndUpcoming(entry({ month: 1, day: 3 }), now)).toBe(false);
  });
});

describe("daysUntilThisYear", () => {
  it("counts forward within the same year", () => {
    const now = new Date("2026-08-07T09:00:00Z");
    expect(daysUntilThisYear(entry({ month: 8, day: 24 }), now)).toBe(17);
  });

  it("is zero on the day itself", () => {
    const now = new Date("2026-08-24T09:00:00Z");
    expect(daysUntilThisYear(entry({ month: 8, day: 24 }), now)).toBe(0);
  });
});

describe("birthdayDateLabel", () => {
  it("formats month/day without a year", () => {
    expect(birthdayDateLabel(entry({ month: 8, day: 24 }))).toBe("24 August");
  });
});

describe("upcomingBirthdayLabel", () => {
  it("labels today, tomorrow, and further out distinctly", () => {
    expect(upcomingBirthdayLabel(0)).toBe("Today");
    expect(upcomingBirthdayLabel(1)).toBe("Tomorrow");
    expect(upcomingBirthdayLabel(17)).toBe("In 17 days");
  });
});

describe("upcomingBirthdayIcon", () => {
  it("escalates the icon as the date approaches", () => {
    expect(upcomingBirthdayIcon(0)).toBe("🎉");
    expect(upcomingBirthdayIcon(3)).toBe("🎁");
    expect(upcomingBirthdayIcon(17)).toBe("🎂");
  });
});
