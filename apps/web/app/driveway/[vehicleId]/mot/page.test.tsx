import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import VehicleMotHistoryPage from "./page";

// Driveway MOT history page (Phase 1): normalised data only, grouped
// plainly, newest first, with no raw provider fields or terminology.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/driveway/v1/mot",
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
    api: { ...actual.api, vehicle: vi.fn(), vehicleMot: vi.fn(), refreshVehicleMot: vi.fn() },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & {
    status?: string;
    value?: { vehicleId: string };
  };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

const VEHICLE = { id: "v1", nickname: "Family car", country_code: "GB", registration: "AB12 CDE" };

const MOT = {
  eligible: true,
  provider_available: true,
  has_registration: true,
  summary: {
    status: "valid",
    due_date: "2027-09-01",
    expiry_date: "2027-09-01",
    first_mot_due_date: null,
    last_test_date: "2026-09-01",
    last_result: "passed",
    source: "dvsa",
    refreshed_at: new Date().toISOString(),
    stale: false,
    last_attempt_at: null,
    last_attempt_outcome: "success",
  },
  tests: [
    {
      id: "t2",
      test_number: "123456789012",
      test_date: "2026-09-01",
      completed_at: null,
      expiry_date: "2027-09-01",
      result: "passed",
      odometer_value: 45210,
      odometer_unit: "mi",
      odometer_result: "read",
      defects: [{ text: "Tyre close to legal limit", category: "advisory", dangerous: false }],
    },
    {
      id: "t1",
      test_number: "123456789011",
      test_date: "2026-08-30",
      completed_at: null,
      expiry_date: null,
      result: "failed",
      odometer_value: 45198,
      odometer_unit: "mi",
      odometer_result: "read",
      defects: [
        { text: "Headlamp aim too high", category: "major", dangerous: false },
        { text: "Brake pipe excessively corroded", category: "dangerous", dangerous: true },
      ],
    },
  ],
  refresh: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
  (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(MOT);
});

describe("MOT history page", () => {
  it("lists tests newest first with result, date, mileage and expiry", async () => {
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    const list = await screen.findByRole("list", { name: "MOT tests, newest first" });
    const items = within(list).getAllByRole("listitem").filter((el) => el.classList.contains("driveway-mot-test"));
    expect(items).toHaveLength(2);
    const [newest, older] = items as [HTMLElement, HTMLElement];
    expect(within(newest).getByText("Passed")).toBeInTheDocument();
    expect(within(newest).getByText("1 September 2026")).toBeInTheDocument();
    expect(within(newest).getByText("45,210 miles")).toBeInTheDocument();
    expect(within(newest).getByText("Valid until 1 September 2027")).toBeInTheDocument();
    expect(within(older).getByText("Failed")).toBeInTheDocument();
  });

  it("groups failure reasons and advisories plainly and flags dangerous items", async () => {
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    await screen.findByRole("list", { name: "MOT tests, newest first" });
    expect(screen.getByRole("heading", { name: "Advisories" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reasons for failure" })).toBeInTheDocument();
    expect(screen.getByText("Dangerous")).toBeInTheDocument();
    expect(screen.getByText("Brake pipe excessively corroded")).toBeInTheDocument();
  });

  it("shows no raw provider terminology", async () => {
    const { container } = render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    await screen.findByRole("list", { name: "MOT tests, newest first" });
    for (const raw of ["PASSED", "FAILED", "ADVISORY", "MAJOR", "motTests", "odometerValue"]) {
      expect(container.textContent).not.toContain(raw);
    }
  });

  it("explains that MOT history is UK-only for other vehicles", async () => {
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue({ ...MOT, eligible: false, tests: [] });
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(
      await screen.findByText("MOT history is only available for vehicles registered in the UK."),
    ).toBeInTheDocument();
  });

  it("shows a not-found message for an inaccessible vehicle", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(await screen.findByText("That vehicle could not be found.")).toBeInTheDocument();
  });
});
