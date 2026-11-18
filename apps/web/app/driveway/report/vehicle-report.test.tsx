import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@mykhaya/api-client";
import { render, screen } from "@testing-library/react";
import { VehicleReport } from "./vehicle-report";

const vehicle = {
  registration: "AA19MOT",
  make: "AUDI",
  model: "A4",
  colour: "Black",
  year: 2021,
  fuel_type: "Diesel",
  engine_size: "1968",
  first_registration_date: "2021-02-01",
  first_registration_precision: "month" as const,
  first_registration_with_dvla_date: null,
  first_registration_with_dvla_precision: null,
  tax_status: "Taxed",
  tax_due_date: "2027-02-01",
  inspection_status: "Valid",
  inspection_due_date: "2027-10-28",
  co2_emissions: 120,
  euro_status: "Euro 6",
  type_approval: "M1",
  wheel_plan: "2 AXLE RIGID BODY",
  revenue_weight: 1800,
  marked_for_export: false,
  marked_as_scrapped: false,
  date_of_last_v5c_issued: null,
  real_driving_emissions: null,
  vehicle_status: "Taxed",
  automated_vehicle: false,
  art_end_date: null,
  tax_calculation: {
    status: "conditional_estimate" as const,
    annual_rate: 200,
    payment_options: {},
    tax_year: "2026–2027",
    category: "post-2017 car",
    assumptions: [],
    missing_information: [],
    supplement_message: null,
    source: "DVLA V149",
    calculated_at: "2026-11-17T00:00:00Z",
  },
};

describe("VehicleReport", () => {
  it("renders the branded essential report and explains unavailable MOT data", () => {
    render(<VehicleReport source="lookup" format="essential" vehicle={vehicle} mot={null} />);
    expect(screen.getByRole("heading", { name: "Vehicle Report" })).toBeInTheDocument();
    expect(screen.getByText("£200 / year")).toBeInTheDocument();
    expect(screen.getByText(/arbitrary DVSA lookup is disabled/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Email me" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Share/ })).toBeDisabled();
    expect(screen.getByText(/Emailing and sharing reports isn’t available yet/)).toBeInTheDocument();
  });

  it("can switch from the essential report to the full report", async () => {
    render(<VehicleReport source="saved" format="essential" vehicle={vehicle} mot={null} />);
    expect(screen.queryByRole("heading", { name: "Additional vehicle details" })).not.toBeInTheDocument();
    await (await import("@testing-library/user-event")).default.setup().click(screen.getByRole("button", { name: "Full report" }));
    expect(screen.getByRole("heading", { name: "Additional vehicle details" })).toBeInTheDocument();
  });

  afterEach(() => vi.restoreAllMocks());

  it("lets a saved-vehicle report leave out the nickname and photo", async () => {
    const pdf = vi.spyOn(api, "vehicleReportPdf").mockResolvedValue({ filename: "r.pdf", content_type: "application/pdf", pdf_base64: btoa("%PDF-") });
    // jsdom has no object URLs; stub them for the download path only.
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:report") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = (await import("@testing-library/user-event")).default.setup();
    render(<VehicleReport source="saved" format="full" vehicle={{ ...vehicle, nickname: "Pebble" }} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    const toggle = screen.getByRole("checkbox", { name: "Include nickname and photo" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Save PDF" }));
    expect(pdf).toHaveBeenCalledWith("home-1", "vehicle-1", "full", false);
  });

  it("never offers household details on a one-off lookup report", () => {
    render(<VehicleReport source="lookup" format="essential" vehicle={vehicle} mot={null} />);
    expect(screen.queryByRole("checkbox", { name: "Include nickname and photo" })).not.toBeInTheDocument();
  });
});
