import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleDetailPage from "./page";

// Coverage for the Driveway vehicle detail page (Phase 3). Mirrors the
// not-found/loading/detail patterns established in app/lists/[id]/page.test.tsx.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/v1",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
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
      vehicle: vi.fn(),
      deleteVehicle: vi.fn(),
      uploadVehiclePhoto: vi.fn(),
      vehicleMot: vi.fn(),
      refreshVehicleMot: vi.fn(),
    },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

const VEHICLE = {
  id: "v1",
  group_id: "home-1",
  owner_user_id: "u1",
  scope: "household",
  nickname: "BMW i4",
  make: "BMW",
  model: "i4",
  colour: "Black",
  year: 2022,
  fuel_type: "Electric",
  engine_size: null,
  country_code: "GB",
  registration: "AP22 OOJ",
  first_registration_date: null,
  photo_version: null,
  vin: null,
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// React's use() needs a promise that's already resolved with `status`/
// `value` set to synchronously unwrap without suspending — matching how
// Next.js's own params promise behaves in practice. Mirrors the identical
// helper in app/lists/[id]/page.test.tsx.
function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & {
    status?: string;
    value?: { vehicleId: string };
  };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

function renderPage(vehicleId = "v1") {
  return render(<VehicleDetailPage params={resolvedParams(vehicleId)} />);
}

// A provider-neutral MOT response, as the backend returns it.
function motResponse(overrides: Record<string, unknown> = {}, summary: Record<string, unknown> = {}) {
  return {
    eligible: true,
    provider_available: true,
    has_registration: true,
    summary: {
      status: null,
      due_date: null,
      expiry_date: null,
      first_mot_due_date: null,
      last_test_date: null,
      last_result: null,
      source: null,
      refreshed_at: null,
      stale: false,
      last_attempt_at: null,
      last_attempt_outcome: null,
      ...summary,
    },
    tests: [],
    refresh: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse());
});

describe("Vehicle detail — real data only", () => {
  it("renders real vehicle fields from the API", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    renderPage();
    expect(await screen.findByRole("heading", { name: "BMW i4" })).toBeInTheDocument();
    expect(screen.getAllByText("AP22 OOJ").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BMW i4").length).toBeGreaterThan(0);
    expect(screen.getByText("2022")).toBeInTheDocument();
    expect(screen.getByText("Electric")).toBeInTheDocument();
    expect(screen.getByText("Black")).toBeInTheDocument();
  });

  it("does not render missing values as fake placeholders", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...VEHICLE,
      colour: null,
      fuel_type: null,
      year: null,
      engine_size: null,
    });
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    for (const fake of ["N/A", "Unknown", "—", "null"]) {
      expect(screen.queryByText(fake)).not.toBeInTheDocument();
    }
  });

  it("never shows the VIN in the general summary card", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, vin: "WBA12345678901234" });
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    expect(screen.queryByText("WBA12345678901234")).not.toBeInTheDocument();
    expect(screen.queryByText(/vin/i)).not.toBeInTheDocument();
  });

  it("navigates to the Vehicle details edit screen", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    renderPage();
    const row = await screen.findByRole("heading", { name: "Vehicle details" });
    expect(row.closest("a")).toHaveAttribute("href", "/driveway/v1/details");
  });

  it("offers the same photo picker entry point used by profile uploads", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    await user.click(screen.getByRole("button", { name: "Add photo" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Choose a clear photo of BMW i4.");
    expect(screen.getByRole("button", { name: "Take photo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose from library" })).toBeInTheDocument();
  });

  it("shows a not-found message for a vehicle that does not exist or is not accessible", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    renderPage();
    expect(await screen.findByText("That vehicle could not be found.")).toBeInTheDocument();
  });

  it("navigates to the Driveway vehicle Reminders list (Phase 4)", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    renderPage();
    const row = await screen.findByRole("heading", { name: "Reminders" });
    expect(row.closest("a")).toHaveAttribute("href", "/driveway/v1/reminders");
  });

  it("only exposes implemented vehicle detail destinations", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });

    for (const title of ["Vehicle details", "Reminders"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    for (const title of ["MOT history", "Documents", "Service history", "Insurance", "Notes"]) {
      expect(screen.queryByRole("heading", { name: title })).not.toBeInTheDocument();
    }

    const detailsRow = screen.getByRole("heading", { name: "Vehicle details" }).closest("a");
    const remindersRow = screen.getByRole("heading", { name: "Reminders" }).closest("a");
    expect(detailsRow?.querySelector("svg")).toBeTruthy();
    expect(remindersRow?.querySelector("svg")).toBeTruthy();
  });
});

describe("Vehicle detail — remove vehicle", () => {
  it("confirms before removing, and routes back to Driveway on success", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.deleteVehicle as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    await user.click(screen.getByRole("button", { name: /remove vehicle/i }));
    expect(screen.getByText("This will remove BMW i4 from Driveway.")).toBeInTheDocument();
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove vehicle" }));
    await waitFor(() => expect(api.deleteVehicle).toHaveBeenCalledWith("home-1", "v1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/driveway"));
  });
});

describe("Vehicle detail — MOT (DVSA, UK vehicles only)", () => {
  const VALID = {
    status: "valid",
    due_date: "2027-03-14",
    expiry_date: "2027-03-14",
    refreshed_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    source: "dvsa",
  };

  it("shows the current MOT in family language with when it was last checked", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse({}, VALID));
    renderPage();
    expect(await screen.findByText("Valid")).toBeInTheDocument();
    expect(screen.getByText("Expires 14 March 2027")).toBeInTheDocument();
    expect(screen.getByText("Last checked 2 hours ago")).toBeInTheDocument();
    expect(api.refreshVehicleMot).not.toHaveBeenCalled(); // fresh data: no provider check
  });

  it("refreshes on request and shows the server's message", async () => {
    const user = userEvent.setup();
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse({}, VALID));
    (api.refreshVehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(
      motResponse({ refresh: { outcome: "rate_limited", message: "MOT checks are busy right now. Please try again in a few minutes." } }, VALID),
    );
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Refresh/ }));
    expect(api.refreshVehicleMot).toHaveBeenCalledWith("home-1", "v1", "force");
    expect(await screen.findByText(/MOT checks are busy right now/)).toBeInTheDocument();
  });

  it("asks for one if-stale refresh when the stored MOT data is stale", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse({}, { ...VALID, stale: true }));
    (api.refreshVehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse({}, VALID));
    renderPage();
    await waitFor(() => expect(api.refreshVehicleMot).toHaveBeenCalledWith("home-1", "v1", "if_stale"));
    expect(api.refreshVehicleMot).toHaveBeenCalledTimes(1);
  });

  it("describes a vehicle whose first MOT is not yet due", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(
      motResponse({}, { status: "not_yet_due", due_date: "2028-03-14", first_mot_due_date: "2028-03-14" }),
    );
    renderPage();
    expect(await screen.findByText("Not yet due")).toBeInTheDocument();
    expect(screen.getByText("First MOT due 14 March 2028")).toBeInTheDocument();
  });

  it("says when MOT checks are unavailable and offers no refresh", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(motResponse({ provider_available: false }));
    renderPage();
    expect(await screen.findByText("MOT checks aren't available right now.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refresh|Check MOT/ })).not.toBeInTheDocument();
  });

  it("links to MOT history only once there is history to show", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(
      motResponse(
        {
          tests: [
            { id: "t1", test_number: "1", test_date: "2026-09-01", completed_at: null, expiry_date: "2027-09-01", result: "passed", odometer_value: 45210, odometer_unit: "mi", odometer_result: "read", defects: [] },
          ],
        },
        VALID,
      ),
    );
    renderPage();
    const row = await screen.findByRole("heading", { name: "MOT history" });
    expect(row.closest("a")).toHaveAttribute("href", "/driveway/v1/mot");
  });

  it("never shows an MOT card or fetches MOT data for a non-UK vehicle", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, country_code: "ZA" });
    renderPage();
    await screen.findByRole("heading", { name: "BMW i4" });
    expect(screen.queryByRole("heading", { name: "MOT" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "MOT history" })).not.toBeInTheDocument();
    expect(api.vehicleMot).not.toHaveBeenCalled();
  });
});
