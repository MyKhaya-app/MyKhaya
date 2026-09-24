import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import DrivewayPage from "./page";

// Coverage for the Driveway landing page — Phase 3 of the Driveway module
// (vehicle management, Ultimate-only). Mirrors the Lists/Budget
// module-state and empty/list-state patterns established in
// app/lists/page.test.tsx.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/driveway",
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
      billingStatus: vi.fn(),
      featureMatrix: vi.fn(),
      vehicles: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function mockModuleState(
  overrides: { featureOn?: boolean; entitled?: boolean } = {},
) {
  const { featureOn = true, entitled = true } = overrides;
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "driveway", enabled: featureOn }],
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    driveway_enabled: entitled,
  });
}

const PERSONAL_VEHICLE = {
  id: "v1",
  group_id: "home-1",
  owner_user_id: "u1",
  scope: "personal",
  nickname: "My little run-around",
  make: "Volkswagen",
  model: "Polo",
  colour: "Red",
  year: 2019,
  fuel_type: "Petrol",
  engine_size: "1.0",
  country_code: "GB",
  registration: "AB19 CDE",
  first_registration_date: "2019-03-01",
  vin: null,
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const HOUSEHOLD_VEHICLE = {
  ...PERSONAL_VEHICLE,
  id: "v2",
  scope: "household",
  nickname: "BMW i4",
  make: "BMW",
  model: "i4",
  colour: "Black",
  year: 2022,
  fuel_type: "Electric",
  registration: "AP22 OOJ",
};

beforeEach(() => {
  vi.clearAllMocks();
  mockModuleState();
  (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
});

describe("Driveway landing — empty state", () => {
  it("shows the empty state and an Add vehicle action when there are no vehicles", async () => {
    render(<DrivewayPage />);
    expect(await screen.findByText("Your Driveway is empty")).toBeInTheDocument();
    expect(
      screen.getByText("Add a vehicle and MyKhaya can help you keep track of the important bits."),
    ).toBeInTheDocument();
    const addLinks = screen.getAllByRole("link", { name: /add vehicle/i });
    expect(addLinks.some((link) => link.getAttribute("href") === "/driveway/add")).toBe(true);
  });
});

describe("Driveway landing — vehicle list", () => {
  it("renders a Personal vehicle as a normal card, linking to its detail page", async () => {
    (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [PERSONAL_VEHICLE] });
    render(<DrivewayPage />);
    const heading = await screen.findByText("My little run-around");
    const link = heading.closest("a")!;
    expect(link).toHaveAttribute("href", "/driveway/v1");
    expect(screen.getByText(/AB19 CDE/)).toBeInTheDocument();
    expect(screen.getByText(/2019 · Petrol · Red/)).toBeInTheDocument();
  });

  it("renders a Household vehicle alongside a Personal one", async () => {
    (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [PERSONAL_VEHICLE, HOUSEHOLD_VEHICLE],
    });
    render(<DrivewayPage />);
    expect(await screen.findByText("My little run-around")).toBeInTheDocument();
    expect(screen.getByText("BMW i4")).toBeInTheDocument();
    expect(screen.getByText(/AP22 OOJ/)).toBeInTheDocument();
  });

  it("does not fabricate MOT/tax/compliance data that the Phase 2 model does not provide", async () => {
    (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [PERSONAL_VEHICLE] });
    render(<DrivewayPage />);
    await screen.findByText("My little run-around");
    for (const fake of ["MOT", "Tax due", "Road tax", "Inspection due"]) {
      expect(screen.queryByText(fake)).not.toBeInTheDocument();
    }
  });
});

describe("Driveway landing — module/entitlement state", () => {
  it("shows an inline message, not a broken page, when the platform feature flag is off", async () => {
    mockModuleState({ featureOn: false, entitled: true });
    render(<DrivewayPage />);
    expect(
      await screen.findByText("Driveway isn't available for this Home yet. Please check back soon."),
    ).toBeInTheDocument();
  });

  it("shows the Ultimate upsell, not vehicle data, when the Home isn't entitled", async () => {
    mockModuleState({ featureOn: true, entitled: false });
    (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [PERSONAL_VEHICLE] });
    render(<DrivewayPage />);
    expect(await screen.findByText("Included with MyKhaya Ultimate.")).toBeInTheDocument();
    expect(screen.queryByText("My little run-around")).not.toBeInTheDocument();
    // The list endpoint must never even be called while not entitled —
    // direct-route access must not render Driveway data on a 403.
    expect(api.vehicles).not.toHaveBeenCalled();
  });
});
