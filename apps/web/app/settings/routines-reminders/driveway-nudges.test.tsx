import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, Reminder, TodoCategory } from "@mykhaya/shared-types";
import RoutinesRemindersPage from "./page";

// Vehicle reminders in Nudges: MOT nudges months away are listed (in a
// collapsed "Later" section) and searchable, carry a vehicle line linking to
// the vehicle, live in the system Driveway category, edit on the MOT reminder
// screen, and delete with a choice of one day or the whole plan.

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: pushMock }),
  usePathname: () => "/settings/routines-reminders",
  useSearchParams: () => new URLSearchParams(),
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
  useActiveHome: () => ({ activeHome: home(), activeHomeId: "home-1", homes: [home()], setActiveHomeId: vi.fn(), loading: false }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      routines: vi.fn(),
      reminders: vi.fn(),
      deleteReminder: vi.fn(),
      deleteVehicleMotNudges: vi.fn(),
      todos: vi.fn(),
      todoCategories: vi.fn(),
      members: vi.fn(),
      billingStatus: vi.fn(),
      featureMatrix: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function iso(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function short(days: number): string {
  const date = new Date(`${iso(days)}T00:00:00`);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}

const DRIVEWAY: TodoCategory = {
  id: "cat-driveway",
  name: "Driveway",
  created_by: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  system: "driveway",
};
const SCHOOL: TodoCategory = { ...DRIVEWAY, id: "cat-school", name: "School", system: null };

function motNudge(days: number, lead: number, id = `mot-${lead}`): Reminder {
  return {
    id,
    title: "Book MOT – BMW i4",
    description: "MOT expires 25 Aug 2027.",
    scope: "personal",
    owner_user_id: "u1",
    due_date: iso(days),
    due_time: "09:00:00",
    repeat: "never",
    cadence: "once",
    category: DRIVEWAY,
    enabled: true,
    member_ids: [],
    next_occurrence_date: iso(days),
    completed_today: false,
    vehicle: { vehicle_id: "v1", nickname: "Family car", make: "BMW", model: "i4", registration: "AP22OOJ", mot_plan_lead_days: lead },
    created_by: "u1",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function dentist(): Reminder {
  return { ...motNudge(2, 0, "dentist"), title: "Call the dentist", description: null, category: null, vehicle: null };
}

function mockData(reminders: Reminder[], categories: TodoCategory[] = [DRIVEWAY, SCHOOL]) {
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: reminders });
  (api.todoCategories as ReturnType<typeof vi.fn>).mockResolvedValue({ items: categories });
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.todos as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    household_routines_enabled: true,
    member_usage: { count: 1, limit: null, over_limit: false },
    calendar_usage: { count: 1, limit: null, over_limit: false },
    shared_events_enabled: true,
    external_invites_enabled: true,
    nudges_enabled: true,
  });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({ features: [{ feature: "nudges", enabled: true }] });
  (api.deleteReminder as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
  (api.deleteVehicleMotNudges as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
  mockData([motNudge(305, 30), motNudge(328, 7), dentist()]);
});

function laterSection() {
  return screen.getByText("Later", { selector: "h2" }).closest("details")!;
}

describe("Nudges — MOT nudges months away", () => {
  it("lists them in a collapsed Later section at the bottom, not among today's items", async () => {
    render(<RoutinesRemindersPage />);
    expect(await screen.findByText("Call the dentist")).toBeInTheDocument();
    const later = laterSection();
    expect(later).not.toHaveAttribute("open");
    expect(within(later).getByText("2")).toHaveClass("rr-later-count");
    expect(within(later).getAllByText("Book MOT – BMW i4")).toHaveLength(2);
    expect(screen.getByText("Upcoming", { selector: "h2" }).compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("finds them by searching for MOT, opening Later", async () => {
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox", { name: "Search nudges" }), "MOT");
    expect(laterSection()).toHaveAttribute("open");
    expect(screen.getAllByText("Book MOT – BMW i4")).toHaveLength(2);
    expect(screen.queryByText("Call the dentist")).not.toBeInTheDocument();
  });

  it("shows the vehicle line with a link to the vehicle page", async () => {
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const links = screen.getAllByRole("link", { name: "BMW i4 (AP22 OOJ)" });
    expect(links[0]).toHaveAttribute("href", "/driveway/v1");
    expect(links[0]!.closest("small")).toHaveTextContent(`Reminder · Driveway · BMW i4 (AP22 OOJ) · ${short(305)}`);
  });

  it("edits a plan nudge on the pre-filled MOT reminder screen", async () => {
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: "Edit Book MOT – BMW i4" })[0]!);
    expect(pushMock).toHaveBeenCalledWith("/driveway/v1/mot/reminder?from=nudges");
  });
});

describe("Nudges — deleting an MOT plan nudge", () => {
  it("can remove just this reminder", async () => {
    mockData([motNudge(0, 7)]);
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const sheet = await screen.findByRole("dialog", { name: "Delete MOT reminder?" });
    await user.click(within(sheet).getByRole("button", { name: "Remove this reminder" }));
    await waitFor(() => expect(api.deleteReminder).toHaveBeenCalledWith("home-1", "mot-7"));
    expect(api.deleteVehicleMotNudges).not.toHaveBeenCalled();
  });

  it("can remove the whole MOT reminder plan", async () => {
    mockData([motNudge(0, 7)]);
    render(<RoutinesRemindersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const sheet = await screen.findByRole("dialog", { name: "Delete MOT reminder?" });
    await user.click(within(sheet).getByRole("button", { name: "Remove MOT reminder plan" }));
    await waitFor(() => expect(api.deleteVehicleMotNudges).toHaveBeenCalledWith("home-1", "v1"));
    expect(api.deleteReminder).not.toHaveBeenCalled();
  });
});

describe("Nudges — the Driveway system category", () => {
  it("is listed with a car icon and no rename/delete once it has nudges", async () => {
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const panel = screen.getByRole("complementary", { name: "Nudges tools" });
    const row = within(panel).getByRole("button", { name: /Driveway/ });
    expect(row.querySelector("svg")).not.toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Manage categories" }));
    const manager = await screen.findByRole("dialog", { name: "Manage categories" });
    expect(within(manager).getByText("Managed by Driveway")).toBeInTheDocument();
    expect(within(manager).getAllByRole("button", { name: "Rename" })).toHaveLength(1); // School only
  });

  it("is hidden until it has nudges, and never offered when choosing a category", async () => {
    mockData([dentist()]);
    render(<RoutinesRemindersPage />);
    await screen.findByText("Call the dentist");
    const panel = screen.getByRole("complementary", { name: "Nudges tools" });
    expect(within(panel).queryByRole("button", { name: /Driveway/ })).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /School/ })).toBeInTheDocument();
  });
});
