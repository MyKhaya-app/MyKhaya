import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EventLabel, Home } from "@mykhaya/shared-types";
import HomeSettings from "./page";

// Locked-state coverage for the exact "Calendars & categories" screen a
// Free user could previously see with every seeded default (Family/School/
// Work/Appointment/Birthday/...) shown as fully active and manageable. See
// docs/architecture/commercial-entitlements.md "Event categories are
// CalendarEventLabel, not HomeCalendar".

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/home",
}));

function freeHome(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["calendar.edit_all"],
    member_count: 1,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: freeHome(),
    activeHomeId: "home-1",
    homes: [freeHome()],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

function label(overrides: Partial<EventLabel> = {}): EventLabel {
  return {
    id: "label-1",
    name: "Family",
    color: "teal",
    is_active: true,
    sort_order: 10,
    commercial_access: "normal",
    ...overrides,
  };
}

const sevenSeededLabels: EventLabel[] = [
  label({ id: "l1", name: "Family", sort_order: 10, is_active: true, commercial_access: "normal" }),
  label({
    id: "l2",
    name: "School",
    sort_order: 20,
    is_active: false,
    commercial_access: "read_only_due_to_plan",
  }),
  label({
    id: "l3",
    name: "Work",
    sort_order: 30,
    is_active: false,
    commercial_access: "read_only_due_to_plan",
  }),
  label({
    id: "l4",
    name: "Appointment",
    sort_order: 40,
    is_active: false,
    commercial_access: "read_only_due_to_plan",
  }),
  label({
    id: "l5",
    name: "Birthday",
    sort_order: 50,
    is_active: false,
    commercial_access: "read_only_due_to_plan",
  }),
];

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      homes: vi.fn(),
      listLabels: vi.fn(),
      billingStatus: vi.fn(),
      listCalendars: vi.fn(),
      updateCalendar: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([freeHome()]);
  (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [
      {
        id: "cal-1",
        name: "Home Calendar",
        timezone: "Europe/London",
        is_primary: true,
        owner_user_id: null,
        color: "teal",
        commercial_access: "normal",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    limit: null,
    personal_calendar: null,
  });
});

describe("Home settings — Calendars & categories locked states", () => {
  it("shows only one category as Active/manageable on Free, the rest locked", async () => {
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue(sevenSeededLabels);
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      category_usage: { count: 1, limit: 1, over_limit: false },
    });

    render(<HomeSettings />);

    await screen.findByRole("heading", { name: /calendars & categories/i });

    // Exactly one interactive "Active" checkbox — the rest render as
    // locked rows with no toggle at all.
    const activeCheckboxes = await screen.findAllByRole("checkbox", { name: /active/i });
    expect(activeCheckboxes).toHaveLength(1);

    // The locked categories are visible (not hidden) but muted/labelled.
    expect(screen.getByText("School")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.getByText("Appointment")).toBeInTheDocument();
    expect(screen.getByText("Birthday")).toBeInTheDocument();
    expect(screen.getAllByText(/^family$/i).length).toBeGreaterThan(0);

    // The create form is replaced by the locked upgrade CTA.
    expect(screen.queryByRole("button", { name: /^add category$/i })).not.toBeInTheDocument();
    expect(screen.getByText(/add another category/i)).toBeInTheDocument();
    expect(
      screen.getByText(/unlimited categories are included with myKhaya family/i),
    ).toBeInTheDocument();
  });

  it("shows every category as Active/manageable on Family", async () => {
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue(
      sevenSeededLabels.map((row) => ({ ...row, is_active: true, commercial_access: "normal" })),
    );
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      category_usage: { count: 5, limit: null, over_limit: false },
    });

    render(<HomeSettings />);

    await screen.findByRole("heading", { name: /calendars & categories/i });

    const activeCheckboxes = await screen.findAllByRole("checkbox", { name: /active/i });
    expect(activeCheckboxes).toHaveLength(5);
    expect(activeCheckboxes.every((box) => (box as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByRole("button", { name: /^add category$/i })).toBeInTheDocument();
  });
});

// The synthetic `label_id: null` option is a normal Home event with no
// category — this page is where an authorised user (calendar.edit_all,
// gated one level up in HomeSettings) customises its colour. Its name is
// a fixed product concept: this page must never expose a way to rename it.
describe("Home settings — Home calendar colour", () => {
  beforeEach(() => {
    (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue(sevenSeededLabels);
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      category_usage: { count: 1, limit: 1, over_limit: false },
    });
  });

  it("shows the Home calendar with its current colour and no rename control", async () => {
    render(<HomeSettings />);

    await screen.findByRole("heading", { name: /calendars & categories/i });

    // A colour-dot toggle button exists, but never a text input for its name.
    await screen.findByRole("button", { name: /change home calendar colour/i });
    expect(screen.getByText("Home calendar")).toBeInTheDocument();
    expect(screen.getByText(/shared events without a category/i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Home Calendar")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/home calendar name/i)).not.toBeInTheDocument();
  });

  it("lets an authorised user change the Home calendar colour via updateCalendar, not a name field", async () => {
    (api.updateCalendar as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "cal-1",
      name: "Home Calendar",
      timezone: "Europe/London",
      is_primary: true,
      owner_user_id: null,
      color: "amber",
      commercial_access: "normal",
      created_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<HomeSettings />);
    await screen.findByRole("heading", { name: /calendars & categories/i });

    await user.click(await screen.findByRole("button", { name: /change home calendar colour/i }));
    const picker = screen.getByRole("radiogroup", { name: /home calendar colour/i });
    await user.click(within(picker).getByRole("radio", { name: /amber/i }));

    // Exact match: only `color` is ever sent — never a `name`.
    expect(api.updateCalendar).toHaveBeenCalledWith("home-1", "cal-1", { color: "amber" });
  });
});
