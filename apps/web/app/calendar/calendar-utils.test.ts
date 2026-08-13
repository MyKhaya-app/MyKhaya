import { describe, expect, it } from "vitest";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { eventsForDay, monthCells } from "./calendar-utils";

function event(overrides: Partial<EventOccurrence>): EventOccurrence {
  return {
    occurrence_id: crypto.randomUUID(),
    event_id: crypto.randomUUID(),
    title: "Event",
    start_at: "2026-07-31T10:00:00+00:00",
    end_at: "2026-07-31T11:00:00+00:00",
    is_all_day: false,
    timezone: "Europe/London",
    description: null,
    location_text: null,
    label: null,
    member_ids: [],
    recurrence: "none",
    reminder_minutes: null,
    created_by: crypto.randomUUID(),
    updated_at: "2026-07-01T00:00:00+00:00",
    ...overrides,
  };
}

describe("Calendar presentation", () => {
  it("builds a stable six-week Monday-first month", () => {
    const cells = monthCells(new Date("2026-08-15T00:00:00Z"));
    expect(cells).toHaveLength(42);
    expect(cells[0]?.getUTCDay()).toBe(1);
    expect(
      cells.some((day) => day.toISOString().startsWith("2026-08-01")),
    ).toBe(true);
  });

  it("orders all-day events before timed events", () => {
    const rows = eventsForDay(
      [
        event({ title: "Later", start_at: "2026-07-31T15:00:00+00:00" }),
        event({
          title: "All day",
          is_all_day: true,
          start_at: "2026-07-31T00:00:00+00:00",
          end_at: "2026-08-01T00:00:00+00:00",
        }),
        event({ title: "Earlier", start_at: "2026-07-31T09:00:00+00:00" }),
      ],
      "2026-07-31",
    );
    expect(rows.map((row) => row.title)).toEqual([
      "All day",
      "Earlier",
      "Later",
    ]);
  });

  it("includes multi-day events on every covered date", () => {
    const multi = event({
      start_at: "2026-07-30T12:00:00+00:00",
      end_at: "2026-08-01T12:00:00+00:00",
    });
    expect(eventsForDay([multi], "2026-07-31")).toEqual([multi]);
  });
});
