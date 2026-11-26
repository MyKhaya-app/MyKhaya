import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api, ApiError } from "@mykhaya/api-client";
import {
  PRINT_TAB_POLL_MS,
  PRINT_URL_MAX_LIFETIME_MS,
  openPrintWindow,
  showPdfInPrintWindow,
} from "./vehicle-report-print";
import { VehicleReport } from "./vehicle-report";

const native = vi.hoisted(() => ({ value: false }));
vi.mock("@/components/native-runtime", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/native-runtime")>()),
  isNativeShell: () => native.value,
}));
const presentNative = vi.hoisted(() => vi.fn());
vi.mock("./vehicle-report-native", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./vehicle-report-native")>()),
  presentNativeVehicleReport: presentNative,
}));

interface FakeTab {
  closed: boolean;
  opener: unknown;
  location: { href: string };
  document: { title: string; body: { textContent: string } };
  close: ReturnType<typeof vi.fn>;
}

function fakeTab(): FakeTab {
  const tab: FakeTab = {
    closed: false,
    opener: window,
    location: { href: "" },
    document: { title: "", body: { textContent: "" } },
    close: vi.fn(() => {
      tab.closed = true;
    }),
  };
  return tab;
}

let createUrl: ReturnType<typeof vi.fn>;
let revokeUrl: ReturnType<typeof vi.fn>;

beforeEach(() => {
  native.value = false;
  presentNative.mockReset();
  let next = 0;
  createUrl = vi.fn(() => `blob:report-${++next}`);
  revokeUrl = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createUrl });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeUrl });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const pdfResponse = { filename: "report.pdf", content_type: "application/pdf", pdf_base64: btoa("%PDF-1.4") };

describe("openPrintWindow", () => {
  it("opens a tab it can see (no noopener), then cuts the tab's link back to MyKhaya", () => {
    const tab = fakeTab();
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    expect(openPrintWindow()).toBe(tab);
    expect(open).toHaveBeenCalledWith("", "_blank");
    expect(open.mock.calls[0]).toHaveLength(2);
    expect(tab.opener).toBeNull();
  });

  it("reports a blocked tab as null", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(openPrintWindow()).toBeNull();
  });
});

describe("showPdfInPrintWindow cleanup", () => {
  it("keeps the PDF URL alive while the tab is open and releases it once the tab closes", () => {
    vi.useFakeTimers();
    const tab = fakeTab();
    expect(showPdfInPrintWindow(tab as unknown as Window, new Blob(["%PDF"]))).toBe(true);
    expect(tab.location.href).toBe("blob:report-1");
    vi.advanceTimersByTime(PRINT_TAB_POLL_MS * 5);
    expect(revokeUrl).not.toHaveBeenCalled();
    tab.closed = true;
    vi.advanceTimersByTime(PRINT_TAB_POLL_MS);
    expect(revokeUrl).toHaveBeenCalledExactlyOnceWith("blob:report-1");
    vi.advanceTimersByTime(PRINT_URL_MAX_LIFETIME_MS);
    expect(revokeUrl).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("releases the URL after the maximum lifetime if the tab is left open", () => {
    vi.useFakeTimers();
    const tab = fakeTab();
    showPdfInPrintWindow(tab as unknown as Window, new Blob(["%PDF"]));
    vi.advanceTimersByTime(PRINT_URL_MAX_LIFETIME_MS - 1);
    expect(revokeUrl).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(revokeUrl).toHaveBeenCalledExactlyOnceWith("blob:report-1");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("creates no URL for a tab the user already closed", () => {
    const tab = fakeTab();
    tab.closed = true;
    expect(showPdfInPrintWindow(tab as unknown as Window, new Blob(["%PDF"]))).toBe(false);
    expect(createUrl).not.toHaveBeenCalled();
  });
});

const vehicle = {
  registration: "AA19MOT", make: "AUDI", model: "A4", colour: "Black", year: 2021, fuel_type: "Diesel", engine_size: "1968",
  first_registration_date: "2021-02-01", first_registration_precision: "month" as const, first_registration_with_dvla_date: null,
  first_registration_with_dvla_precision: null, tax_status: "Taxed", tax_due_date: "2027-02-01", inspection_status: "Valid",
  inspection_due_date: "2027-10-28", co2_emissions: 120, euro_status: "Euro 6", type_approval: "M1", wheel_plan: "2 AXLE RIGID BODY",
  revenue_weight: 1800, marked_for_export: false, marked_as_scrapped: false, date_of_last_v5c_issued: null, real_driving_emissions: null,
  vehicle_status: "Taxed", automated_vehicle: false, art_end_date: null, tax_calculation: null,
};
const lookupResult = { ...vehicle, report_token: "signed-token" } as unknown as import("@mykhaya/shared-types").VehicleLookupResult;

describe("VehicleReport Print button (browser)", () => {
  it("opens the tab before requesting the PDF, then shows the generated PDF for the chosen format", async () => {
    const tab = fakeTab();
    const order: string[] = [];
    vi.spyOn(window, "open").mockImplementation(() => {
      order.push("open");
      return tab as unknown as Window;
    });
    const pdf = vi.spyOn(api, "vehicleReportPdf").mockImplementation(async () => {
      order.push("request");
      return pdfResponse;
    });
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Essential report" }));
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(await screen.findByText("PDF opened in a new tab. Use the PDF viewer's Print action.")).toBeInTheDocument();
    expect(order).toEqual(["open", "request"]);
    expect(pdf).toHaveBeenCalledWith("home-1", "vehicle-1", "essential", true);
    expect(tab.location.href).toBe("blob:report-1");
    expect(tab.opener).toBeNull();
    expect(revokeUrl).not.toHaveBeenCalled();
    expect(tab.close).not.toHaveBeenCalled();
  });

  it("prints a one-off lookup through its signed report token", async () => {
    const tab = fakeTab();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const pdf = vi.spyOn(api, "lookupReportPdf").mockResolvedValue(pdfResponse);
    render(<VehicleReport source="lookup" format="essential" vehicle={vehicle} mot={null} homeId="home-1" lookupResult={lookupResult} />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    await screen.findByText(/PDF opened in a new tab/);
    expect(pdf).toHaveBeenCalledWith("home-1", "signed-token", "essential");
    expect(tab.location.href).toBe("blob:report-1");
  });

  it("explains a blocked tab and does not request a PDF", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    const pdf = vi.spyOn(api, "vehicleReportPdf").mockResolvedValue(pdfResponse);
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(await screen.findByText(/Your browser blocked the PDF tab/)).toBeInTheDocument();
    expect(pdf).not.toHaveBeenCalled();
    expect(createUrl).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Print" })).toBeEnabled();
  });

  it("closes the waiting tab when the PDF can't be prepared", async () => {
    const tab = fakeTab();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    vi.spyOn(api, "vehicleReportPdf").mockRejectedValue(new Error("network"));
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(await screen.findByText("The PDF could not be prepared for printing. Please try again.")).toBeInTheDocument();
    expect(tab.close).toHaveBeenCalledOnce();
    expect(createUrl).not.toHaveBeenCalled();
  });

  it("shows the download limit message and closes the tab when rate limited", async () => {
    const tab = fakeTab();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    vi.spyOn(api, "vehicleReportPdf").mockRejectedValue(new ApiError(429, "You've reached the hourly report limit."));
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(await screen.findByText("You've reached the hourly report limit.")).toBeInTheDocument();
    expect(tab.close).toHaveBeenCalledOnce();
  });

  it("tells the user when they closed the tab before the PDF arrived", async () => {
    const tab = fakeTab();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    vi.spyOn(api, "vehicleReportPdf").mockImplementation(async () => {
      tab.closed = true;
      return pdfResponse;
    });
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(await screen.findByText(/The PDF tab was closed before the report was ready/)).toBeInTheDocument();
    expect(createUrl).not.toHaveBeenCalled();
  });
});

describe("VehicleReport Print button (native shell)", () => {
  it("keeps the native document actions and never opens a browser tab", async () => {
    native.value = true;
    const open = vi.spyOn(window, "open");
    vi.spyOn(api, "vehicleReportPdf").mockResolvedValue(pdfResponse);
    presentNative.mockResolvedValue(undefined);
    render(<VehicleReport source="saved" format="full" vehicle={vehicle} mot={null} homeId="home-1" vehicleId="vehicle-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    await waitFor(() => expect(presentNative).toHaveBeenCalledOnce());
    expect(presentNative.mock.calls[0]?.[1]).toBe("report.pdf");
    expect(presentNative.mock.calls[0]?.[2]).toBe(pdfResponse.pdf_base64);
    expect(open).not.toHaveBeenCalled();
    expect(await screen.findByText("PDF ready. Choose Print in the native document actions.")).toBeInTheDocument();
  });
});
