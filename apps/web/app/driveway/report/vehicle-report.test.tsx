import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@mykhaya/api-client";
import { render, screen, within } from "@testing-library/react";
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
    const toggle = screen.getByRole("switch", { name: "Include nickname and photo" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Save PDF" }));
    expect(pdf).toHaveBeenCalledWith("home-1", "vehicle-1", "full", false);
  });

  it("never offers household details on a one-off lookup report", () => {
    render(<VehicleReport source="lookup" format="essential" vehicle={vehicle} mot={null} />);
    expect(screen.queryByRole("switch", { name: "Include nickname and photo" })).not.toBeInTheDocument();
  });

  it("shows tax and MOT at a glance with the formatted plate", () => {
    const mot = {
      status: "valid",
      due_date: "2099-08-25",
      first_mot_due_date: null,
      refreshed_at: null,
      tests: [
        { test_number: "1", test_date: "2026-08-07", completed_at: null, expiry_date: null, result: "passed" as const, odometer_value: 51950, odometer_unit: "mi" as const, odometer_result: null, defects: [] },
        { test_number: "2", test_date: "2025-08-22", completed_at: null, expiry_date: null, result: "failed" as const, odometer_value: null, odometer_unit: null, odometer_result: null, defects: [] },
      ],
    };
    render(<VehicleReport source="lookup" format="full" vehicle={{ ...vehicle, registration: "AP22OOJ" }} mot={mot} />);
    expect(screen.getByText("AP22 OOJ")).toBeInTheDocument();
    expect(screen.getAllByText("Taxed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Valid").length).toBeGreaterThan(0);
    expect(screen.getByText("Expires 25 Aug 2099")).toBeInTheDocument();
    const tests = screen.getByRole("list", { name: "MOT tests" });
    expect(tests).toHaveTextContent("7 Aug 2026");
    expect(tests).toHaveTextContent("51,950 miles");
    expect(tests).toHaveTextContent("Passed");
    expect(tests).toHaveTextContent("Failed");
    expect(tests).toHaveTextContent("Mileage unavailable");
  });

  it("lays the VED payment plans out as payment and total", () => {
    const options = {
      single_12_month_total: 200,
      monthly_direct_debit_per_month: 17.5,
      monthly_direct_debit_total: 210,
      six_month_direct_debit_payment: 105,
      six_month_direct_debit_total: 210,
      six_month_single_payment: 110,
      six_month_single_total: 220,
    };
    render(<VehicleReport source="lookup" format="full" vehicle={{ ...vehicle, tax_calculation: { ...vehicle.tax_calculation, payment_options: options } }} mot={null} />);
    const table = screen.getByRole("table", { name: "VED payment options" });
    expect(within(table).getByRole("rowheader", { name: "Monthly Direct Debit" }).closest("tr")).toHaveTextContent("£17.50/mo£210");
    expect(within(table).getByRole("rowheader", { name: "6-month single payment" }).closest("tr")).toHaveTextContent("£110£220");
    expect(within(table).getAllByRole("row")).toHaveLength(5);
  });

  it("hides the photo from the preview when household details are switched off", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} photo={<img alt="Car photo" src="data:," />} />);
    expect(screen.getByRole("img", { name: "Car photo" })).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Include nickname and photo" }));
    expect(screen.queryByRole("img", { name: "Car photo" })).not.toBeInTheDocument();
  });
});
