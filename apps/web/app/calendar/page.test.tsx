import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { resolveColour } from "@mykhaya/design-tokens";
import type { EventPayload, EventUpdatePayload } from "@mykhaya/shared-types";
import CalendarPage from "./page";
import { SETTLE_DURATION_MS } from "./use-month-swipe";

// Integration coverage for Month view navigation on the real, fully mounted
// calendar page — proves the existing Previous/Next buttons and the new
// swipe gesture both drive the same focusDate/heading, and that neither
// regressed the other. (Gesture-classification edge cases — short/vertical
// movement, reduced motion, mouse — are covered in isolation against
// MonthSwipeView directly in month-swipe-view.test.tsx.)

// A stable router object matters here specifically: CalendarPage's
// feature-check effect depends on `router` (via useRouter()), so a mock
// that returns a fresh object identity on every call would re-trigger that
// effect (and its "Checking Calendar access…" loading branch) on every
// unrelated re-render — including the focusDate updates this file's tests
// are asserting on — silently swapping in a brand-new heading DOM node.
const mockRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/calendar",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    // calendar.edit_all so the Edit action is reachable for the
    // Calendar/Calendar Tag edit-flow tests below — no existing test in
    // this file asserts on the Edit action being hidden.
    activeHome: {
      id: "home-1",
      name: "Hales Home",
      capabilities: ["calendar.edit_all", "calendar.delete"],
    },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      featureMatrix: vi.fn(),
      listEvents: vi.fn(),
      listLabels: vi.fn(),
      members: vi.fn(),
      listCalendars: vi.fn(),
      billingStatus: vi.fn(),
      birthdays: vi.fn(),
      sharedCalendars: vi.fn(),
      createEvent: vi.fn(),
      updateEvent: vi.fn(),
      deleteEvent: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan" });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "calendar", enabled: true }],
  });
  (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [{ id: "cal-1", is_primary: true, timezone: "UTC" }],
    personal_calendar: null,
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    shared_events_enabled: false,
  });
  (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
});

describe("Calendar — Month view navigation", () => {
  it("the Previous/Next buttons still move the month and keep the heading in sync", async () => {
    render(<CalendarPage />);

    const heading = await screen.findByRole("heading", { level: 1 });
    const initialLabel = heading.textContent;
    expect(initialLabel).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next period" }));
    await waitFor(() => expect(heading.textContent).not.toBe(initialLabel));
    const afterNext = heading.textContent;

    fireEvent.click(screen.getByRole("button", { name: "Previous period" }));
    await waitFor(() => expect(heading.textContent).toBe(initialLabel));
    expect(heading.textContent).not.toBe(afterNext);
  });

  it("a left swipe on the month grid navigates forward and updates the heading, same as Next", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CalendarPage />);

    const heading = await screen.findByRole("heading", { level: 1 });
    const initialLabel = heading.textContent;

    const swipeArea = document.querySelector(".calendar-month-swipe");
    expect(swipeArea).not.toBeNull();

    const pointerId = 1;
    const down = new Event("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(down, { pointerId, pointerType: "touch", clientX: 200, clientY: 200 });
    fireEvent(swipeArea!, down);

    const move = new Event("pointermove", { bubbles: true, cancelable: true });
    Object.assign(move, { pointerId, pointerType: "touch", clientX: 80, clientY: 200 });
    fireEvent(swipeArea!, move);

    const up = new Event("pointerup", { bubbles: true, cancelable: true });
    Object.assign(up, { pointerId, pointerType: "touch", clientX: 80, clientY: 200 });
    fireEvent(swipeArea!, up);

    act(() => {
      vi.advanceTimersByTime(SETTLE_DURATION_MS);
    });
    vi.useRealTimers();

    await waitFor(() => expect(heading.textContent).not.toBe(initialLabel));
  });
});

// Month View → Day List → Event Detail: every interaction with a day cell in
// Month view (blank space, the date number, an event chip, a multi-day bar,
// the overflow indicator) opens the Day List for that date first — never the
// event detail directly. Only selecting an event from within the Day List
// opens it. See month-view.tsx's own comments for the implementation.
describe("Calendar — Month view opens Day List first", () => {
  // Thursday 15 January 2026 — a fixed "today" so the current-day and
  // adjacent-month-day cases are deterministic regardless of when this
  // suite actually runs. January 2026 starts on a Thursday, so the first
  // rendered (Monday-first) week row is 29 Dec 2025 - 4 Jan 2026 — real
  // "outside" (previous-month) cells to exercise against.
  const TODAY = new Date("2026-01-15T09:00:00Z");

  beforeEach(() => {
    // Fake only Date, not setTimeout/setInterval — RTL's findBy*/waitFor
    // polling relies on real timers to ever resolve; faking those too (the
    // bare vi.useFakeTimers() default) would hang every async query below.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TODAY);
    // The member-filter test below persists its choice to localStorage (same
    // as Month view does for real), which would otherwise leak into later
    // tests' fresh CalendarPage renders and filter out their events.
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function occ(overrides: Record<string, unknown> = {}) {
    return {
      occurrence_id: "occ-1",
      event_id: "occ-1",
      calendar_id: "cal-1",
      title: "Sample event",
      start_at: "2026-01-15T09:00:00Z",
      end_at: "2026-01-15T10:00:00Z",
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
      ...overrides,
    };
  }

  function dayArticleFor(dateLabel: RegExp) {
    return screen.getByRole("button", { name: dateLabel });
  }

  it("1. tapping blank area of a populated day opens the Day List", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    await screen.findByText("Sample event");

    // The day article itself (blank space) — not the chip, not the number.
    fireEvent.click(dayArticleFor(/15 January 2026, 1 events/));

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });

  it("2. tapping the date number opens the Day List", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    await screen.findByText("Sample event");

    // MonthSwipeView renders the visible month plus two aria-hidden
    // peek panels, so "15" alone is ambiguous — scope through the one
    // uniquely-identified (by full date) day article instead.
    const dayNumber = dayArticleFor(/15 January 2026, 1 events/).querySelector(".day-number span")!;
    fireEvent.click(dayNumber);

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });

  it("3. tapping a normal event chip opens the Day List, not the event detail", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(await screen.findByText("Sample event"));

    const daySheet = await screen.findByRole("dialog");
    // The Day List, never the event view dialog, directly from Month view.
    expect(screen.queryByRole("dialog", { name: "Sample event" })).not.toBeInTheDocument();
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });

  it("4. tapping another event chip on the same date still opens that same date's Day List", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occ({ occurrence_id: "occ-1", event_id: "occ-1", title: "First event" }),
        occ({ occurrence_id: "occ-2", event_id: "occ-2", title: "Second event" }),
      ],
    });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(await screen.findByText("Second event"));

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /First event/ })).toBeInTheDocument();
    expect(within(daySheet).getByRole("button", { name: /Second event/ })).toBeInTheDocument();
  });

  it("5. selecting an event from the Day List opens Event Detail", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText("Sample event"));
    const daySheet = await screen.findByRole("dialog");

    fireEvent.click(within(daySheet).getByRole("button", { name: /Sample event/ }));

    expect(await screen.findByRole("dialog", { name: "Sample event" })).toBeInTheDocument();
  });

  it("6. tapping an empty day opens an empty Day List", async () => {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(dayArticleFor(/16 January 2026, 0 events/));

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByText("No events")).toBeInTheDocument();
  });

  it("7. Add event on this day uses the selected Day List date", async () => {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(dayArticleFor(/16 January 2026, 0 events/));
    const daySheet = await screen.findByRole("dialog");

    fireEvent.click(within(daySheet).getByRole("button", { name: "Add event on this day" }));

    const addDialog = await screen.findByRole("dialog", { name: "Add event" });
    const startDateInput = within(addDialog).getByLabelText<HTMLInputElement>("Date");
    expect(startDateInput.value).toBe("2026-01-16");
  });

  it("8. tapping the current (Today-highlighted) day opens today's Day List", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    const today = document.querySelector(".calendar-day.today") as HTMLElement;
    expect(today).not.toBeNull();
    fireEvent.click(today);

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });

  it("9. tapping an adjacent-month date resolves the full correct date, not just the displayed day number", async () => {
    // 29 Dec 2025 is an "outside" cell in January's first rendered week row
    // and shares its day-of-month number (29) with nothing in January
    // 2026's own dates near it — a naive "current month + this number"
    // resolution would misresolve this to some January date instead.
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [occ({ start_at: "2025-12-29T09:00:00Z", end_at: "2025-12-29T10:00:00Z" })],
    });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    // Not findByText("Sample event") here: MonthSwipeView's aria-hidden
    // previous-month peek panel genuinely re-renders 29 Dec in its own
    // (non-outside) grid too, and text queries — unlike getByRole, which
    // already correctly excludes aria-hidden content — don't filter that
    // out, so this waits via the same role-based, aria-hidden-safe query
    // the click itself uses.
    const cell = await screen.findByRole("button", { name: /29 December 2025, 1 events/ });

    fireEvent.click(cell);

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });

  it("10. tapping a multi-day event segment resolves the specific cell date clicked, not the event's start date", async () => {
    // 5-9 January 2026 (Mon-Fri) all fall in one rendered week row, so the
    // bar is one continuous element spanning 5 day columns — the exact
    // per-pixel resolution is covered directly and precisely in
    // calendar-utils.test.ts (resolveMultiDaySegmentDay); this proves the
    // wiring: clicking anywhere on the bar opens *a* Day List, never the
    // event detail directly, matching every other Month-view interaction.
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occ({
          title: "Multi-day trip",
          start_at: "2026-01-05T00:00:00Z",
          end_at: "2026-01-10T00:00:00Z",
          is_all_day: true,
        }),
      ],
    });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(await screen.findByText("Multi-day trip"));

    const daySheet = await screen.findByRole("dialog");
    expect(screen.queryByRole("dialog", { name: "Multi-day trip" })).not.toBeInTheDocument();
    expect(within(daySheet).getByRole("button", { name: /Multi-day trip/ })).toBeInTheDocument();
  });

  it("11. a recurring occurrence opens the Day List first, same as a normal event", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [occ({ title: "Weekly standup", recurrence: "weekly" })],
    });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(await screen.findByText("Weekly standup"));

    const daySheet = await screen.findByRole("dialog");
    expect(screen.queryByRole("dialog", { name: "Weekly standup" })).not.toBeInTheDocument();
    fireEvent.click(within(daySheet).getByRole("button", { name: /Weekly standup/ }));
    // Only after Day List selection does the recurrence-aware event detail
    // open — existing recurrence behaviour is otherwise untouched.
    expect(await screen.findByRole("dialog", { name: "Weekly standup" })).toBeInTheDocument();
  });

  it("12. clicking the date number does not open the Day List twice (no bubbling double-fire)", async () => {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });

    const dayNumber = dayArticleFor(/15 January 2026, 0 events/).querySelector(".day-number span")!;
    fireEvent.click(dayNumber);

    await screen.findByRole("dialog");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("13. the Day List reflects the same member filter currently applied to Month view", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      { user_id: "member-anthony", display_name: "Anthony", colour: null, avatar_version: null },
      { user_id: "member-megan", display_name: "Megan", colour: null, avatar_version: null },
    ]);
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occ({
          occurrence_id: "occ-anthony",
          event_id: "occ-anthony",
          title: "Anthony's event",
          member_ids: ["member-anthony"],
        }),
        occ({
          occurrence_id: "occ-megan",
          event_id: "occ-megan",
          title: "Megan's event",
          member_ids: ["member-megan"],
        }),
      ],
    });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    await screen.findByText("Anthony's event");

    fireEvent.change(screen.getByLabelText("Filter by household member"), {
      target: { value: "member-anthony" },
    });
    await waitFor(() => expect(screen.queryByText("Megan's event")).not.toBeInTheDocument());

    fireEvent.click(dayArticleFor(/15 January 2026, 1 events/));

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Anthony's event/ })).toBeInTheDocument();
    expect(within(daySheet).queryByRole("button", { name: /Megan's event/ })).not.toBeInTheDocument();
  });

  it("14. the day cell opens the Day List via keyboard (Enter) as well as click", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [occ()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    await screen.findByText("Sample event");

    const cell = dayArticleFor(/15 January 2026, 1 events/);
    cell.focus();
    fireEvent.keyDown(cell, { key: "Enter" });

    const daySheet = await screen.findByRole("dialog");
    expect(within(daySheet).getByRole("button", { name: /Sample event/ })).toBeInTheDocument();
  });
});

// Regression coverage for the Calendars visibility/filter sheet's row layout
// (see app/styles.css's .calendar-visibility-* rules) — the calendar name
// previously used `overflow-wrap: anywhere`, which on a content-sized flex
// item collapses to a near-one-character-wide column instead of growing to
// fill the row (see the CSS comment for the exact mechanism). JSDOM doesn't
// compute real layout, so these assert the *structural* fix instead: each
// row is a fixed-dot / flexible-name / fixed-switch triple, the name is a
// single, ellipsis-truncatable element (not a wrapping one), and the native
// checkbox was replaced with the app's existing `.switch` control.
describe("Calendar — Calendars visibility sheet", () => {
  beforeEach(() => {
    // Visibility toggles persist to localStorage (see HIDDEN_CALENDARS_STORAGE
    // in app/calendar/page.tsx) — cleared per test so one test's toggle can
    // never leak into the next test's initial state.
    window.localStorage.clear();
  });

  async function openCalendarsSheet() {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Calendars" }));
    return screen.findByRole("dialog", { name: "Calendars" });
  }

  it("renders Home and Personal calendars as horizontal rows with a switch, not a bare checkbox", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "cal-1", name: "Hales Home", is_primary: true, timezone: "UTC", color: "teal" }],
      personal_calendar: { id: "cal-personal", owner_user_id: "u1", is_primary: false, timezone: "UTC", color: "sage" },
    });

    const dialog = await openCalendarsSheet();
    const homeRow = within(dialog).getByText("Hales Home").closest("label");
    const personalRow = within(dialog).getByText("Personal calendar").closest("label");
    expect(homeRow).not.toBeNull();
    expect(personalRow).not.toBeNull();

    for (const row of [homeRow!, personalRow!]) {
      expect(row.className).toContain("calendar-visibility-row");
      const dot = row.querySelector(".calendar-visibility-dot");
      const name = row.querySelector(".calendar-visibility-name");
      const toggle = within(row as HTMLElement).getByRole("switch");
      expect(dot).not.toBeNull();
      expect(name).not.toBeNull();
      // The switch (not a bare checkbox) is the reused MyKhaya toggle — see
      // EventForm's "All day" control, same className/role/aria-checked shape.
      expect(toggle).toHaveClass("switch");
      expect(toggle).toHaveAttribute("type", "checkbox");
    }
  });

  it("keeps the calendar name on a single, ellipsis-truncatable line rather than wrapping", async () => {
    const longName = "A very long shared family calendar name that should truncate cleanly";
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          calendar_name: longName,
          calendar_color: "rose",
          source_group_name: "Smith Home",
          permission: "view",
        },
      ],
    });

    const dialog = await openCalendarsSheet();
    const nameEl = await within(dialog).findByText(longName);
    // The single-line ellipsis class, not a wrapping/overflow-wrap one —
    // this is the actual regression fix: see the CSS comment on
    // .calendar-visibility-name for why `overflow-wrap: anywhere` could
    // collapse this element to ~1 character wide.
    expect(nameEl).toHaveClass("calendar-visibility-name-primary");
    const container = nameEl.closest(".calendar-visibility-name");
    expect(container?.className).not.toMatch(/overflow-wrap/);
  });

  it("shows a 'Shared with you' section only when the user has shared calendars, alongside My calendars", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "cal-1", name: "Hales Home", is_primary: true, timezone: "UTC", color: "teal" }],
      personal_calendar: null,
    });
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          calendar_name: "Mum & Dad",
          calendar_color: "rose",
          source_group_name: "Smith Home",
          permission: "view",
        },
      ],
    });

    const dialog = await openCalendarsSheet();
    expect(within(dialog).getByText("My calendars")).toBeInTheDocument();
    expect(within(dialog).getByText("Shared with you")).toBeInTheDocument();
    expect(within(dialog).getByText("Mum & Dad")).toBeInTheDocument();
    expect(within(dialog).getByText("Smith Home")).toBeInTheDocument();
  });

  it("omits the 'Shared with you' section entirely when nothing is shared", async () => {
    const dialog = await openCalendarsSheet();
    expect(within(dialog).queryByText("Shared with you")).not.toBeInTheDocument();
  });

  it("toggling one calendar's visibility does not affect the others", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "cal-1", name: "Hales Home", is_primary: true, timezone: "UTC", color: "teal" }],
      personal_calendar: { id: "cal-personal", owner_user_id: "u1", is_primary: false, timezone: "UTC", color: "sage" },
    });

    const dialog = await openCalendarsSheet();
    const homeToggle = within(
      within(dialog).getByText("Hales Home").closest("label") as HTMLElement,
    ).getByRole("switch");
    const personalToggle = within(
      within(dialog).getByText("Personal calendar").closest("label") as HTMLElement,
    ).getByRole("switch");
    expect(homeToggle).toBeChecked();
    expect(personalToggle).toBeChecked();

    fireEvent.click(homeToggle);
    await waitFor(() => expect(homeToggle).not.toBeChecked());
    expect(personalToggle).toBeChecked();
  });
});

// Calendar vs Calendar Tag on Add/Edit Event — regression coverage for the
// terminology/UI split: "Calendar" (where the event lives — Home Calendar,
// a secondary Home calendar like GFOAT, Personal calendar, a writable
// shared calendar) is a completely separate control from "Calendar Tag"
// (CalendarEventLabel — a colour/category tag), and only actual writable
// calendars ever appear as Calendar destinations.
describe("Calendar — Add/Edit Event: Calendar vs Calendar Tag", () => {
  const primaryCalendar = {
    id: "cal-1",
    name: "Home Calendar",
    timezone: "UTC",
    is_primary: true,
    owner_user_id: null,
    color: "teal",
    commercial_access: "normal" as const,
  };
  const secondaryCalendar = {
    id: "cal-2",
    name: "GFOAT",
    timezone: "UTC",
    is_primary: false,
    owner_user_id: null,
    color: "coral",
    commercial_access: "normal" as const,
  };
  const personalCalendar = {
    id: "cal-personal",
    name: "Personal calendar",
    timezone: "UTC",
    is_primary: false,
    owner_user_id: "u1",
    color: "sage",
    commercial_access: "normal" as const,
  };
  const activityTag = {
    id: "label-activity",
    name: "Activity",
    color: "violet",
    is_active: true,
    sort_order: 1,
    commercial_access: "normal" as const,
  };

  function existingEvent(overrides: Record<string, unknown> = {}) {
    const start = new Date();
    return {
      occurrence_id: "occ-1",
      event_id: "event-1",
      calendar_id: secondaryCalendar.id,
      title: "Football",
      start_at: start.toISOString(),
      end_at: new Date(start.getTime() + 3_600_000).toISOString(),
      is_all_day: false,
      timezone: "UTC",
      description: null,
      location_text: null,
      label: activityTag,
      calendar_color: secondaryCalendar.color,
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: "u1",
      updated_at: "2026-08-01T00:00:00Z",
      ...overrides,
    };
  }

  beforeEach(() => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar, secondaryCalendar],
      personal_calendar: personalCalendar,
    });
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([activityTag]);
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      { user_id: "member-anthony", display_name: "Anthony", colour: null, avatar_version: null },
    ]);
  });

  async function openAddEventSheet() {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Add calendar event" }));
    return screen.findByRole("dialog", { name: "Add event" });
  }

  // Month view → Day List → Event Detail: the "Football" month chip now
  // opens the Day List first (see month-view.tsx), not the event directly —
  // this helper follows the same two-step path a real user takes, rather
  // than reaching into the event view dialog in one click as it used to.
  async function openEditEventSheet() {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [existingEvent()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText("Football"));
    const daySheet = await screen.findByRole("dialog");
    fireEvent.click(within(daySheet).getByRole("button", { name: /Football/ }));
    const viewDialog = await screen.findByRole("dialog", { name: "Football" });
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    return screen.findByRole("dialog", { name: "Edit event" });
  }

  it("shows separate Calendar and Calendar Tag fields when adding an event", async () => {
    const dialog = await openAddEventSheet();
    expect(within(dialog).getByLabelText("Calendar")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Calendar Tag")).toBeInTheDocument();
  });

  it("shows separate Calendar and Calendar Tag fields when editing an event", async () => {
    const dialog = await openEditEventSheet();
    const calendarSelect = within(dialog).getByLabelText<HTMLSelectElement>("Calendar");
    const tagSelect = within(dialog).getByLabelText<HTMLSelectElement>("Calendar Tag");
    expect(calendarSelect.value).toBe(secondaryCalendar.id);
    expect(tagSelect.value).toBe(activityTag.id);
  });

  it("the Calendar picker lists Home Calendar and a secondary Home calendar like GFOAT", async () => {
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).getByText("Home calendar")).toBeInTheDocument();
    expect(within(calendarSelect).getByText("GFOAT")).toBeInTheDocument();
  });

  it("the Calendar picker lists Personal calendar for its owner", async () => {
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).getByText("Personal calendar")).toBeInTheDocument();
  });

  it("a writable (manage) shared calendar appears in the Calendar picker", async () => {
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          calendar_name: "Grandma's calendar",
          calendar_color: "rose",
          source_group_name: "Smith Home",
          permission: "manage",
        },
      ],
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).getByText(/Grandma's calendar.*Smith Home/)).toBeInTheDocument();
  });

  it("a read-only (view) shared calendar never appears as a writable destination", async () => {
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-2",
          calendar_name: "Read-only calendar",
          calendar_color: "rose",
          source_group_name: "Smith Home",
          permission: "view",
        },
      ],
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).queryByText(/Read-only calendar/)).not.toBeInTheDocument();
  });

  it("household member names never appear in the Calendar picker merely because they are members", async () => {
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).queryByText("Anthony")).not.toBeInTheDocument();
  });

  it("existing Calendar Tags appear in the Calendar Tag picker", async () => {
    const dialog = await openAddEventSheet();
    const tagSelect = within(dialog).getByLabelText("Calendar Tag");
    expect(within(tagSelect).getByText("No tag")).toBeInTheDocument();
    expect(within(tagSelect).getByText("Activity")).toBeInTheDocument();
  });

  it("selecting a Calendar persists the correct calendar_id, independent of the Calendar Tag", async () => {
    const dialog = await openAddEventSheet();
    fireEvent.change(within(dialog).getByLabelText("Title"), { target: { value: "Match day" } });
    fireEvent.change(within(dialog).getByLabelText("Calendar"), {
      target: { value: secondaryCalendar.id },
    });
    fireEvent.change(within(dialog).getByLabelText("Calendar Tag"), {
      target: { value: activityTag.id },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /save event/i }));

    await waitFor(() => expect(api.createEvent).toHaveBeenCalled());
    const [, payload] = (api.createEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      EventPayload,
    ];
    expect(payload).toMatchObject({ calendar_id: secondaryCalendar.id, label_id: activityTag.id });
  });

  it("selecting Personal calendar together with a Calendar Tag keeps both — a tag never changes calendar access", async () => {
    const dialog = await openAddEventSheet();
    fireEvent.change(within(dialog).getByLabelText("Title"), { target: { value: "Nap time" } });
    fireEvent.change(within(dialog).getByLabelText("Calendar"), {
      target: { value: "__personal__" },
    });
    fireEvent.change(within(dialog).getByLabelText("Calendar Tag"), {
      target: { value: activityTag.id },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /save event/i }));

    await waitFor(() => expect(api.createEvent).toHaveBeenCalled());
    const [, payload] = (api.createEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      EventPayload,
    ];
    expect(payload).toMatchObject({
      calendar_id: personalCalendar.id,
      label_id: activityTag.id,
      member_ids: [],
    });
  });

  it("the Calendar field is fixed (disabled) when editing — only Calendar Tag can change", async () => {
    const dialog = await openEditEventSheet();
    const calendarSelect = within(dialog).getByLabelText<HTMLSelectElement>("Calendar");
    expect(calendarSelect).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText("Calendar Tag"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(api.updateEvent).toHaveBeenCalled());
    const [, , payload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    expect(payload).toMatchObject({ label_id: null });
    expect(payload).not.toHaveProperty("calendar_id");
  });

  it("the event chip's colour comes from its Calendar Tag, not the calendar it lives on", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [existingEvent()] });
    render(<CalendarPage />);
    await screen.findByText("Football");

    const chip = document.querySelector(".month-event") as HTMLElement;
    expect(chip).not.toBeNull();
    const eventColour = chip.style.getPropertyValue("--event-color");
    expect(eventColour).toBe(resolveColour(activityTag.color));
    expect(eventColour).not.toBe(resolveColour(secondaryCalendar.color));
  });
});

// Phase 2D: the Calendar picker must never offer a calendar the backend has
// already marked read_only_due_to_plan (preserved past a Family-to-Free
// downgrade — see mykhaya.routers.calendar._calendar_access/
// _personal_calendar_access) as a *new* destination, matching the same
// "locked, disabled option" pattern this file already covers for a
// view-only externally shared calendar. An event already assigned to a
// now-restricted calendar must still show that assignment — the Calendar
// field is disabled entirely on edit (see "the Calendar field is fixed"
// above), so the value is preserved without offering a mutation.
describe("Calendar — Add/Edit Event: plan-restricted calendars are not offered", () => {
  const primaryCalendar = {
    id: "cal-1",
    name: "Home Calendar",
    timezone: "UTC",
    is_primary: true,
    owner_user_id: null,
    color: "teal",
    commercial_access: "normal" as const,
  };
  const secondaryCalendar = {
    id: "cal-2",
    name: "GFOAT",
    timezone: "UTC",
    is_primary: false,
    owner_user_id: null,
    color: "coral",
    commercial_access: "normal" as const,
  };
  const personalCalendar = {
    id: "cal-personal",
    name: "Personal calendar",
    timezone: "UTC",
    is_primary: false,
    owner_user_id: "u1",
    color: "sage",
    commercial_access: "normal" as const,
  };

  beforeEach(() => {
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      { user_id: "member-anthony", display_name: "Anthony", colour: null, avatar_version: null },
    ]);
  });

  async function openAddEventSheet() {
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Add calendar event" }));
    return screen.findByRole("dialog", { name: "Add event" });
  }

  it("a read-only (plan-restricted) Personal Calendar cannot be selected", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar],
      personal_calendar: { ...personalCalendar, commercial_access: "read_only_due_to_plan" },
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    const option = within(calendarSelect).getByText(/Personal calendar/).closest("option")!;
    expect(option).toBeDisabled();
    expect(option.textContent).toContain("(Family)");
  });

  it("a read-only (plan-restricted) Home calendar cannot be selected", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar, { ...secondaryCalendar, commercial_access: "read_only_due_to_plan" }],
      personal_calendar: personalCalendar,
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    const option = within(calendarSelect).getByText(/GFOAT/).closest("option")!;
    expect(option).toBeDisabled();
    expect(option.textContent).toContain("(Family)");
  });

  it("a writable Personal Calendar and writable Home calendar both stay selectable (Family/unrestricted behaviour unchanged)", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar, secondaryCalendar],
      personal_calendar: personalCalendar,
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText("Calendar");
    expect(within(calendarSelect).getByText("Home calendar").closest("option")).not.toBeDisabled();
    expect(within(calendarSelect).getByText("GFOAT").closest("option")).not.toBeDisabled();
    expect(
      within(calendarSelect).getByText(/Personal calendar/).closest("option"),
    ).not.toBeDisabled();
  });

  it("defaults a new event to the Personal Calendar when the primary Home calendar is read-only due to plan (Free retained-member behaviour)", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ ...primaryCalendar, commercial_access: "read_only_due_to_plan" }],
      personal_calendar: personalCalendar,
    });
    const dialog = await openAddEventSheet();
    const calendarSelect = within(dialog).getByLabelText<HTMLSelectElement>("Calendar");
    expect(calendarSelect.value).toBe("__personal__");
  });

  it("editing an existing event on a now-read-only calendar still shows it as the current selection, without allowing a new invalid target", async () => {
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar, { ...secondaryCalendar, commercial_access: "read_only_due_to_plan" }],
      personal_calendar: personalCalendar,
    });
    const restrictedEvent = {
      occurrence_id: "occ-1",
      event_id: "event-1",
      calendar_id: secondaryCalendar.id,
      title: "Football",
      start_at: new Date().toISOString(),
      end_at: new Date(Date.now() + 3_600_000).toISOString(),
      is_all_day: false,
      timezone: "UTC",
      description: null,
      location_text: null,
      label: null,
      calendar_color: secondaryCalendar.color,
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: "u1",
      updated_at: "2026-08-01T00:00:00Z",
    };
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [restrictedEvent] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText("Football"));
    const daySheet = await screen.findByRole("dialog");
    fireEvent.click(within(daySheet).getByRole("button", { name: /Football/ }));
    const viewDialog = await screen.findByRole("dialog", { name: "Football" });
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit event" });

    const calendarSelect = within(dialog).getByLabelText<HTMLSelectElement>("Calendar");
    // Still shown as the event's current calendar — never silently moved —
    // and the whole field stays disabled on edit (its own dedicated test
    // above), so there is no path to re-submit it against a new, invalid
    // target either.
    expect(calendarSelect.value).toBe(secondaryCalendar.id);
    expect(calendarSelect).toBeDisabled();
  });
});

// Coverage for the recurring-event edit/delete scope chooser: an occurrence
// belonging to a recurring series must offer "This occurrence only / This
// and future occurrences / Entire series" (edit) or the matching delete
// wording, before anything is sent to the API — while a non-recurring event
// keeps its old, immediate Save/Delete behaviour untouched.
describe("Calendar — Recurring event scope chooser", () => {
  const primaryCalendar = {
    id: "cal-1",
    name: "Home Calendar",
    timezone: "UTC",
    is_primary: true,
    owner_user_id: null,
    color: "teal",
    commercial_access: "normal" as const,
  };

  beforeEach(() => {
    // Calendar visibility (and the other calendar-page prefs below) persist
    // in localStorage — jsdom does not reset it between tests, so an
    // earlier describe block's "hide this calendar" toggle would otherwise
    // silently hide cal-1's events here too.
    window.localStorage.clear();
    (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [primaryCalendar],
      personal_calendar: null,
    });
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    window.confirm = vi.fn(() => true);
  });

  // A moved+overridden occurrence: its canonical identity ("occurrence_start")
  // is 2026-09-15T18:00:00Z, but it now displays at a different effective
  // time/title ("start_at" / "title") after a prior "This occurrence only"
  // edit — exactly the re-edit scenario the task calls out explicitly.
  function movedOccurrence(overrides: Record<string, unknown> = {}) {
    return {
      occurrence_id: "occ-2026-09-15",
      event_id: "event-swim",
      calendar_id: primaryCalendar.id,
      title: "Family Swimming",
      start_at: "2026-09-16T19:00:00Z",
      end_at: "2026-09-16T20:00:00Z",
      occurrence_start: "2026-09-15T18:00:00Z",
      is_overridden: true,
      is_all_day: false,
      timezone: "UTC",
      description: null,
      location_text: null,
      label: null,
      calendar_color: primaryCalendar.color,
      member_ids: [],
      recurrence: "weekly",
      recurrence_interval: 1,
      reminder_minutes: null,
      created_by: "u1",
      updated_at: "2026-08-01T00:00:00Z",
      ...overrides,
    };
  }

  function nonRecurringEvent(overrides: Record<string, unknown> = {}) {
    return {
      occurrence_id: "occ-solo",
      event_id: "event-solo",
      calendar_id: primaryCalendar.id,
      title: "Dentist",
      start_at: "2026-09-10T09:00:00Z",
      end_at: "2026-09-10T10:00:00Z",
      occurrence_start: "2026-09-10T09:00:00Z",
      is_overridden: false,
      is_all_day: false,
      timezone: "UTC",
      description: null,
      location_text: null,
      label: null,
      calendar_color: primaryCalendar.color,
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: "u1",
      updated_at: "2026-08-01T00:00:00Z",
      ...overrides,
    };
  }

  // Month view → Day List → Event Detail: the chip no longer opens the
  // event dialog directly (see month-view.tsx) — go via the Day List, same
  // as a real user, rather than reaching the dialog in one click.
  async function openEventDialog(event: Record<string, unknown>) {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [event] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText(event.title as string));
    const daySheet = await screen.findByRole("dialog");
    fireEvent.click(within(daySheet).getByRole("button", { name: new RegExp(event.title as string) }));
    return screen.findByRole("dialog", { name: event.title as string });
  }

  it("a non-recurring event's Save/Delete are unaffected — no chooser appears", async () => {
    const viewDialog = await openEventDialog(nonRecurringEvent());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });

    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(1));
    const [, , payload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    expect(payload).not.toHaveProperty("scope");
    expect(payload).not.toHaveProperty("occurrence_start");
    expect(screen.queryByRole("dialog", { name: "Apply changes to" })).toBeNull();
  });

  it("a non-recurring event's Delete still uses the existing confirm() flow, no scope chooser", async () => {
    const viewDialog = await openEventDialog(nonRecurringEvent());
    fireEvent.click(within(viewDialog).getByRole("button", { name: /delete event/i }));

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(api.deleteEvent).toHaveBeenCalledTimes(1));
    expect(api.deleteEvent).toHaveBeenCalledWith("home-1", "event-solo");
    expect(screen.queryByRole("dialog", { name: "Delete recurring event" })).toBeNull();
  });

  it("Save on a recurring occurrence opens the scope chooser and sends no request before a choice", async () => {
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });

    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));

    const chooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    expect(api.updateEvent).not.toHaveBeenCalled();
    expect(within(chooser).getByRole("button", { name: "This occurrence only" })).toBeInTheDocument();
    expect(
      within(chooser).getByRole("button", { name: "This and future occurrences" }),
    ).toBeInTheDocument();
    expect(within(chooser).getByRole("button", { name: "Entire series" })).toBeInTheDocument();

    // Cancel makes no API request and returns to the editor's edits intact.
    fireEvent.click(within(chooser).getByRole("button", { name: "Cancel" }));
    expect(api.updateEvent).not.toHaveBeenCalled();
    await screen.findByRole("dialog", { name: "Edit event" });
  });

  it("choosing 'This occurrence only' sends the canonical occurrence_start, not the moved start_at", async () => {
    (api.updateEvent as ReturnType<typeof vi.fn>).mockResolvedValue(movedOccurrence());
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });
    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));

    const chooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    fireEvent.click(within(chooser).getByRole("button", { name: "This occurrence only" }));

    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(1));
    const [, , payload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    expect(payload.scope).toBe("occurrence");
    // Canonical identity, never the effective/moved start_at.
    expect(payload.occurrence_start).toBe("2026-09-15T18:00:00Z");
    expect(payload.occurrence_start).not.toBe("2026-09-16T19:00:00Z");
  });

  it("choosing 'This and future occurrences' sends scope=future with the canonical occurrence_start", async () => {
    (api.updateEvent as ReturnType<typeof vi.fn>).mockResolvedValue(movedOccurrence());
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });
    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));

    const chooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    fireEvent.click(within(chooser).getByRole("button", { name: "This and future occurrences" }));

    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(1));
    const [, , payload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    expect(payload.scope).toBe("future");
    expect(payload.occurrence_start).toBe("2026-09-15T18:00:00Z");
  });

  it("choosing 'Entire series' sends scope=series", async () => {
    (api.updateEvent as ReturnType<typeof vi.fn>).mockResolvedValue(movedOccurrence());
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });
    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));

    const chooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    fireEvent.click(within(chooser).getByRole("button", { name: "Entire series" }));

    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(1));
    const [, , payload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[0]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    // "series" is the backend's default scope, so toEventUpdatePayload omits
    // it rather than sending it redundantly — either an explicit "series" or
    // no scope field at all is a correct payload for this choice.
    expect(payload.scope === undefined || payload.scope === "series").toBe(true);
    expect(payload).not.toHaveProperty("occurrence_start");
  });

  it("Delete on a recurring occurrence opens a matching delete chooser, no request before a choice, and Cancel sends none", async () => {
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: /delete event/i }));

    const chooser = await screen.findByRole("dialog", { name: "Delete recurring event" });
    expect(api.deleteEvent).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
    expect(within(chooser).getByRole("button", { name: "Delete this occurrence" })).toBeInTheDocument();
    expect(
      within(chooser).getByRole("button", { name: "Delete this and future occurrences" }),
    ).toBeInTheDocument();
    expect(within(chooser).getByRole("button", { name: "Delete entire series" })).toBeInTheDocument();

    fireEvent.click(within(chooser).getByRole("button", { name: "Cancel" }));
    expect(api.deleteEvent).not.toHaveBeenCalled();
    await screen.findByRole("dialog", { name: "Family Swimming" });
  });

  it("the delete chooser's destructive options carry the recurrence-delete-menu contrast fix, Cancel does not", async () => {
    // button.danger (global) gives .sheet-menu-item.danger buttons a dark
    // red background; without the .recurrence-delete-menu scoped override
    // in styles.css, their text stays the low-contrast --colour-danger red
    // instead of white. This asserts the markup that override targets is
    // actually present, so a future refactor can't silently drop it.
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: /delete event/i }));
    const chooser = await screen.findByRole("dialog", { name: "Delete recurring event" });

    const nav = chooser.querySelector("nav.sheet-menu");
    expect(nav).not.toBeNull();
    expect(nav).toHaveClass("recurrence-delete-menu");

    for (const label of [
      "Delete this occurrence",
      "Delete this and future occurrences",
      "Delete entire series",
    ]) {
      const button = within(chooser).getByRole("button", { name: label });
      expect(button).toHaveClass("sheet-menu-item", "danger");
    }
    const cancelButton = within(chooser).getByRole("button", { name: "Cancel" });
    expect(cancelButton).toHaveClass("sheet-menu-item");
    expect(cancelButton).not.toHaveClass("danger");
  });

  it("choosing 'Delete this occurrence' sends scope=occurrence with the canonical occurrence_start", async () => {
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: /delete event/i }));
    const chooser = await screen.findByRole("dialog", { name: "Delete recurring event" });
    fireEvent.click(within(chooser).getByRole("button", { name: "Delete this occurrence" }));

    await waitFor(() => expect(api.deleteEvent).toHaveBeenCalledTimes(1));
    expect(api.deleteEvent).toHaveBeenCalledWith(
      "home-1",
      "event-swim",
      "occurrence",
      "2026-09-15T18:00:00Z",
    );
  });

  it("a failed occurrence edit keeps the chooser recoverable and does not silently fall back to series scope", async () => {
    (api.updateEvent as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(movedOccurrence());
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: "Edit" }));
    const editDialog = await screen.findByRole("dialog", { name: "Edit event" });
    fireEvent.click(within(editDialog).getByRole("button", { name: /save changes/i }));

    const chooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    fireEvent.click(within(chooser).getByRole("button", { name: "This occurrence only" }));

    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(1));
    // The chooser is still open (not silently dismissed/escalated) and the
    // user can retry the same choice.
    const reopenedChooser = await screen.findByRole("dialog", { name: "Apply changes to" });
    await waitFor(() => expect(within(reopenedChooser).getByRole("alert")).toBeInTheDocument());

    fireEvent.click(within(reopenedChooser).getByRole("button", { name: "This occurrence only" }));
    await waitFor(() => expect(api.updateEvent).toHaveBeenCalledTimes(2));
    const [, , secondPayload] = (api.updateEvent as ReturnType<typeof vi.fn>).mock.calls[1]! as [
      string,
      string,
      EventUpdatePayload,
    ];
    expect(secondPayload.scope).toBe("occurrence");
  });

  it("disables the scope options once a choice is submitted, preventing a double DELETE", async () => {
    let resolveDelete: () => void = () => {};
    (api.deleteEvent as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDelete = resolve;
      }),
    );
    const viewDialog = await openEventDialog(movedOccurrence());
    fireEvent.click(within(viewDialog).getByRole("button", { name: /delete event/i }));
    const chooser = await screen.findByRole("dialog", { name: "Delete recurring event" });

    const occurrenceButton = within(chooser).getByRole("button", { name: "Delete this occurrence" });
    fireEvent.click(occurrenceButton);
    fireEvent.click(occurrenceButton);
    fireEvent.click(occurrenceButton);

    expect(occurrenceButton).toBeDisabled();
    expect(api.deleteEvent).toHaveBeenCalledTimes(1);

    resolveDelete();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Delete recurring event" })).toBeNull());
  });
});
