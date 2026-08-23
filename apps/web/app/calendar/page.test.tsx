import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    activeHome: { id: "home-1", name: "Hales Home" },
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
