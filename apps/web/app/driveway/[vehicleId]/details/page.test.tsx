import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleDetailsEditPage from "./page";

// Coverage for Driveway's Vehicle details edit screen (Phase 3).

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/v1/details",
}));

let relationship = "home_admin";
let currentUserId = "u1";
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: { id: currentUserId, display_name: "Megan", principal_type: "adult" } }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      vehicle: vi.fn(),
      updateVehicle: vi.fn(),
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
  vin: "WBA12345678901234",
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

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
  return render(<VehicleDetailsEditPage params={resolvedParams(vehicleId)} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  relationship = "home_admin";
  currentUserId = "u1";
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
});

describe("Vehicle details — editing", () => {
  it("pre-fills the form from the authoritative API values", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("BMW i4")).toBeInTheDocument();
    expect(screen.getByDisplayValue("BMW")).toBeInTheDocument();
    expect(screen.getByDisplayValue("i4")).toBeInTheDocument();
    expect(screen.getByDisplayValue("AP22 OOJ")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2022")).toBeInTheDocument();
  });

  it("shows the VIN field for the vehicle's own owner", async () => {
    renderPage();
    await screen.findByDisplayValue("BMW i4");
    expect(screen.getByLabelText(/vin/i)).toHaveValue("WBA12345678901234");
  });

  it("hides the VIN field for a household member who is not the owner or a home_admin", async () => {
    relationship = "partner";
    currentUserId = "u2";
    renderPage();
    await screen.findByDisplayValue("BMW i4");
    expect(screen.queryByLabelText(/vin/i)).not.toBeInTheDocument();
  });

  it("saves changes and routes back to the vehicle detail page", async () => {
    (api.updateVehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ ...VEHICLE, nickname: "i4" });
    const user = userEvent.setup();
    renderPage();
    const nickname = await screen.findByDisplayValue("BMW i4");
    await user.clear(nickname);
    await user.type(nickname, "i4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.updateVehicle).toHaveBeenCalledTimes(1));
    const [homeId, vehicleId, body] = (api.updateVehicle as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      string,
      Record<string, unknown>,
    ];
    expect(homeId).toBe("home-1");
    expect(vehicleId).toBe("v1");
    expect(body).toMatchObject({ nickname: "i4", expected_updated_at: VEHICLE.updated_at });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/driveway/v1"));
  });

  it("stays on the form and shows the API error when saving fails", async () => {
    (api.updateVehicle as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(409, "This vehicle changed. Reload and try again."),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByDisplayValue("BMW i4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("This vehicle changed. Reload and try again."),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
