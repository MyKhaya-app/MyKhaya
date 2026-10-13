import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DrivewayPage from "./page";

// Driveway list (Screen 1): person filter chips, the MOT summary strip, the
// vehicle cards and the empty state. MOT dates are relative to today so the
// shared 30-day rule is exercised without fake timers.

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

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: { id: "u1", display_name: "Anthony Hales" } }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: { ...actual.api, billingStatus: vi.fn(), featureMatrix: vi.fn(), vehicles: vi.fn(), members: vi.fn() },
  };
});

const { api } = await import("@mykhaya/api-client");

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

function mockModuleState({ featureOn = true, entitled = true } = {}) {
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({ features: [{ feature: "driveway", enabled: featureOn }] });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ driveway_enabled: entitled });
}

const BMW = {
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
  vin: null,
  inspection_status: "valid",
  inspection_due_date: iso(317),
  tax_status: null,
  tax_due_date: null,
  photo_version: null,
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const TEST_CAR = {
  ...BMW,
  id: "v2",
  nickname: "My vehicle",
  make: null,
  model: null,
  year: null,
  fuel_type: null,
  colour: null,
  registration: "DEV2BTEST2",
  inspection_status: "no_record",
  inspection_due_date: null,
};

const MEMBERS = [
  { user_id: "u1", display_name: "Anthony Hales", colour: "green" },
  { user_id: "u2", display_name: "Megan Hales", colour: "rose" },
];

function mockVehicles(items: object[]) {
  (api.vehicles as ReturnType<typeof vi.fn>).mockResolvedValue({ items });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockModuleState();
  mockVehicles([]);
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue(MEMBERS);
});

describe("Driveway list — header and filters", () => {
  it("shows the Home eyebrow, title, subtitle and the existing illustration", async () => {
    mockVehicles([BMW]);
    const { container } = render(<DrivewayPage />);
    expect(await screen.findByText("Everyone's vehicles, MOTs and key details in one place.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Driveway" })).toBeInTheDocument();
    expect(screen.getByText("Home", { selector: ".drv-eyebrow" })).toBeInTheDocument();
    expect(container.querySelector("img.drv-heading-art")).toHaveAttribute("src", "/images/Driveway-asset.png");
  });

  it("offers All, Mine and each other family member, and filters by owner", async () => {
    mockVehicles([BMW, { ...TEST_CAR, owner_user_id: "u2" }]);
    render(<DrivewayPage />);
    const group = await screen.findByRole("group", { name: "Filter by person" });
    const chips = within(group).getAllByRole("button").map((chip) => chip.textContent);
    expect(chips).toEqual(["All", "Mine", "Megan"]);
    expect(within(group).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");

    const user = userEvent.setup();
    await user.click(within(group).getByRole("button", { name: "Mine" }));
    expect(screen.getByText("BMW i4")).toBeInTheDocument();
    expect(screen.queryByText("My vehicle")).not.toBeInTheDocument();
    await user.click(within(group).getByRole("button", { name: "Megan" }));
    expect(screen.getByText("My vehicle")).toBeInTheDocument();
    expect(screen.queryByText("BMW i4")).not.toBeInTheDocument();
  });

  it("shows a friendly empty state with an add action for that person", async () => {
    mockVehicles([BMW]);
    render(<DrivewayPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Megan" }));
    expect(screen.getByText("No vehicles for Megan yet")).toBeInTheDocument();
    expect(screen.getByText("Add one with just the registration – we'll look up the MOT.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a vehicle for Megan" })).toHaveAttribute("href", "/driveway/add?owner=u2");
    expect(screen.queryByText(/All MOTs in date/)).not.toBeInTheDocument();
  });
});

describe("Driveway list — vehicle cards", () => {
  it("shows make + model, a formatted plate chip, details, owner and MOT pill", async () => {
    mockVehicles([BMW, TEST_CAR]);
    render(<DrivewayPage />);
    const link = (await screen.findByText("BMW i4")).closest("a")!;
    expect(link).toHaveAttribute("href", "/driveway/v1");
    expect(within(link).getByText("AP22 OOJ")).toHaveClass("drv-plate");
    expect(within(link).getByText("2022 · Electric · White")).toBeInTheDocument();
    expect(within(link).getByRole("img", { name: "Owner: Anthony Hales" })).toHaveTextContent("AH");
    expect(within(link).getByText(`MOT valid · ${short(317)}`)).toHaveClass("drv-pill-valid");

    const other = screen.getByText("My vehicle").closest("a")!;
    expect(within(other).getByText("DEV2BTEST2")).toBeInTheDocument();
    expect(within(other).getByText("Add make and model")).toBeInTheDocument();
    expect(within(other).getByText("No MOT record found")).toHaveClass("drv-pill-none");
  });

  it("turns the pill and summary strip red at 30 days or fewer", async () => {
    mockVehicles([{ ...BMW, inspection_due_date: iso(12) }]);
    render(<DrivewayPage />);
    expect(await screen.findByText("MOT due in 12 days")).toHaveClass("drv-pill-soon");
    const strip = screen.getByText(/BMW i4 MOT due in 12 days/).closest("p")!;
    expect(strip).toHaveClass("drv-strip-urgent");
    expect(within(strip).getByText(short(12))).toBeInTheDocument();
  });

  it("uses the singular for one day and flags an expired MOT", async () => {
    mockVehicles([{ ...BMW, inspection_due_date: iso(1) }, { ...BMW, id: "v3", nickname: "Old", make: "Ford", model: "Ka", inspection_status: "expired", inspection_due_date: iso(-4) }]);
    render(<DrivewayPage />);
    expect(await screen.findByText("MOT due in 1 day")).toBeInTheDocument();
    expect(screen.getByText("MOT expired")).toHaveClass("drv-pill-expired");
    // The most urgent vehicle leads the strip.
    expect(screen.getByText(/Ford Ka MOT expired/)).toBeInTheDocument();
  });

  it("says all MOTs are in date with the earliest expiry when none are due", async () => {
    mockVehicles([BMW, { ...BMW, id: "v4", inspection_due_date: iso(200) }]);
    render(<DrivewayPage />);
    const strip = (await screen.findByText(/All MOTs in date · next due/)).closest("p")!;
    expect(strip).not.toHaveClass("drv-strip-urgent");
    expect(within(strip).getByText(short(200))).toBeInTheDocument();
  });

  it("shows no MOT pill for a vehicle outside the UK", async () => {
    mockVehicles([{ ...BMW, country_code: "ZA", registration: "CA 123-456" }]);
    render(<DrivewayPage />);
    await screen.findByText("BMW i4");
    expect(document.querySelector(".drv-pill")).toBeNull();
    expect(screen.queryByText(/MOTs in date|MOT valid/)).not.toBeInTheDocument();
  });

  it("keeps the floating Add vehicle action", async () => {
    mockVehicles([BMW]);
    render(<DrivewayPage />);
    await screen.findByText("BMW i4");
    const add = screen.getByRole("link", { name: "Add vehicle" });
    expect(add).toHaveAttribute("href", "/driveway/add");
    expect(add).toHaveClass("rr-fab");
  });
});

describe("Driveway list — module/entitlement state", () => {
  it("shows an inline message when the platform feature flag is off", async () => {
    mockModuleState({ featureOn: false, entitled: true });
    render(<DrivewayPage />);
    expect(await screen.findByText("Driveway isn't available for this Home yet. Please check back soon.")).toBeInTheDocument();
  });

  it("shows the Ultimate upsell and never loads vehicles when not entitled", async () => {
    mockModuleState({ featureOn: true, entitled: false });
    mockVehicles([BMW]);
    render(<DrivewayPage />);
    expect(await screen.findByText("Included with MyKhaya Ultimate.")).toBeInTheDocument();
    expect(screen.queryByText("BMW i4")).not.toBeInTheDocument();
    expect(api.vehicles).not.toHaveBeenCalled();
  });
});
