import { describe, expect, it } from "vitest";

import { daysFromToday, recentPlannedLabel } from "./recent-label";

const TODAY = "2026-10-14";

describe("recentPlannedLabel", () => {
  it("labels a meal planned for today", () => {
    expect(recentPlannedLabel("2026-10-14", TODAY)).toBe("Planned for today");
  });

  it("never labels a future plan as today (regression)", () => {
    expect(recentPlannedLabel("2026-10-15", TODAY)).toBe("Planned for tomorrow");
    expect(recentPlannedLabel("2026-10-20", TODAY)).toBe("Planned in 6 days");
    expect(recentPlannedLabel("2026-10-27", TODAY)).toBe("Planned in 13 days");
    expect(recentPlannedLabel("2026-11-04", TODAY)).toBe("Planned in 3 weeks");
  });

  it("keeps the existing wording for past plans", () => {
    expect(recentPlannedLabel("2026-10-13", TODAY)).toBe("Last planned Yesterday");
    expect(recentPlannedLabel("2026-10-09", TODAY)).toBe("Last planned 5 days ago");
    expect(recentPlannedLabel("2026-09-30", TODAY)).toBe("Last planned 2 weeks ago");
    expect(recentPlannedLabel("2026-09-23", TODAY)).toBe("Last planned 3 weeks ago");
  });

  it("uses whole calendar days across a clock change", () => {
    // UK clocks go back on 25 October 2026.
    expect(daysFromToday("2026-10-26", "2026-10-24")).toBe(2);
    expect(recentPlannedLabel("2026-10-26", "2026-10-24")).toBe("Planned in 2 days");
  });

  it("switches from days to weeks at two weeks", () => {
    expect(recentPlannedLabel("2026-10-21", "2026-10-07")).toBe("Planned in 2 weeks");
    expect(recentPlannedLabel("2026-10-14", "2026-10-28")).toBe("Last planned 2 weeks ago");
  });
});
