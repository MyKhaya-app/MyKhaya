import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleMotHistoryPage from "./page";

// MOT history (Screen 3): green status card, stat tiles and a newest-first
// timeline with older entries collapsed. Normalised data only — no raw
// provider fields or terminology.

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

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: { id: "u1", display_name: "Anthony Hales" } }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, vehicle: vi.fn(), vehicleMot: vi.fn(), refreshVehicleMot: vi.fn() } };
});

const { ApiError, api } = await import("@mykhaya/api-client");

function iso(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & { status?: string; value?: { vehicleId: string } };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

const VEHICLE = { id: "v1", owner_user_id: "u1", nickname: "Family car", make: "BMW", model: "i4", country_code: "GB", registration: "AP22OOJ" };

function mot(days: number) {
  return {
    eligible: true,
    provider_available: true,
    has_registration: true,
    summary: {
      status: days < 0 ? "expired" : "valid",
      due_date: iso(days),
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
    tests: [
      {
        id: "t3",
        test_number: "489904503767",
        test_date: "2026-08-07",
        completed_at: null,
        expiry_date: "2027-08-25",
        result: "passed",
        odometer_value: 51950,
        odometer_unit: "mi",
        odometer_result: "read",
        defects: [],
      },
      {
        id: "t2",
        test_number: "222",
        test_date: "2025-08-20",
        completed_at: null,
        expiry_date: null,
        result: "failed",
        odometer_value: 37060,
        odometer_unit: "mi",
        odometer_result: "read",
        defects: [
          { text: "Brake pipe excessively corroded", category: "dangerous", dangerous: true },
          { text: "Tyre close to legal limit", category: "advisory", dangerous: false },
        ],
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
    ],
    refresh: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
  (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(mot(317));
});

describe("MOT history", () => {
  it("shows the heading, back link and a valid status card", async () => {
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(await screen.findByRole("heading", { name: "MOT history" })).toBeInTheDocument();
    expect(screen.getByText("Vehicle · AP22 OOJ")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BMW i4" })).toHaveAttribute("href", "/driveway/v1?tab=mot");
    const card = screen.getByRole("region", { name: "Current MOT" });
    expect(within(card).getByText("Valid")).toHaveClass("drv-pill-onGreen");
    expect(within(card).getByText("317 days left · checked 3 min ago")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Refresh MOT status" })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Set MOT reminder/ })).toHaveAttribute("href", "/driveway/v1/mot/reminder?from=history");
  });

  it("uses a red pill when the MOT is due within 30 days", async () => {
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue(mot(1));
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(await screen.findByText("Due in 1 day")).toHaveClass("drv-pill-soon");
  });

  it("shows tests passed and the miles between the last two tests", async () => {
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    const stats = await screen.findByRole("region", { name: "MOT at a glance" });
    expect(within(stats).getByText("2 of 3")).toBeInTheDocument();
    expect(within(stats).getByText("14,890")).toBeInTheDocument();
  });

  it("lists tests newest first, latest expanded, older ones collapsed until asked", async () => {
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    const list = await screen.findByRole("list", { name: "MOT tests, newest first" });
    const entries = within(list).getAllByRole("listitem").filter((item) => item.classList.contains("drv-timeline-entry"));
    expect(entries).toHaveLength(3);
    expect(within(entries[0]!).getByText("51,950 miles · valid until 25 Aug 2027")).toBeInTheDocument();
    expect(within(entries[0]!).getByText("No defects or advisories")).toBeInTheDocument();
    expect(within(entries[0]!).getByText("Test no. 489904503767")).toBeInTheDocument();
    expect(within(entries[1]!).getByText("Failed")).toHaveClass("drv-result-failed");
    expect(within(entries[2]!).getByText("37,064 miles · first MOT")).toBeInTheDocument();
    expect(within(entries[1]!).queryByText("Brake pipe excessively corroded")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(entries[1]!).getByRole("button", { name: /Show details/ }));
    const defect = within(entries[1]!).getByText("Brake pipe excessively corroded").closest("li")!;
    expect(defect).toHaveClass("drv-defect-fail");
    expect(within(defect).getByText("Dangerous")).toBeInTheDocument();
  });

  it("shows no raw provider terminology", async () => {
    const { container } = render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    await screen.findByRole("list", { name: "MOT tests, newest first" });
    for (const raw of ["PASSED", "FAILED", "ADVISORY", "motTests", "odometerValue"]) {
      expect(container.textContent).not.toContain(raw);
    }
  });

  it("explains that MOT history is UK-only for other vehicles", async () => {
    (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue({ ...mot(317), eligible: false, tests: [] });
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(await screen.findByText("MOT history is only available for vehicles registered in the UK.")).toBeInTheDocument();
  });

  it("shows a not-found message for an inaccessible vehicle", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    render(<VehicleMotHistoryPage params={resolvedParams("v1")} />);
    expect(await screen.findByText("That vehicle could not be found.")).toBeInTheDocument();
  });
});
