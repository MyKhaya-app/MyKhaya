import { beforeEach, describe, expect, it, vi } from "vitest";
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

  async function openEditEventSheet() {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [existingEvent()] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText("Football"));
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

  async function openEventDialog(event: Record<string, unknown>) {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [event] });
    render(<CalendarPage />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(await screen.findByText(event.title as string));
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
