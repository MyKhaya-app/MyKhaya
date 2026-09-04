import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { contrastText, resolveColour } from "@mykhaya/design-tokens";
import { MonthView } from "./month-view";
import { monthCells } from "./calendar-utils";

// Focused coverage for the month-view density refinement: the "+N more"
// overflow threshold, multi-day events counting as a single lane (not one
// row per day), the dynamic 5-week/6-week row-count CSS variable, and solid
// (never faded) Calendar Tag colouring. Deliberately renders MonthView
// directly (not the whole CalendarPage) — same pattern as
// month-swipe-view.test.tsx — since none of this depends on data fetching.

function occurrence(overrides: Partial<EventOccurrence> & { occurrence_id: string }): EventOccurrence {
  return {
    event_id: overrides.occurrence_id,
    calendar_id: "cal-1",
    title: "Event",
    start_at: "2026-01-05T09:00:00Z",
    end_at: "2026-01-05T10:00:00Z",
    is_all_day: false,
    timezone: "UTC",
    description: null,
    location_text: null,
    label: null,
    calendar_color: "teal",
    member_ids: [],
    recurrence: "none",
    reminder_minutes: null,
    created_by: "u1",
    updated_at: "2026-01-01T00:00:00Z",
    is_overridden: false,
    ...overrides,
    occurrence_start: overrides.occurrence_start ?? overrides.start_at ?? "2026-01-05T09:00:00Z",
  };
}

const noop = () => {};

describe("MonthView — overflow threshold (MONTH_VISIBLE_ROW_CAP)", () => {
  // Jan 5, 2026 is a Monday, so this week runs Jan 5 (Mon) - Jan 11 (Sun).
  const focusDate = new Date(Date.UTC(2026, 0, 15));

  function sameDayEvents(count: number) {
    return Array.from({ length: count }, (_, index) =>
      occurrence({
        occurrence_id: `occ-${index}`,
        title: `Event ${index}`,
        start_at: `2026-01-05T0${index}:00:00Z`,
        end_at: `2026-01-05T0${index}:30:00Z`,
      }),
    );
  }

  it("shows all 5 events with no overflow indicator when a day has exactly the cap", () => {
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={sameDayEvents(5)}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    expect(container.querySelectorAll(".month-event")).toHaveLength(5);
    expect(container.querySelector(".overflow-events")).toBeNull();
  });

  it("collapses the 6th event on the same day into a '+1 more' indicator", () => {
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={sameDayEvents(6)}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    expect(container.querySelectorAll(".month-event")).toHaveLength(5);
    const overflow = container.querySelector(".overflow-events");
    expect(overflow).not.toBeNull();
    expect(overflow!.textContent).toBe("+1 more");
  });
});

describe("MonthView — multi-day events occupy one lane, not one row per day", () => {
  const focusDate = new Date(Date.UTC(2026, 0, 15));

  it("a multi-day span plus 4 single-day events fills the cap without overflowing", () => {
    const events = [
      occurrence({
        occurrence_id: "multi",
        title: "Multi day trip",
        start_at: "2026-01-05T00:00:00Z",
        end_at: "2026-01-08T00:00:00Z",
        is_all_day: true,
      }),
      ...["a", "b", "c", "d"].map((id, index) =>
        occurrence({
          occurrence_id: `single-${id}`,
          title: `Single ${id}`,
          start_at: `2026-01-06T0${index}:00:00Z`,
          end_at: `2026-01-06T0${index}:30:00Z`,
        }),
      ),
    ];
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={events}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    // 5 lanes total for the week (1 spanning + 4 single-day) — the spanning
    // event renders as exactly one bar, not once per day it covers.
    expect(container.querySelectorAll('[title*="Multi day trip"]')).toHaveLength(1);
    expect(container.querySelector(".overflow-events")).toBeNull();
  });

  it("a 6th event lands only the affected day into overflow, leaving the spanning bar's other days untouched", () => {
    const events = [
      occurrence({
        occurrence_id: "multi",
        title: "Multi day trip",
        start_at: "2026-01-05T00:00:00Z",
        end_at: "2026-01-08T00:00:00Z",
        is_all_day: true,
      }),
      ...["a", "b", "c", "d", "e"].map((id, index) =>
        occurrence({
          occurrence_id: `single-${id}`,
          title: `Single ${id}`,
          start_at: `2026-01-06T0${index}:00:00Z`,
          end_at: `2026-01-06T0${index}:30:00Z`,
        }),
      ),
    ];
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={events}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    // Still exactly one spanning bar for the multi-day event.
    expect(container.querySelectorAll('[title*="Multi day trip"]')).toHaveLength(1);
    const overflowButtons = Array.from(container.querySelectorAll(".overflow-events"));
    expect(overflowButtons).toHaveLength(1);
    expect(overflowButtons[0]!.textContent).toBe("+1 more");
    // Jan 1 2026 is a Thursday (lead=3 in the Monday-first grid), so the
    // second rendered week row is Jan 5 (Mon) - Jan 11 (Sun); Jan 6 is its
    // 2nd day cell, Jan 5 its 1st.
    const secondWeek = container.querySelectorAll(".calendar-week")[1]!;
    const daysInWeek = secondWeek.querySelectorAll(".calendar-day");
    const jan5 = daysInWeek[0]!;
    const jan6 = daysInWeek[1]!;
    expect(jan6.querySelector(".overflow-events")).not.toBeNull();
    expect(jan5.querySelector(".overflow-events")).toBeNull();
  });
});

describe("MonthView — multi-day priority under the density/overflow cap", () => {
  const focusDate = new Date(Date.UTC(2026, 0, 15));

  it("when a week has more events than MONTH_VISIBLE_ROW_CAP, multi-day events keep the visible lanes over single-day ones", () => {
    // 2 multi-day + 5 single-day = 7 lanes needed, but the cap is 5 — both
    // multi-day events must still render (never pushed into overflow),
    // and exactly 2 single-day events must be bumped into "+N more".
    const events = [
      occurrence({
        occurrence_id: "multi-a",
        title: "Multi A",
        start_at: "2026-01-05T00:00:00Z",
        end_at: "2026-01-07T00:00:00Z",
        is_all_day: true,
      }),
      occurrence({
        occurrence_id: "multi-b",
        title: "Multi B",
        start_at: "2026-01-06T00:00:00Z",
        end_at: "2026-01-09T00:00:00Z",
        is_all_day: true,
      }),
      ...["a", "b", "c", "d", "e"].map((id, index) =>
        occurrence({
          occurrence_id: `single-${id}`,
          title: `Single ${id}`,
          start_at: `2026-01-06T0${index}:00:00Z`,
          end_at: `2026-01-06T0${index}:30:00Z`,
        }),
      ),
    ];
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={events}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    // Total visible bars is still capped at 5 (unchanged density rule).
    expect(container.querySelectorAll(".month-event")).toHaveLength(5);
    // Both multi-day bars are among the visible ones.
    expect(container.querySelectorAll('[title="Multi A"]')).toHaveLength(1);
    expect(container.querySelectorAll('[title="Multi B"]')).toHaveLength(1);
    // Jan 6 (2nd day cell of the second rendered week row) is where every
    // single-day event lives, and where the 2 bumped ones surface as overflow.
    const secondWeek = container.querySelectorAll(".calendar-week")[1]!;
    const jan6 = secondWeek.querySelectorAll(".calendar-day")[1]!;
    const overflow = jan6.querySelector(".overflow-events");
    expect(overflow).not.toBeNull();
    expect(overflow!.textContent).toBe("+2 more");
  });
});

describe("MonthView — no blank rendered rows (corrective follow-up)", () => {
  const focusDate = new Date(Date.UTC(2026, 0, 15));

  it("a day with only a single-day event renders it at the topmost grid row, even though another day that week has a multi-day event in the top lane", () => {
    const events = [
      occurrence({
        occurrence_id: "multi-wed-thu",
        title: "Multi Wed-Thu",
        start_at: "2026-01-07T00:00:00Z", // Wednesday
        end_at: "2026-01-09T00:00:00Z",
        is_all_day: true,
      }),
      occurrence({
        occurrence_id: "monday-single",
        title: "Monday only",
        start_at: "2026-01-05T09:00:00Z", // Monday - never touched by the multi-day event
        end_at: "2026-01-05T10:00:00Z",
      }),
    ];
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={events}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    const mondayChip = Array.from(container.querySelectorAll(".month-event")).find(
      (el) => el.textContent?.includes("Monday only"),
    ) as HTMLElement;
    expect(mondayChip).toBeDefined();
    // Row 2 is the topmost event row (row 1 is the day-number row) - not
    // pushed down just because Wed/Thu's multi-day bar occupies row 2 too.
    expect(mondayChip.style.gridRow).toBe("2");
  });
});

describe("MonthView — dynamic 5-week vs 6-week row count", () => {
  it("renders 5 week rows, tagged via --calendar-week-count, for a month that only needs 5", () => {
    // January 2026: 31 days starting on a Thursday — fits in 5 Monday-first
    // calendar-week rows.
    const focusDate = new Date(Date.UTC(2026, 0, 15));
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={[]}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    expect(container.querySelectorAll(".calendar-week")).toHaveLength(5);
    const weeks = container.querySelector(".calendar-weeks") as HTMLElement;
    expect(weeks.style.getPropertyValue("--calendar-week-count")).toBe("5");
  });

  it("renders 6 week rows, tagged via --calendar-week-count, for a month that needs 6", () => {
    // March 2026: 31 days starting on a Sunday — spills into a 6th row.
    const focusDate = new Date(Date.UTC(2026, 2, 15));
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={[]}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    expect(container.querySelectorAll(".calendar-week")).toHaveLength(6);
    const weeks = container.querySelector(".calendar-weeks") as HTMLElement;
    expect(weeks.style.getPropertyValue("--calendar-week-count")).toBe("6");
  });
});

describe("MonthView — solid Calendar Tag colouring", () => {
  const focusDate = new Date(Date.UTC(2026, 0, 15));

  it("uses the Calendar Tag colour with an automatically contrasting text colour", () => {
    const tagColour = resolveColour("violet");
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={[
          occurrence({
            occurrence_id: "occ-1",
            title: "Tagged event",
            label: {
              id: "label-1",
              name: "Activity",
              color: "violet",
              is_active: true,
              sort_order: 1,
              commercial_access: "normal",
            },
          }),
        ]}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    const chip = container.querySelector(".month-event") as HTMLElement;
    expect(chip.style.getPropertyValue("--event-color")).toBe(tagColour);
    expect(chip.style.getPropertyValue("--event-text-color")).toBe(contrastText(tagColour));
  });

  it("falls back to the calendar's own colour when the event has no Calendar Tag", () => {
    const calendarColour = resolveColour("amber");
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={[
          occurrence({ occurrence_id: "occ-1", title: "Untagged event", calendar_color: "amber" }),
        ]}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    const chip = container.querySelector(".month-event") as HTMLElement;
    expect(chip.style.getPropertyValue("--event-color")).toBe(calendarColour);
    expect(chip.style.getPropertyValue("--event-text-color")).toBe(contrastText(calendarColour));
  });

  it("a multi-day span uses the same solid colour treatment as a single-day chip", () => {
    const tagColour = resolveColour("teal");
    const { container } = render(
      <MonthView
        cells={monthCells(focusDate)}
        events={[
          occurrence({
            occurrence_id: "multi",
            title: "Spanning trip",
            start_at: "2026-01-05T00:00:00Z",
            end_at: "2026-01-08T00:00:00Z",
            is_all_day: true,
            label: {
              id: "label-2",
              name: "Trips",
              color: "teal",
              is_active: true,
              sort_order: 1,
              commercial_access: "normal",
            },
          }),
        ]}
        focusDate={focusDate}
        timeZone="UTC"
        onDay={noop}
        onEvent={noop}
      />,
    );
    const bar = container.querySelector(".month-event.month-event-span") as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.style.getPropertyValue("--event-color")).toBe(tagColour);
    expect(bar.style.getPropertyValue("--event-text-color")).toBe(contrastText(tagColour));
  });
});
