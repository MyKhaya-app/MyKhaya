import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleDetailPage from "./page";

// Vehicle page (Screen 2): header, Overview | MOT | Details tabs, the MOT
// card with refresh, the red reminder action when the MOT needs attention,
// and the existing photo/edit/remove flows.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/v1",
}));

const activeHome = { id: "home-1", name: "Hales Home", relationship: "home_admin" };
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome,
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: { id: "u1", display_name: "Anthony Hales" } }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      vehicle: vi.fn(),
      members: vi.fn(),
      deleteVehicle: vi.fn(),
      uploadVehiclePhoto: vi.fn(),
      vehicleMot: vi.fn(),
      refreshVehicleMot: vi.fn(),
    },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

function iso(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function short(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}

const VEHICLE = {
  id: "v1",
  group_id: "home-1",
  owner_user_id: "u1",
  nickname: "Family car",
  make: "BMW",
  model: "i4",
  colour: "White",
  year: 2022,
  fuel_type: "Electric",
  engine_size: null,
  country_code: "GB",
  registration: "AP22OOJ",
  first_registration_date: null,
  photo_version: null,
  vin: null,
  tax_status: null,
  tax_due_date: null,
  inspection_status: "valid",
  inspection_due_date: iso(317),
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & { status?: string; value?: { vehicleId: string } };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

function renderPage(vehicleId = "v1") {
  return render(<VehicleDetailPage params={resolvedParams(vehicleId)} />);
}

const TESTS = [
  {
    id: "t2",
    test_number: "489904503767",
    test_date: "2026-08-07",
    completed_at: null,
    expiry_date: iso(317),
    result: "passed",
    odometer_value: 51950,
    odometer_unit: "mi",
    odometer_result: "read",
    defects: [],
  },
  {
    id: "t1",
    test_number: "111",
    test_date: "2025-08-22",
    completed_at: null,
    expiry_date: "2026-08-21",
    result: "passed",
    odometer_value: 37064,
    odometer_unit: "mi",
    odometer_result: "read",
    defects: [],
  },
];

function motResponse(days: number | null = 317, overrides: Record<string, unknown> = {}) {
  return {
    eligible: true,
    provider_available: true,
    has_registration: true,
    summary: {
      status: days === null ? null : days < 0 ? "expired" : "valid",
      due_date: days === null ? null : iso(days),
      expiry_date: null,
      first_mot_due_date: null,
      last_test_date: null,
      last_result: null,
      source: "dvsa",
      refreshed_at: new Date(Date.now() - 3 * 60_000).toISOString(),
      stale: false,
      last_attempt_at: null,
      last_attempt_outcome: "success",
    },
    tests: TESTS,
    refresh: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/driveway/v1");
  activeHome.relationship = "home_admin";
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
    { user_id: "u1", display_name: "Anthony Hales" },
    { user_id: "u2", display_name: "Megan Hales" },
  ]);
  (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse());
});

describe("Vehicle page — header and tabs", () => {
  it("shows the back link, name, plate chip, owner and photo button", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "BMW i4" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Driveway" })).toHaveAttribute("href", "/driveway");
    expect(screen.getByText("AP22 OOJ")).toHaveClass("drv-plate-md");
    expect(screen.getByText("You")).toHaveClass("drv-owner-chip");
    expect(screen.getByRole("button", { name: "Change vehicle photo" })).toBeInTheDocument();
  });

  it("names another member's vehicle by their first name", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, owner_user_id: "u2" });
    renderPage();
    expect(await screen.findByText("Megan")).toHaveClass("drv-owner-chip");
  });

  it("switches tabs with clicks and arrow keys, keeping the tab in the URL", async () => {
    renderPage();
    const tablist = await screen.findByRole("tablist", { name: "Vehicle sections" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Overview", "MOT", "Details"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    const user = userEvent.setup();
    await user.click(tabs[1]!);
    expect(within(tablist).getByRole("tab", { name: "MOT" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toBe("?tab=mot");
    await user.keyboard("{ArrowRight}");
    expect(within(tablist).getByRole("tab", { name: "Details" })).toHaveFocus();
    expect(window.location.search).toBe("?tab=details");
  });

  it("opens on the tab named in the URL", async () => {
    window.history.replaceState(null, "", "/driveway/v1?tab=mot");
    renderPage();
    expect(await screen.findByRole("link", { name: /View full MOT history/ })).toHaveAttribute("href", "/driveway/v1/mot");
  });
});

describe("Vehicle page — Overview", () => {
  it("shows a valid MOT with expiry, days left, last check and refresh — and no reminder button", async () => {
    renderPage();
    expect(await screen.findByText("MOT valid")).toHaveClass("drv-pill-valid");
    expect(screen.getByText(`Expires ${short(317)}`)).toBeInTheDocument();
    expect(screen.getByText("317 days left · checked 3 min ago")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh MOT status" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Set MOT reminder/ })).not.toBeInTheDocument();
  });

  it("goes red with a reminder action when the MOT is due within 30 days", async () => {
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse(12));
    renderPage();
    expect(await screen.findByText("MOT due in 12 days")).toHaveClass("drv-pill-soon");
    expect(screen.getByRole("link", { name: /Set MOT reminder/ })).toHaveAttribute("href", "/driveway/v1/mot/reminder?from=vehicle");
  });

  it("says how long ago an expired MOT ran out", async () => {
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse(-4));
    renderPage();
    expect(await screen.findByText("MOT expired")).toHaveClass("drv-pill-expired");
    expect(screen.getByText(/Expired 4 days ago/)).toBeInTheDocument();
  });

  it("does not offer reminders to someone who can't set them", async () => {
    activeHome.relationship = "adult_member";
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, owner_user_id: "u2" });
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse(12));
    renderPage();
    await screen.findByText("MOT due in 12 days");
    expect(screen.queryByRole("link", { name: /Set MOT reminder/ })).not.toBeInTheDocument();
  });

  it("shows the facts card with mileage from the latest test, and nothing else", async () => {
    renderPage();
    await screen.findByText("MOT valid");
    expect(screen.getByText("Last recorded mileage").nextSibling).toHaveTextContent("51,950 mi");
    expect(screen.getByText("Year").nextSibling).toHaveTextContent("2022");
    expect(screen.queryByRole("link", { name: /Reminders/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove vehicle/ })).not.toBeInTheDocument();
  });

  it("refreshes on request and shows the server's message", async () => {
    (api.refreshVehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...motResponse(),
      refresh: { outcome: "rate_limited", message: "MOT checks are busy right now." },
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Refresh MOT status" }));
    await waitFor(() => expect(api.refreshVehicleMot).toHaveBeenCalledWith("home-1", "v1", "force"));
    expect(await screen.findByText("MOT checks are busy right now.")).toBeInTheDocument();
  });

  it("asks for one if-stale refresh when stored MOT data is stale", async () => {
    const stale = motResponse();
    stale.summary.stale = true;
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(stale);
    (api.refreshVehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse());
    renderPage();
    await screen.findByText("MOT valid");
    await waitFor(() => expect(api.refreshVehicleMot).toHaveBeenCalledWith("home-1", "v1", "if_stale"));
    expect(api.refreshVehicleMot).toHaveBeenCalledTimes(1);
  });

  it("never fetches or shows MOT for a vehicle outside the UK", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, country_code: "ZA", registration: "CA 123-456" });
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    expect(api.vehicleMot).not.toHaveBeenCalled();
    expect(screen.queryByText(/MOT valid|MOT not checked/)).not.toBeInTheDocument();
  });
});

describe("Vehicle page — MOT tab", () => {
  beforeEach(() => window.history.replaceState(null, "", "/driveway/v1?tab=mot"));

  it("lists recent tests with the latest marked, first MOT labelled, and links onward", async () => {
    renderPage();
    const list = await screen.findByRole("list", { name: "Recent MOT tests" });
    const rows = within(list).getAllByRole("listitem");
    expect(within(rows[0]!).getByText("7 Aug 2026")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("51,950 mi · no defects or advisories")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Test no. 489904503767")).toBeInTheDocument();
    expect(rows[0]!.querySelector(".drv-test-dot-latest")).not.toBeNull();
    expect(within(rows[1]!).getByText("37,064 mi · first MOT")).toBeInTheDocument();
    expect(within(rows[1]!).queryByText(/Test no\./)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Set MOT reminder/ })).toHaveAttribute("href", "/driveway/v1/mot/reminder?from=vehicle-mot");
    expect(screen.getByRole("link", { name: /View full MOT history/ })).toHaveAttribute("href", "/driveway/v1/mot");
  });
});

describe("Vehicle page — Details tab", () => {
  beforeEach(() => window.history.replaceState(null, "", "/driveway/v1?tab=details"));

  it("lists the details, links to edit, and never shows the VIN", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, vin: "WBA00000000000000", tax_status: "Taxed", tax_due_date: iso(100) });
    renderPage();
    expect(await screen.findByText("Make / model")).toBeInTheDocument();
    for (const [label, value] of [
      ["Registration", "AP22 OOJ"],
      ["Country", "United Kingdom"],
      ["Driver", "You"],
      ["Vehicle tax", `Taxed · due ${short(100)}`],
    ]) {
      expect(screen.getByText(label!).nextSibling).toHaveTextContent(value!);
    }
    expect(screen.queryByText("WBA00000000000000")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Edit details/ })).toHaveAttribute("href", "/driveway/v1/details");
  });

  it("confirms before removing, and routes back to Driveway on success", async () => {
    (api.deleteVehicle as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Remove vehicle/ }));
    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: "Remove vehicle" }));
    await waitFor(() => expect(api.deleteVehicle).toHaveBeenCalledWith("home-1", "v1"));
    expect(push).toHaveBeenCalledWith("/driveway");
  });
});

describe("Vehicle page — not found", () => {
  it("shows a not-found message for a vehicle that is missing or not accessible", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    renderPage("missing");
    expect(await screen.findByText("That vehicle could not be found.")).toBeInTheDocument();
  });
});
