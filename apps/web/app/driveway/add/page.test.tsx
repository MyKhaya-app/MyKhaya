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
      lookupVehicle: vi.fn(),
      members: vi.fn(),
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
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
    { user_id: "test-user", display_name: "You" },
    { user_id: "u2", display_name: "Megan" },
  ]);
});

describe("Add vehicle — validation", () => {
  it("requires a country and registration before submitting", async () => {
    render(<AddVehiclePage />);
    expect(screen.getByRole("button", { name: "Find my vehicle" })).toBeDisabled();
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

  it("shows the signed-in owner without exposing the legacy scope switch", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    const owner = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Owner" });
    expect(owner.selectedOptions[0]).toHaveTextContent("You");
    expect(screen.queryByRole("tab", { name: "Household" })).not.toBeInTheDocument();
  });

  it("submits a manually-entered vehicle and routes to its detail page on success", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "v1",
      group_id: "home-1",
      owner_user_id: "u1",
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
    await user.click(screen.getByRole("button", { name: "Add manually" }));
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
      owner_user_id: "test-user",
      make: "BMW",
      model: "i4",
      // Nickname was left blank, so it is derived from make + model — the
      // backend requires a non-empty nickname even though Phase 3 treats it
      // as an optional, editable field.
      nickname: "BMW i4",
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/driveway/v1"));
  });

  it("never defaults the nickname to the registration when make and model are blank", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "v2" });
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    await waitFor(() => expect(api.createVehicle).toHaveBeenCalledTimes(1));
    const [, body] = (api.createVehicle as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(body).toMatchObject({ registration: "AP22 OOJ", nickname: "My vehicle" });
    expect(String(body.nickname).replace(/\s+/g, "")).not.toContain("AP22OOJ");
  });

  it("stays on the form and shows the API error when creation fails", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(400, "That registration is already in use."),
    );
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    expect(await screen.findByText("That registration is already in use.")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});

// The shared vehicle fields (../vehicle-fields.tsx) on the shared form
// primitives: each problem is shown on, and announced with, its own field.
describe("Add vehicle — field-level validation", () => {
  it("shows a missing registration on the Registration field, focuses it and sends nothing", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.click(await screen.findByRole("button", { name: "Add manually" }));
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    const registration = screen.getByLabelText("Registration / licence plate");
    expect(registration).toHaveAttribute("aria-invalid", "true");
    expect(registration).toHaveAccessibleDescription("Add the registration.");
    await waitFor(() => expect(registration).toHaveFocus());
    expect(api.createVehicle).not.toHaveBeenCalled();

    await user.type(registration, "AP22 OOJ");
    expect(registration).not.toHaveAttribute("aria-invalid");
  });

  it("shows a year outside 1900–2200 on the Year field", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    await user.type(screen.getByLabelText("Year"), "1850");
    await user.click(screen.getByRole("button", { name: "Add vehicle" }));

    expect(screen.getByLabelText("Year")).toHaveAccessibleDescription("Enter a year between 1900 and 2200.");
    expect(api.createVehicle).not.toHaveBeenCalled();
  });

  it("shows a failed create next to the Add vehicle action and keeps what was entered", async () => {
    (api.createVehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(400, "That registration is already in use."));
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), "AP22 OOJ");
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    await user.type(screen.getByLabelText("Make"), "BMW");
    const add = screen.getByRole("button", { name: "Add vehicle" });
    await user.click(add);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That registration is already in use.");
    // Directly before the action it concerns, not at the top of the form.
    expect(alert.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Make")).toHaveValue("BMW");
    expect(add).toBeEnabled();
  });

  it("pairs short fields in shared rows and keeps the form's own validation", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.click(await screen.findByRole("button", { name: "Add manually" }));
    expect(screen.getByLabelText("Make").closest(".form-row")).toBe(screen.getByLabelText("Model").closest(".form-row"));
    expect(screen.getByLabelText("Year").closest(".form-row")).toBe(screen.getByLabelText("Fuel type").closest(".form-row"));
    expect(screen.getByLabelText("Make").closest("form")).toHaveAttribute("novalidate");
    expect(screen.getByLabelText("VIN / chassis number")).toHaveAccessibleDescription("Your VIN is only ever shown to you and your Home Admin.");
  });
});
