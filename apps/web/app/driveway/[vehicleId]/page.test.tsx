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

beforeEach(() => {
  vi.clearAllMocks();
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
