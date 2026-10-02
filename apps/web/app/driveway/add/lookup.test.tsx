import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AddVehiclePage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/add",
}));
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({ activeHomeId: "home-1", activeHome: null, homes: [], setActiveHomeId: vi.fn(), loading: false }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, lookupVehicle: vi.fn(), createVehicle: vi.fn() } };
});

const { api, ApiError } = await import("@mykhaya/api-client");
const lookupVehicle = api.lookupVehicle as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Driveway UK vehicle lookup", () => {
  it("renders the UK registration field and disables lookup when empty", async () => {
    render(<AddVehiclePage />);
    expect(await screen.findByLabelText("Registration / licence plate")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find my vehicle" })).toBeDisabled();
  });

  it("sends AA19MOT normalised in the lookup payload", async () => {
    lookupVehicle.mockResolvedValue({ found: true, registration: "AA19MOT", make: "Test", model: "Vehicle", year: 2019, fuel_type: "Petrol", colour: "Black", engine_size: null, first_registration_date: null, capabilities: [], message: null });
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.type(await screen.findByLabelText("Registration / licence plate"), " aa19mot ");
    await user.click(screen.getByRole("button", { name: "Find my vehicle" }));
    await waitFor(() => expect(lookupVehicle).toHaveBeenCalledWith("home-1", { country_code: "GB", registration: "AA19MOT" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Test Vehicle");
  });

  it("preserves the entered VRN after a failed lookup", async () => {
    lookupVehicle.mockRejectedValue(new ApiError(502, "We can't check vehicle details right now."));
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    const input = await screen.findByLabelText("Registration / licence plate");
    await user.type(input, "AA19MOT");
    await user.click(screen.getByRole("button", { name: "Find my vehicle" }));
    expect(await screen.findByText("We can't check vehicle details right now.")).toBeInTheDocument();
    expect(input).toHaveValue("AA19MOT");
  });

  it("leaves unsupported countries on the manual-entry path", async () => {
    const user = userEvent.setup();
    render(<AddVehiclePage />);
    await user.selectOptions(await screen.findByLabelText(/country/i), "ZA");
    expect(screen.queryByLabelText("Registration / licence plate")).not.toBeInTheDocument();
    expect(screen.getByText(/Automatic vehicle lookup isn.t available/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add manually" }));
    expect(screen.getByLabelText("Registration / licence plate")).toBeInTheDocument();
    expect(lookupVehicle).not.toHaveBeenCalled();
  });
});
