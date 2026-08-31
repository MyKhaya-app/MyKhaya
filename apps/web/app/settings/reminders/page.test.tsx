import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, Reminder } from "@mykhaya/shared-types";
import ReminderSettings from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/reminders",
}));

function home(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["household.manage_reminders"],
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
      reminders: vi.fn(),
      createReminder: vi.fn(),
      updateReminder: vi.fn(),
      deleteReminder: vi.fn(),
      completeReminder: vi.fn(),
      uncompleteReminder: vi.fn(),
      members: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function reminder(overrides: Partial<Reminder> = {}): Reminder {
  const today = new Date().toISOString().slice(0, 10);
  return {
    id: "reminder-1",
    title: "Call the dentist",
    description: null,
    scope: "personal",
    owner_user_id: "u1",
    due_date: today,
    due_time: "09:00:00",
    repeat: "never",
    cadence: "once",
    enabled: true,
    member_ids: [],
    next_occurrence_date: today,
    completed_today: false,
    home_occurrence_date: today,
    home_completed_at: null,
    home_completed_by_user_id: null,
    home_completed_by_display_name: null,
    created_by: "u1",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.createReminder as ReturnType<typeof vi.fn>).mockResolvedValue(reminder());
  (api.updateReminder as ReturnType<typeof vi.fn>).mockResolvedValue(reminder());
  (api.completeReminder as ReturnType<typeof vi.fn>).mockResolvedValue(reminder({ completed_today: true }));
});

describe("Reminders — Personal/Household tabs", () => {
  it("only shows reminders matching the selected scope tab", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        reminder({ id: "p1", title: "Personal one", scope: "personal" }),
        reminder({ id: "h1", title: "Household one", scope: "household", owner_user_id: null }),
      ],
    });

    render(<ReminderSettings />);

    expect(await screen.findByText("Personal one")).toBeInTheDocument();
    expect(screen.queryByText("Household one")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Household" }));

    expect(await screen.findByText("Household one")).toBeInTheDocument();
    expect(screen.queryByText("Personal one")).not.toBeInTheDocument();
  });
});

describe("Reminders — sections", () => {
  it("groups overdue, today, upcoming and completed reminders separately", async () => {
    const today = new Date().toISOString().slice(0, 10);
    const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        reminder({ id: "r1", title: "Overdue item", next_occurrence_date: yesterday }),
        reminder({ id: "r2", title: "Today item", next_occurrence_date: today }),
        reminder({ id: "r3", title: "Upcoming item", next_occurrence_date: tomorrow }),
        reminder({ id: "r4", title: "Done item", completed_today: true }),
      ],
    });

    render(<ReminderSettings />);

    await screen.findByText("Overdue item");
    expect(screen.getByRole("heading", { name: "Overdue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Completed" })).toBeInTheDocument();
    expect(screen.getByText("Today item")).toBeInTheDocument();
    expect(screen.getByText("Upcoming item")).toBeInTheDocument();
    expect(screen.getByText("Done item")).toBeInTheDocument();
  });
});

describe("Reminders — create", () => {
  it("creates a personal reminder with the fields from the form", async () => {
    render(<ReminderSettings />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add a reminder/i }));
    await user.type(screen.getByLabelText(/title/i), "Water the plants");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createReminder).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({ title: "Water the plants", scope: "personal" }),
    );
    expect(await screen.findByText("Reminder created.")).toBeInTheDocument();
  });

  it("creates a household reminder assigned to a specific member", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        membership_id: "m1",
        user_id: "u2",
        display_name: "Erin",
        email: null,
        role: "adult_member",
        relationship: "partner",
        permission_profile: "standard_partner",
        permission_overrides: {},
        shared_resources: [],
        colour: "sky",
        avatar_version: null,
      },
    ]);

    render(<ReminderSettings />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add a reminder/i }));
    await user.type(screen.getByLabelText(/title/i), "Bring PE kit");
    await user.selectOptions(screen.getByLabelText(/^scope$/i), "household");
    await user.selectOptions(screen.getByLabelText(/assign to/i), "u2");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.createReminder).toHaveBeenCalledWith(
      "home-1",
      expect.objectContaining({
        title: "Bring PE kit",
        scope: "household",
        member_ids: ["u2"],
      }),
    );
  });
});

describe("Reminders — completion", () => {
  it("ticking a reminder calls completeReminder with its occurrence date", async () => {
    const item = reminder();
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [item] });

    render(<ReminderSettings />);
    const row = await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(within(row.closest(".card") as HTMLElement).getByRole("checkbox"));

    expect(api.completeReminder).toHaveBeenCalledWith(
      "home-1",
      "reminder-1",
      item.home_occurrence_date,
    );
  });
});

describe("Reminders — delete", () => {
  it("asks for confirmation, then deletes and reloads", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [reminder()] });
    (api.deleteReminder as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    render(<ReminderSettings />);
    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(api.deleteReminder).toHaveBeenCalledWith("home-1", "reminder-1");
  });

  it("does nothing when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [reminder()] });

    render(<ReminderSettings />);
    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(api.deleteReminder).not.toHaveBeenCalled();
  });
});
