import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AddVehiclePage from "./page";

// Coverage for Driveway's manual Add Vehicle flow (Phase 3) — no DVLA/DVSA
// lookup yet, manual entry only. Mirrors the create-then-navigate pattern
// established in app/budget/_components/budget-module-wired.tsx.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/add",
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
      me: vi.fn(),
      featureMatrix: vi.fn(),
      billingStatus: vi.fn(),
      createVehicle: vi.fn(),
    },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({ features: [] });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({});
});

describe("Add vehicle — validation", () => {
  it("requires a country and registration before submitting", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));
    expect(
      await screen.findByText("Add a country and a registration to continue."),
    ).toBeInTheDocument();
    expect(api.createVehicle).not.toHaveBeenCalled();
  });
});

describe("Add vehicle — manual creation", () => {
  it("defaults the country to the United Kingdom, editable to any ISO-3166 country", async () => {
    render(<AddVehiclePage />);
    const select = await screen.findByLabelText<HTMLSelectElement>(/country/i);
    expect(select.value).toBe("GB");
    expect(screen.getByRole("option", { name: "South Africa" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "United States" })).toBeInTheDocument();
  });

  it("defaults scope to Household and allows switching to Personal", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    const household = await screen.findByRole("tab", { name: "Household" });
    const personal = screen.getByRole("tab", { name: "Personal" });
    expect(household).toHaveAttribute("aria-selected", "true");
    await user.click(personal);
    expect(personal).toHaveAttribute("aria-selected", "true");
    expect(household).toHaveAttribute("aria-selected", "false");
  });

  it("submits a manually-entered vehicle and routes to its detail page on success", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "v1",
      group_id: "home-1",
      owner_user_id: "u1",
      scope: "household",
      nickname: "BMW i4",
      make: "BMW",
      model: "i4",
      colour: null,
      year: null,
      fuel_type: null,
      engine_size: null,
      country_code: "GB",
      registration: "AP22 OOJ",
      first_registration_date: null,
      vin: null,
      archived: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.type(screen.getByLabelText(/^make$/i), "BMW");
    await user.type(screen.getByLabelText(/^model$/i), "i4");
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    await waitFor(() => expect(api.createVehicle).toHaveBeenCalledTimes(1));
    const [homeId, body] = (api.createVehicle as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(homeId).toBe("home-1");
    expect(body).toMatchObject({
      registration: "AP22 OOJ",
      country_code: "GB",
      scope: "household",
      make: "BMW",
      model: "i4",
      // Nickname was left blank, so it is derived from make + model — the
      // backend requires a non-empty nickname even though Phase 3 treats it
      // as an optional, editable field.
      nickname: "BMW i4",
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/driveway/v1"));
  });

  it("stays on the form and shows the API error when creation fails", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(400, "That registration is already in use."),
    );
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    expect(await screen.findByText("That registration is already in use.")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
