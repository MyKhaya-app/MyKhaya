"use client";

import { useState, type ReactNode } from "react";
import {
  Download,
  ExternalLink,
  Info,
  Mail,
  Printer,
  Share2,
} from "lucide-react";
import type {
  Vehicle,
  VehicleLookupResult,
  VehicleMot,
  VehicleTaxCalculation,
} from "@mykhaya/shared-types";
import { Logo } from "@/components/logo";
import { api, ApiError } from "@mykhaya/api-client";
import { isNativeShell } from "@/components/native-runtime";
import {
  formatMileage,
  formatPlate,
  formatRegistrationDate,
  formatShortDate,
  motExpiryText,
  motShortLabel,
  motState,
  type MotTone,
} from "../vehicle-display";
import {
  NativeVehicleReportError,
  presentNativeVehicleReport,
} from "./vehicle-report-native";
import { openPrintWindow, showPdfInPrintWindow } from "./vehicle-report-print";

type ReportVehicle = Pick<
  VehicleLookupResult,
  | "registration"
  | "make"
  | "model"
  | "colour"
  | "year"
  | "fuel_type"
  | "engine_size"
  | "first_registration_date"
  | "first_registration_precision"
  | "first_registration_with_dvla_date"
  | "first_registration_with_dvla_precision"
  | "tax_status"
  | "tax_due_date"
  | "inspection_status"
  | "inspection_due_date"
  | "co2_emissions"
  | "euro_status"
  | "type_approval"
  | "wheel_plan"
  | "revenue_weight"
  | "marked_for_export"
  | "marked_as_scrapped"
  | "date_of_last_v5c_issued"
  | "real_driving_emissions"
  | "vehicle_status"
  | "automated_vehicle"
  | "art_end_date"
> & {
  nickname?: string | null;
  country_code?: string | null;
  last_successful_lookup?: string | null;
  tax_calculation?: VehicleTaxCalculation | null;
};
type ReportMot = VehicleMot | NonNullable<VehicleLookupResult["mot"]> | null;

export interface VehicleReportProps {
  source: "saved" | "lookup";
  format: "full" | "essential";
  vehicle: ReportVehicle;
  mot: ReportMot;
  taxCalculation?: VehicleTaxCalculation | null;
  photo?: ReactNode;
  homeId?: string;
  vehicleId?: string;
  lookupResult?: VehicleLookupResult;
}

function display(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  return null;
}

function Row({ label, value }: { label: string; value: unknown }) {
  const text = display(value);
  if (!text) return null;
  return (
    <div className="drv-report-row">
      <dt>{label}</dt>
      <dd>{text}</dd>
    </div>
  );
}

function Section({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`drv-report-section ${className}`.trim()}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function taxAmount(value: number | null | undefined): string | null {
  return value == null ? null : `£${value.toFixed(2).replace(/\.00$/, "")}`;
}

// Colours follow the shared Driveway pills (.drv-pill-valid / -expired / -none).
function taxTone(status: string | null | undefined): MotTone {
  if (!status) return "none";
  const normalised = status.trim().toLowerCase();
  if (normalised === "taxed") return "valid";
  if (normalised === "untaxed") return "expired";
  return "none";
}

function Pill({ tone, children }: { tone: MotTone; children: ReactNode }) {
  return (
    <span className={`drv-pill drv-pill-small drv-pill-${tone}`}>{children}</span>
  );
}

const RESULT_LABELS: Record<string, string> = {
  passed: "Passed",
  failed: "Failed",
  other: "Other",
};
const RESULT_TONES: Record<string, MotTone> = {
  passed: "valid",
  failed: "expired",
};

// The VED payment plans DVLA offers, as pairs of the calculator's
// payment_options keys (see apps/api/mykhaya/driveway_tax.py). A plan is shown
// only when both of its amounts are present.
const PAYMENT_PLANS: Array<{
  label: string;
  payment: string;
  total: string;
  perMonth?: boolean;
}> = [
  {
    label: "12-month payment",
    payment: "single_12_month_total",
    total: "single_12_month_total",
  },
  {
    label: "Monthly Direct Debit",
    payment: "monthly_direct_debit_per_month",
    total: "monthly_direct_debit_total",
    perMonth: true,
  },
  {
    label: "6-month Direct Debit",
    payment: "six_month_direct_debit_payment",
    total: "six_month_direct_debit_total",
  },
  {
    label: "6-month single payment",
    payment: "six_month_single_payment",
    total: "six_month_single_total",
  },
];

function PaymentOptions({ options }: { options: Record<string, number> }) {
  const plans = PAYMENT_PLANS.filter(
    (plan) => options[plan.payment] != null && options[plan.total] != null,
  );
  const known = new Set(plans.flatMap((plan) => [plan.payment, plan.total]));
  const other = Object.entries(options).filter(([key]) => !known.has(key));
  if (!plans.length && !other.length) return null;
  return (
    <>
      {plans.length > 0 && (
        <table className="drv-report-payments">
          <caption className="sr-only">VED payment options</caption>
          <thead>
            <tr>
              <th scope="col">How you pay</th>
              <th scope="col">Payment</th>
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((plan) => (
              <tr key={plan.label}>
                <th scope="row">{plan.label}</th>
                <td>
                  {taxAmount(options[plan.payment])}
                  {plan.perMonth ? "/mo" : ""}
                </td>
                <td>{taxAmount(options[plan.total])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {other.length > 0 && (
        <dl className="drv-report-payments-other">
          {other.map(([key, amount]) => (
            <Row key={key} label={key.replaceAll("_", " ")} value={taxAmount(amount)} />
          ))}
        </dl>
      )}
    </>
  );
}

function motTests(mot: ReportMot) {
  if (!mot || !mot.tests.length) return null;
  return (
    <ol className="drv-report-tests" aria-label="MOT tests">
      {mot.tests.map((test, index) => (
        <li
          className="drv-report-test"
          key={`${test.test_number ?? "test"}-${test.test_date}-${index}`}
        >
          <span
            className={`drv-report-test-dot${index === 0 ? " drv-report-test-dot-latest" : ""}`}
            aria-hidden="true"
          />
          <div className="drv-report-test-body">
            <div className="drv-report-test-top">
              <span className="drv-report-test-date">
                {formatShortDate(test.test_date) ?? test.test_date}
              </span>
              <Pill tone={RESULT_TONES[test.result] ?? "none"}>
                {RESULT_LABELS[test.result] ?? test.result}
              </Pill>
            </div>
            <span className="drv-report-test-miles">
              {formatMileage(test, true) ?? "Mileage unavailable"}
            </span>
            {test.defects.length > 0 && (
              <ul className="drv-report-defects">
                {test.defects.map((defect, defectIndex) => (
                  <li key={`${defect.category}-${defectIndex}`}>
                    {defect.dangerous ? "Dangerous: " : ""}
                    {defect.text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

// Outbound email and external sharing of reports stay off until the Owner
// approves them (the API refuses report email independently of this flag).
const REPORT_SHARING_AVAILABLE = false;

export function VehicleReport({
  source,
  format,
  vehicle,
  mot,
  taxCalculation = vehicle.tax_calculation,
  photo,
  homeId,
  vehicleId,
  lookupResult,
}: VehicleReportProps) {
  const [shareMessage, setShareMessage] = useState("");
  const [busy, setBusy] = useState<"save" | "print" | "email" | "share" | null>(null);
  const [reportFormat, setReportFormat] = useState<"full" | "essential">(
    format,
  );
  // Saved vehicles only: the household-entered nickname and the vehicle photo.
  // Switch off for a report that will be shared outside the Home.
  const [includeHousehold, setIncludeHousehold] = useState(true);
  const name =
    [vehicle.make, vehicle.model].filter(Boolean).join(" ") ||
    vehicle.nickname ||
    "Vehicle report";
  const isFull = reportFormat === "full";
  const motSummary = mot && "summary" in mot ? mot.summary : mot;
  const motStatus =
    motSummary && "status" in motSummary ? motSummary.status : null;
  const motDue =
    motSummary && "due_date" in motSummary ? motSummary.due_date : null;
  const motNow = motState(motStatus, motDue);
  const hasMotStatus = Boolean(motStatus || motDue);
  const taxDue = formatShortDate(vehicle.tax_due_date);
  const plate = formatPlate(vehicle.registration);
  // The household toggle also governs the on-screen preview, so what is shown
  // here matches the PDF that Save PDF / Print will produce.
  const showPhoto = Boolean(photo) && (source !== "saved" || includeHousehold);
  const tax = taxCalculation;
  const generated = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
  }).format(new Date());

  async function getPdf(): Promise<{
    blob: Blob;
    filename: string;
    base64: string;
  }> {
    const result =
      source === "saved" && vehicleId
        ? await api.vehicleReportPdf(
            homeId ?? "",
            vehicleId,
            reportFormat,
            includeHousehold,
          )
        : await api.lookupReportPdf(
            homeId ?? "",
            lookupResult?.report_token ?? "",
            reportFormat,
          );
    const bytes = Uint8Array.from(atob(result.pdf_base64), (char) =>
      char.charCodeAt(0),
    );
    return {
      blob: new Blob([bytes], { type: "application/pdf" }),
      filename: result.filename,
      base64: result.pdf_base64,
    };
  }

  function downloadPdf(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  async function savePdf() {
    setBusy("save");
    setShareMessage("");
    try {
      const report = await getPdf();
      if (isNativeShell()) {
        await presentNativeVehicleReport(
          report.blob,
          report.filename,
          report.base64,
          `Save MyKhaya Vehicle Report - ${name}`,
        );
        setShareMessage(
          "PDF ready. Choose Save to Files or another supported action.",
        );
      } else {
        downloadPdf(report.blob, report.filename);
        setShareMessage("PDF ready to save.");
      }
    } catch (error) {
      setShareMessage(
        error instanceof ApiError && error.status === 429
          ? error.message
          : error instanceof NativeVehicleReportError
            ? error.message
            : "The PDF could not be prepared. Please try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function printPdf() {
    const native = isNativeShell();
    // Browser: open the tab now, inside the click, before any await (see
    // vehicle-report-print.ts). A blocked tab costs no PDF request.
    const printWindow = native ? null : openPrintWindow();
    setShareMessage("");
    if (!native && !printWindow) {
      setShareMessage(
        "Your browser blocked the PDF tab. Allow pop-ups for MyKhaya, or use Save PDF.",
      );
      return;
    }
    setBusy("print");
    try {
      const report = await getPdf();
      if (native) {
        await presentNativeVehicleReport(
          report.blob,
          report.filename,
          report.base64,
          `Print MyKhaya Vehicle Report - ${name}`,
        );
        setShareMessage(
          "PDF ready. Choose Print in the native document actions.",
        );
        return;
      }
      if (!printWindow || !showPdfInPrintWindow(printWindow, report.blob)) {
        setShareMessage(
          "The PDF tab was closed before the report was ready. Press Print to try again.",
        );
        return;
      }
      setShareMessage(
        "PDF opened in a new tab. Use the PDF viewer's Print action.",
      );
    } catch (error) {
      printWindow?.close();
      setShareMessage(
        error instanceof ApiError && error.status === 429
          ? error.message
          : error instanceof NativeVehicleReportError
            ? error.message
            : "The PDF could not be prepared for printing. Please try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function share() {
    setBusy("share");
    setShareMessage("");
    try {
      const { blob, filename } = await getPdf();
      const file = new File([blob], filename, { type: "application/pdf" });
      if (
        navigator.share &&
        (!navigator.canShare || navigator.canShare({ files: [file] }))
      ) {
        await navigator.share({
          title: `MyKhaya Vehicle Report - ${name}`,
          files: [file],
        });
        return;
      }
      throw new Error("File sharing is unavailable in this environment.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setShareMessage("The PDF could not be prepared for sharing.");
    } finally {
      setBusy(null);
    }
  }

  async function email() {
    setBusy("email");
    setShareMessage("");
    try {
      if (source === "saved" && vehicleId)
        await api.emailVehicleReport(
          homeId ?? "",
          vehicleId,
          reportFormat,
          includeHousehold,
        );
      else
        await api.emailLookupReport(
          homeId ?? "",
          lookupResult?.report_token ?? "",
          reportFormat,
        );
      setShareMessage("Email queued to your verified MyKhaya account email.");
    } catch (error) {
      setShareMessage(
        error instanceof ApiError && [403, 409, 429].includes(error.status)
          ? error.message
          : "The report email could not be queued. Please try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  /*
    setShareMessage("");
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({ title: `MyKhaya Vehicle Report – ${name}`, text: `Vehicle Report for ${name}${vehicle.registration ? ` (${vehicle.registration})` : ""}`, url: window.location.href });
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShareMessage("Report link copied. The recipient must already have access to MyKhaya.");
    } catch {
      setShareMessage("Sharing is not available in this browser.");
    }
  } */

  const detailRows: Array<[string, unknown]> = [
    ["Registration", vehicle.registration],
    ["Make / model", name],
    ["Year", vehicle.year],
    [
      "First registration",
      formatRegistrationDate(
        vehicle.first_registration_date,
        vehicle.first_registration_precision ?? "day",
      ),
    ],
    [
      "First registered with DVLA",
      formatRegistrationDate(
        vehicle.first_registration_with_dvla_date,
        vehicle.first_registration_with_dvla_precision ?? "day",
      ),
    ],
    ["Fuel", vehicle.fuel_type],
    ["Colour", vehicle.colour],
    [
      "Engine capacity",
      vehicle.engine_size ? `${vehicle.engine_size} cc` : null,
    ],
    ["Country", vehicle.country_code],
  ];
  const additionalRows: Array<[string, unknown]> = [
    [
      "CO₂ emissions",
      vehicle.co2_emissions != null ? `${vehicle.co2_emissions} g/km` : null,
    ],
    ["Euro status", vehicle.euro_status],
    ["Type approval", vehicle.type_approval],
    ["Wheelplan", vehicle.wheel_plan],
    [
      "Revenue weight",
      vehicle.revenue_weight != null ? `${vehicle.revenue_weight} kg` : null,
    ],
    ["Marked for export", vehicle.marked_for_export],
    ["Marked as scrapped", vehicle.marked_as_scrapped],
    [
      "Last V5C issued",
      formatRegistrationDate(vehicle.date_of_last_v5c_issued, "day"),
    ],
    ["Real driving emissions", vehicle.real_driving_emissions],
    ["Automated vehicle", vehicle.automated_vehicle],
  ];

  return (
    <main className="drv-report" aria-labelledby="drv-report-title">
      <header className="drv-report-header">
        <div className="drv-report-brand">
          <Logo />
        </div>
        <div>
          <h1 id="drv-report-title">Vehicle Report</h1>
          <p>Generated {generated}</p>
        </div>
      </header>
      <div className="drv-report-toolbar">
        <div className="drv-report-controls">
          <div
            className="rr-segmented drv-report-format"
            role="group"
            aria-label="Report format"
          >
            <button
              type="button"
              className={`rr-segment${reportFormat === "full" ? " rr-segment-active" : ""}`}
              aria-pressed={reportFormat === "full"}
              onClick={() => setReportFormat("full")}
              disabled={busy !== null}
            >
              Full report
            </button>
            <button
              type="button"
              className={`rr-segment${reportFormat === "essential" ? " rr-segment-active" : ""}`}
              aria-pressed={reportFormat === "essential"}
              onClick={() => setReportFormat("essential")}
              disabled={busy !== null}
            >
              Essential report
            </button>
          </div>
          {source === "saved" && (
            <label className="drv-report-household">
              <span>Include nickname and photo</span>
              <input
                type="checkbox"
                role="switch"
                className="drv-report-switch"
                checked={includeHousehold}
                onChange={(event) => setIncludeHousehold(event.target.checked)}
                disabled={busy !== null}
              />
            </label>
          )}
        </div>
        <div className="drv-report-actions" aria-label="Report actions" role="group">
          <div className="drv-report-primary-actions">
            <button
              type="button"
              className="drv-report-button drv-report-button-primary"
              onClick={() => void savePdf()}
              disabled={busy !== null}
            >
              <Download size={20} aria-hidden="true" />
              {busy === "save" ? "Preparing…" : "Save PDF"}
            </button>
            <button
              type="button"
              className="drv-report-button drv-report-button-secondary"
              onClick={() => void printPdf()}
              disabled={busy !== null}
            >
              <Printer size={20} aria-hidden="true" />
              {busy === "print" ? "Preparing…" : "Print"}
            </button>
          </div>
          <div className="drv-report-sharing">
            <div className="drv-report-sharing-buttons">
              <button
                type="button"
                className="drv-report-button drv-report-button-quiet"
                onClick={() => void email()}
                disabled={busy !== null || !REPORT_SHARING_AVAILABLE}
                aria-describedby={
                  REPORT_SHARING_AVAILABLE ? undefined : "drv-report-sharing-note"
                }
              >
                <Mail size={18} aria-hidden="true" />
                {busy === "email" ? "Queueing…" : "Email me"}
              </button>
              <button
                type="button"
                className="drv-report-button drv-report-button-quiet"
                onClick={() => void share()}
                disabled={busy !== null || !REPORT_SHARING_AVAILABLE}
                aria-describedby={
                  REPORT_SHARING_AVAILABLE ? undefined : "drv-report-sharing-note"
                }
              >
                <Share2 size={18} aria-hidden="true" />
                {busy === "share" ? "Preparing…" : "Share"}
              </button>
            </div>
            {!REPORT_SHARING_AVAILABLE && (
              <p className="drv-report-sharing-note" id="drv-report-sharing-note">
                Emailing and sharing reports isn’t available yet. You can save or
                print the PDF.
              </p>
            )}
          </div>
        </div>
      </div>
      {shareMessage && (
        <p className="notice" role="status">
          {shareMessage}
        </p>
      )}
      <section className="drv-report-hero" aria-labelledby="drv-report-vehicle">
        {showPhoto && <div className="drv-report-photo">{photo}</div>}
        <div className="drv-report-hero-body">
          <div className="drv-report-hero-heading">
            <div>
              <p className="drv-report-eyebrow">
                {source === "saved" ? "Saved Home Vehicle" : "One-off Lookup"}
              </p>
              <h2 id="drv-report-vehicle">{name}</h2>
            </div>
            <span className="drv-report-plate">
              {plate ?? "Registration unavailable"}
            </span>
          </div>
          <p className="drv-report-hero-summary">
            {source === "saved"
              ? "Household vehicle information summary"
              : "Vehicle information summary"}
          </p>
          {(vehicle.tax_status || hasMotStatus) && (
            <dl className="drv-report-glance">
              {vehicle.tax_status && (
                <div>
                  <dt>Tax</dt>
                  <dd>
                    <Pill tone={taxTone(vehicle.tax_status)}>
                      {vehicle.tax_status}
                    </Pill>
                  </dd>
                  {taxDue && <dd>Due {taxDue}</dd>}
                </div>
              )}
              {hasMotStatus && (
                <div>
                  <dt>MOT</dt>
                  <dd>
                    <Pill tone={motNow.tone}>{motShortLabel(motNow)}</Pill>
                  </dd>
                  {motExpiryText(motNow) && <dd>{motExpiryText(motNow)}</dd>}
                </div>
              )}
            </dl>
          )}
        </div>
      </section>
      <div className="drv-report-grid">
        <Section title="Vehicle details">
          <dl>
            {detailRows.map(([label, value]) => (
              <Row key={label} label={label} value={value} />
            ))}
          </dl>
        </Section>
        <Section title="Tax and status">
          <dl>
            {vehicle.tax_status && (
              <div className="drv-report-row">
                <dt>Tax status</dt>
                <dd>
                  <Pill tone={taxTone(vehicle.tax_status)}>
                    {vehicle.tax_status}
                  </Pill>
                </dd>
              </div>
            )}
            <Row label="Tax due" value={taxDue} />
            <Row label="Vehicle status" value={vehicle.vehicle_status} />
            <Row
              label="SORN / export"
              value={
                vehicle.marked_for_export
                  ? "Marked for export"
                  : vehicle.marked_as_scrapped
                    ? "Marked as scrapped"
                    : null
              }
            />
          </dl>
          {tax && (
            <div className="drv-report-estimate">
              <span>Estimated annual VED</span>
              <strong>
                {taxAmount(tax.annual_rate) ?? "Unavailable"} / year
              </strong>
              <small>
                {tax.tax_year
                  ? `${tax.tax_year} tax year`
                  : "Tax year unavailable"}
                . Estimate only; check GOV.UK for the authoritative amount.
              </small>
              <PaymentOptions options={tax.payment_options} />
            </div>
          )}
          <p className="drv-report-source">
            <Info size={16} aria-hidden="true" /> DVLA tax and status
            information; VED figures are MyKhaya estimates.
          </p>
        </Section>
      </div>
      <Section title="MOT history" className="drv-report-mot">
        <dl>
          {hasMotStatus && (
            <div className="drv-report-row">
              <dt>Status</dt>
              <dd>
                <Pill tone={motNow.tone}>{motShortLabel(motNow)}</Pill>
              </dd>
            </div>
          )}
          <Row label="Expiry / due" value={formatShortDate(motDue)} />
        </dl>
        {mot ? (
          (motTests(mot) ?? (
            <p className="drv-report-muted">No detailed MOT tests were returned.</p>
          ))
        ) : (
          <p className="drv-report-muted">
            MOT history is unavailable for this report because arbitrary DVSA
            lookup is disabled.
          </p>
        )}
      </Section>
      {isFull && (
        <>
          <Section title="Additional vehicle details">
            <dl>
              {additionalRows.map(([label, value]) => (
                <Row key={label} label={label} value={value} />
              ))}
            </dl>
          </Section>
          <Section title="Data sources and privacy" className="drv-report-note">
            <p>
              Vehicle details, tax status and VED inputs are sourced from DVLA
              where available. MOT results are sourced from DVSA only through
              authorised saved-vehicle functionality.
            </p>
            <p>
              Private household data, authentication secrets, internal
              identifiers and full VIN values are excluded from this report.
            </p>
          </Section>
        </>
      )}
      <a
        className="drv-report-gov-link"
        href="https://www.gov.uk/check-vehicle-tax"
        target="_blank"
        rel="noreferrer"
      >
        Check vehicle tax on GOV.UK
        <ExternalLink size={16} aria-hidden="true" />
      </a>
      <footer className="drv-report-footer">
        <span>Generated with MyKhaya</span>
        <span>mykhaya.app</span>
      </footer>
    </main>
  );
}

export function savedVehicleReportVehicle(vehicle: Vehicle): ReportVehicle {
  return vehicle;
}
