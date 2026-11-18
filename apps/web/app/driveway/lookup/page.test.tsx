import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleLookupPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/driveway/lookup" }));
vi.mock("@/components/use-active-home", () => ({ useActiveHome: () => ({ activeHomeId: "home-1" }) }));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, lookupVehicle: vi.fn() } };
});

const { api } = await import("@mykhaya/api-client");
const lookupVehicle = api.lookupVehicle as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => vi.clearAllMocks());

describe("dedicated Driveway vehicle lookup", () => {
  it("normalises the registration and does not save until Add to Driveway", async () => {
    lookupVehicle.mockResolvedValue({
      found: true,
      registration: "AA19MOT",
      make: "AUDI",
      model: "A4",
      fuel_type: "Diesel",
      first_registration_date: "2021-02-01",
      first_registration_precision: "month",
      capabilities: ["tax"],
      mot: null,
    });
    const user = userEvent.setup();
    render(<VehicleLookupPage />);
    await user.type(screen.getByLabelText("Registration / licence plate"), " aa19mot ");
    await user.click(screen.getByRole("button", { name: "Check vehicle" }));
    await waitFor(() => expect(lookupVehicle).toHaveBeenCalledWith("home-1", { country_code: "GB", registration: "AA19MOT" }));
    expect(await screen.findByText("A4")).toBeInTheDocument();
    expect(screen.getByText("Feb 2021")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Vehicle Report" }));
    expect(push).toHaveBeenCalledWith("/driveway/lookup/report");
    expect(window.sessionStorage.getItem("mykhaya.driveway.lookup.report")).toContain("AA19MOT");
    push.mockClear();
    await user.click(screen.getByRole("button", { name: "Add to Driveway" }));
    expect(push).toHaveBeenCalledWith("/driveway/add");
    expect(window.sessionStorage.getItem("mykhaya.driveway.lookup.handoff")).toContain("AA19MOT");
  });
});
