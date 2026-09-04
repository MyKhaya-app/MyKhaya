import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, Reminder, Routine } from "@mykhaya/shared-types";
import RoutinesRemindersPage from "./page";

const replaceMock = vi.fn();
let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => "/settings/routines-reminders",
  useSearchParams: () => searchParamsValue,
}));

function home(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["household.manage_routines", "household.manage_reminders"],
    member_count: 1,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: home(),
    activeHomeId: "home-1",
    homes: [home()],
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
      routines: vi.fn(),
      createRoutine: vi.fn(),
      updateRoutine: vi.fn(),
      deleteRoutine: vi.fn(),
      completeRoutine: vi.fn(),
      uncompleteRoutine: vi.fn(),
      reminders: vi.fn(),
      createReminder: vi.fn(),
      updateReminder: vi.fn(),
      deleteReminder: vi.fn(),
      completeReminder: vi.fn(),
      uncompleteReminder: vi.fn(),
      members: vi.fn(),
      billingStatus: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function today(): string {
  return new Date().toISOString().slice(0, 10);
}
function tomorrow(): string {
  return new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
}

function routine(overrides: Partial<Routine> = {}): Routine {
  return {
    id: "routine-1",
    title: "Put bins out",
    description: null,
    scope: "household",
    owner_user_id: null,
    interval_weeks: 1,
    repeat_unit: "weekly",
    week_anchor_date: today(),
    reminder_timing: "evening_before",
    is_critical: false,
    pinned: false,
    enabled: true,
    start_date: today(),
    end_date: null,
    member_ids: [],
    next_occurrence_date: today(),
    completed_today: false,
    created_by: "u1",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function reminder(overrides: Partial<Reminder> = {}): Reminder {
  return {
    id: "reminder-1",
    title: "Call the dentist",
    description: null,
    scope: "personal",
    owner_user_id: "u1",
    due_date: today(),
    due_time: "09:00:00",
    repeat: "never",
    cadence: "once",
    enabled: true,
    member_ids: [],
    next_occurrence_date: today(),
    completed_today: false,
    created_by: "u1",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  searchParamsValue = new URLSearchParams();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    household_routines_enabled: true,
    member_usage: { count: 1, limit: null, over_limit: false },
    calendar_usage: { count: 1, limit: null, over_limit: false },
    shared_events_enabled: true,
    external_invites_enabled: true,
  });
  (api.createRoutine as ReturnType<typeof vi.fn>).mockResolvedValue(routine());
  (api.updateRoutine as ReturnType<typeof vi.fn>).mockResolvedValue(routine());
  (api.createReminder as ReturnType<typeof vi.fn>).mockResolvedValue(reminder());
  (api.updateReminder as ReturnType<typeof vi.fn>).mockResolvedValue(reminder());
});

function mockBoth() {
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [routine({ id: "routine-1", title: "Put bins out", scope: "personal" })],
  });
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [reminder({ id: "reminder-1", title: "Call the dentist", scope: "personal" })],
  });
}

describe("Routines & Reminders — combined module", () => {
  it("renders both Routines and Reminders together in the All view, subtly labelled", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);

    expect(await screen.findByText("Put bins out")).toBeInTheDocument();
    expect(screen.getByText("Call the dentist")).toBeInTheDocument();
    // Kind is labelled as part of each card's meta line ("Routine ·
    // Personal · ..." / "Reminder · Personal") rather than a standalone
    // badge — still text, never colour alone.
    expect(screen.getByText(/^Routine · /)).toBeInTheDocument();
    expect(screen.getByText(/^Reminder · /)).toBeInTheDocument();
  });

  it("Routines filter shows only Routines", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Routines" }));

    expect(await screen.findByText("Put bins out")).toBeInTheDocument();
    expect(screen.queryByText("Call the dentist")).not.toBeInTheDocument();
  });

  it("Reminders filter shows only Reminders", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Reminders" }));

    expect(await screen.findByText("Call the dentist")).toBeInTheDocument();
    expect(screen.queryByText("Put bins out")).not.toBeInTheDocument();
  });

  it("Personal/Household scope filtering hides items from the other scope", async () => {
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [routine({ id: "r1", title: "Household routine", scope: "household" })],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ id: "m1", title: "Personal reminder", scope: "personal" })],
    });

    render(<RoutinesRemindersPage />);

    expect(await screen.findByText("Personal reminder")).toBeInTheDocument();
    expect(screen.queryByText("Household routine")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Household" }));

    expect(await screen.findByText("Household routine")).toBeInTheDocument();
    expect(screen.queryByText("Personal reminder")).not.toBeInTheDocument();
  });

  it("sorts the combined All view chronologically rather than grouping by source", async () => {
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [routine({ id: "r1", title: "Later routine", scope: "personal", next_occurrence_date: tomorrow() })],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ id: "m1", title: "Earlier reminder", scope: "personal", due_time: "08:00:00" })],
    });

    render(<RoutinesRemindersPage />);
    await screen.findByText("Earlier reminder");

    const upcomingHeading = screen.getByRole("heading", { name: "Today" });
    const upcomingSection = upcomingHeading.closest("section") as HTMLElement;
    expect(within(upcomingSection).getByText("Earlier reminder")).toBeInTheDocument();

    const laterHeading = screen.getByRole("heading", { name: "Upcoming" });
    const laterSection = laterHeading.closest("section") as HTMLElement;
    expect(within(laterSection).getByText("Later routine")).toBeInTheDocument();
  });

  it("shows an empty state when there are no Routines or Reminders at all", async () => {
    render(<RoutinesRemindersPage />);
    expect(await screen.findByText(/nothing here yet/i)).toBeInTheDocument();
  });

  it("shows a contextual empty state when the current filter has no matches", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Routines" }));
    expect(await screen.findByText("All caught up!")).toBeInTheDocument();
    expect(screen.getByText(/no more personal routines scheduled/i)).toBeInTheDocument();
  });
});

describe("Routines & Reminders — create menu", () => {
  it("offers both New Routine and New Reminder from one Add control", async () => {
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add" }));

    expect(screen.getByRole("button", { name: "New Routine" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Reminder" })).toBeInTheDocument();
  });

  it("creates a routine via the Routine form", async () => {
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add" }));
    await user.click(screen.getByRole("button", { name: "New Routine" }));
    await user.type(screen.getByLabelText(/title/i), "Feed the dog");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createRoutine).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ title: "Feed the dog" }),
    );
    expect(await screen.findByText("Routine created.")).toBeInTheDocument();
  });

  it("creates a Household Routine with scope=household reaching the backend unchanged", async () => {
    // Regression coverage for the "Household Routine silently saves as
    // Personal" investigation: the earlier live-verification finding turned
    // out to be a test-tooling artifact (Playwright's selectOption() forcing
    // a value onto a genuinely *disabled* <option>, which no real user can
    // do) rather than a real defect — this test drives the form the same
    // way a real user does (userEvent.selectOptions, which respects
    // disabled options) against an entitled Home, and asserts the exact
    // payload sent to the API.
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add" }));
    await user.click(screen.getByRole("button", { name: "New Routine" }));
    const scopeSelect = await screen.findByLabelText(/who this is for/i);
    await user.selectOptions(scopeSelect, "household");
    expect(scopeSelect).toHaveValue("household");
    await user.type(screen.getByLabelText(/title/i), "Put bins out");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createRoutine).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ title: "Put bins out", scope: "household" }),
    );
  });

  it("keeps the Household Routine option disabled (with the Family upsell) when not entitled", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      household_routines_enabled: false,
      member_usage: { count: 1, limit: 1, over_limit: false },
      calendar_usage: { count: 1, limit: 1, over_limit: false },
      shared_events_enabled: false,
      external_invites_enabled: false,
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add" }));
    await user.click(screen.getByRole("button", { name: "New Routine" }));

    const householdOption = await screen.findByRole("option", { name: /household/i });
    expect(householdOption).toBeDisabled();
    expect(screen.getByText("Household routines")).toBeInTheDocument();

    // A disabled <option> cannot be selected by userEvent either — the same
    // constraint a real click-driven user faces — so the select stays on
    // its Personal default and a save reaches the API as Personal, never a
    // silently-downgraded Household request.
    await user.type(screen.getByLabelText(/title/i), "Water the plants");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(api.createRoutine).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ scope: "personal" }),
    );
  });

  it("creates a reminder via the Reminder form", async () => {
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add" }));
    await user.click(screen.getByRole("button", { name: "New Reminder" }));
    await user.type(screen.getByLabelText(/title/i), "Water the plants");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createReminder).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ title: "Water the plants", scope: "personal" }),
    );
    expect(await screen.findByText("Reminder created.")).toBeInTheDocument();
  });
});

describe("Routines & Reminders — completion dispatches to the right API", () => {
  it("completing a Routine row calls completeRoutine, not completeReminder", async () => {
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [routine({ id: "routine-1", title: "Put bins out", scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    await screen.findByText("Put bins out");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /complete put bins out/i }));

    expect(api.completeRoutine).toHaveBeenCalledWith("home-1", "routine-1", today());
    expect(api.completeReminder).not.toHaveBeenCalled();
  });

  it("completing a one-off Reminder row calls completeReminder, not completeRoutine", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ id: "reminder-1", title: "Call the dentist", scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /complete call the dentist/i }));

    expect(api.completeReminder).toHaveBeenCalledWith("home-1", "reminder-1", today());
    expect(api.completeRoutine).not.toHaveBeenCalled();
  });

  it("completing a repeating Reminder only closes the current occurrence via the same completeReminder call", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ id: "reminder-1", title: "Take out recycling", repeat: "weekly", scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    await screen.findByText("Take out recycling");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /complete take out recycling/i }));

    expect(api.completeReminder).toHaveBeenCalledWith("home-1", "reminder-1", today());
  });
});

describe("Routines & Reminders — edit and delete", () => {
  it("edits a routine, pre-filling the Routine form", async () => {
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [routine({ scope: "household" })],
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Household" }));
    await user.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText(/title/i)).toHaveValue("Put bins out");
    expect(screen.getByRole("heading", { name: "Edit routine" })).toBeInTheDocument();
  });

  it("edits a reminder, pre-filling the Reminder form", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText(/title/i)).toHaveValue("Call the dentist");
    expect(screen.getByRole("heading", { name: "Edit reminder" })).toBeInTheDocument();
  });

  it("deletes a routine after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [routine({ scope: "household" })],
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Household" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(api.deleteRoutine).toHaveBeenCalledWith("home-1", "routine-1");
  });

  it("deletes a reminder after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder({ scope: "personal" })],
    });
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(api.deleteReminder).toHaveBeenCalledWith("home-1", "reminder-1");
  });
});

describe("Routines & Reminders — search", () => {
  it("filters the visible list client-side by title as the user types", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);
    await screen.findByText("Put bins out");
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText(/search routines and reminders/i),
      "dentist",
    );

    expect(await screen.findByText("Call the dentist")).toBeInTheDocument();
    expect(screen.queryByText("Put bins out")).not.toBeInTheDocument();
    // No backend search architecture — routines()/reminders() are called
    // exactly once each, at initial load, never re-fetched as the user types.
    expect(api.routines).toHaveBeenCalledTimes(1);
    expect(api.reminders).toHaveBeenCalledTimes(1);
  });

  it("shows the empty state, scoped to the current search term, when nothing matches", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);
    await screen.findByText("Put bins out");
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText(/search routines and reminders/i),
      "nonexistent item",
    );

    expect(await screen.findByText("All caught up!")).toBeInTheDocument();
    expect(screen.getByText(/match "nonexistent item"/i)).toBeInTheDocument();
  });
});

describe("Routines & Reminders — filter visibility toggle", () => {
  it("hides and re-shows the Type/Scope segmented controls without touching the underlying filters", async () => {
    mockBoth();
    render(<RoutinesRemindersPage />);
    await screen.findByText("Put bins out");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Routines" }));
    expect(screen.queryByText("Call the dentist")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hide filters" }));
    expect(screen.queryByRole("button", { name: "All" })).not.toBeInTheDocument();
    // The Routines-only filter chosen before hiding is still in effect.
    expect(screen.queryByText("Call the dentist")).not.toBeInTheDocument();
    expect(screen.getByText("Put bins out")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show filters" }));
    expect(screen.getByRole("button", { name: "All", pressed: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Routines", pressed: true })).toBeInTheDocument();
  });
});

describe("Routines & Reminders — Upcoming cards", () => {
  it("shows the UPCOMING eyebrow and due date, and tapping the card opens the existing edit flow", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        reminder({
          id: "reminder-2",
          title: "Gym Session",
          scope: "personal",
          next_occurrence_date: tomorrow(),
          due_time: "07:00:00",
        }),
      ],
    });
    render(<RoutinesRemindersPage />);

    const card = await screen.findByRole("button", { name: /Gym Session/ });
    expect(within(card).getByText("Upcoming")).toBeInTheDocument();
    expect(within(card).getByText(/tomorrow at 07:00/i)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(card);
    expect(screen.getByRole("heading", { name: "Edit reminder" })).toBeInTheDocument();
    expect(screen.getByLabelText(/title/i)).toHaveValue("Gym Session");
  });
});
