// Shared Driveway presentation: MOT status (one rule, used by every screen),
// dates, number plates, vehicle names and mileage. Pure functions so the
// wording and thresholds are unit-tested once.
import type { Vehicle, VehicleMotTest } from "@mykhaya/shared-types";

// ---- dates -------------------------------------------------------------------

// Fixed month names: Intl's en-GB short month is "Sept" on newer ICU builds,
// but Driveway dates are always "D Mon YYYY".
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function localDate(iso: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "25 Aug 2027". */
export function formatShortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = localDate(iso);
  if (!date) return null;
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

/** Whole days from `today` (local calendar date) to the ISO date. */
export function daysUntil(iso: string, today: Date = new Date()): number | null {
  const date = localDate(iso);
  if (!date) return null;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((date.getTime() - start.getTime()) / 86_400_000);
}

export function dayCount(days: number): string {
  return `${days} ${days === 1 ? "day" : "days"}`;
}

/** "3 min ago" / "2 hr ago" / "yesterday" — when MOT data was last checked. */
export function checkedAgo(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  const seconds = Math.round((then.getTime() - now.getTime()) / 1000);
  const format = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto", style: "short" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

// ---- MOT status ----------------------------------------------------------------

/** valid: > 30 days left · soon: 0–30 days · expired: past · none: no usable date. */
export type MotTone = "valid" | "soon" | "expired" | "none";

export type MotState = {
  tone: MotTone;
  daysLeft: number | null;
  dueDate: string | null;
  /** The provider-neutral status code (valid / expired / not_yet_due / no_record / null). */
  status: string | null;
  firstMot: boolean;
};

export const MOT_DUE_SOON_DAYS = 30;

export function motState(
  status: string | null | undefined,
  dueDate: string | null | undefined,
  today: Date = new Date(),
): MotState {
  const base = { status: status ?? null, dueDate: dueDate ?? null, firstMot: status === "not_yet_due" };
  if (status === "no_record" || !dueDate) return { ...base, tone: "none", daysLeft: null };
  const daysLeft = daysUntil(dueDate, today);
  if (daysLeft === null) return { ...base, tone: "none", daysLeft: null };
  const tone: MotTone = daysLeft < 0 ? "expired" : daysLeft <= MOT_DUE_SOON_DAYS ? "soon" : "valid";
  return { ...base, tone, daysLeft };
}

export function vehicleMotState(vehicle: Vehicle, today: Date = new Date()): MotState {
  return motState(vehicle.inspection_status, vehicle.inspection_due_date, today);
}

/** True when the MOT needs attention (due within 30 days, or expired). */
export function motNeedsAttention(state: MotState): boolean {
  return state.tone === "soon" || state.tone === "expired";
}

function noneLabel(state: MotState): string {
  return state.status === null ? "MOT not checked yet" : "No MOT record found";
}

/** Pill wording on the vehicle page: "MOT valid" / "MOT due in 12 days" / "MOT expired". */
export function motPillLabel(state: MotState): string {
  switch (state.tone) {
    case "valid":
      return state.firstMot ? "First MOT not due yet" : "MOT valid";
    case "soon":
      return `${state.firstMot ? "First MOT" : "MOT"} due in ${dayCount(state.daysLeft ?? 0)}`;
    case "expired":
      return "MOT expired";
    default:
      return noneLabel(state);
  }
}

/** Pill wording on the green MOT history card: "Valid" / "Due in 12 days" / "MOT expired". */
export function motShortLabel(state: MotState): string {
  switch (state.tone) {
    case "valid":
      return state.firstMot ? "Not yet due" : "Valid";
    case "soon":
      return `Due in ${dayCount(state.daysLeft ?? 0)}`;
    case "expired":
      return "MOT expired";
    default:
      return noneLabel(state);
  }
}

/** Driveway list pill: "MOT valid · 25 Aug 2027" / "MOT due in 12 days". */
export function motListLabel(state: MotState): string {
  if (state.tone === "valid") {
    const date = formatShortDate(state.dueDate);
    return `${state.firstMot ? "First MOT due" : "MOT valid"}${date ? ` · ${date}` : ""}`;
  }
  return motPillLabel(state);
}

/** "317 days left" / "Expired 4 days ago". */
export function motDaysText(state: MotState): string | null {
  if (state.daysLeft === null) return null;
  if (state.daysLeft < 0) return `Expired ${dayCount(-state.daysLeft)} ago`;
  return `${dayCount(state.daysLeft)} left`;
}

/** "Expires 25 Aug 2027" (or "First MOT due …" for a vehicle not yet tested). */
export function motExpiryText(state: MotState): string | null {
  const date = formatShortDate(state.dueDate);
  if (!date) return null;
  return state.firstMot ? `First MOT due ${date}` : `Expires ${date}`;
}

// ---- number plates and names -----------------------------------------------------

const UK_CURRENT_FORMAT = /^[A-Z]{2}[0-9]{2}[A-Z]{3}$/;

/** "AP22OOJ" → "AP22 OOJ". Anything not in the standard 7-character format
 *  (e.g. "DEV2BTEST2", a cherished plate) is shown as stored. */
export function formatPlate(registration: string | null | undefined): string | null {
  if (!registration) return null;
  const compact = registration.replace(/\s+/g, "").toUpperCase();
  if (UK_CURRENT_FORMAT.test(compact)) return `${compact.slice(0, 4)} ${compact.slice(4)}`;
  return registration.trim().toUpperCase();
}

// Makes whose brand name is all capitals.
const UPPERCASE_MAKES = new Set(["BMW", "MG", "VW", "DS", "GMC", "BYD", "MINI", "LEVC", "LDV", "DAF", "KTM"]);

/** "BMW" stays "BMW"; "MERCEDES-BENZ" → "Mercedes-Benz"; "bmw" → "BMW".
 *  A make already typed in mixed case (e.g. "McLaren") is left alone. */
export function formatMake(make: string): string {
  const trimmed = make.trim().replace(/\s+/g, " ");
  if (UPPERCASE_MAKES.has(trimmed.toUpperCase())) return trimmed.toUpperCase();
  if (trimmed !== trimmed.toUpperCase() && trimmed !== trimmed.toLowerCase()) return trimmed;
  return trimmed.toLowerCase().replace(/(^|[\s-])([a-z])/g, (_, sep: string, letter: string) => sep + letter.toUpperCase());
}

/** Make + model ("BMW i4") when both are known, otherwise the nickname. */
export function vehicleName(vehicle: Pick<Vehicle, "make" | "model" | "nickname">): string {
  if (vehicle.make?.trim() && vehicle.model?.trim()) return `${formatMake(vehicle.make)} ${vehicle.model.trim()}`;
  return vehicle.nickname;
}

/** "2022 · Electric · White", or null when none are known. */
export function vehicleMeta(vehicle: Pick<Vehicle, "year" | "fuel_type" | "colour">): string | null {
  const parts = [vehicle.year ? String(vehicle.year) : null, vehicle.fuel_type, vehicle.colour].filter(
    (part): part is string => Boolean(part && part.trim()),
  );
  return parts.length ? parts.join(" · ") : null;
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? `${parts[0]![0]}${parts[parts.length - 1]![0]}` : (parts[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}

// ---- MOT tests -----------------------------------------------------------------------

/** "51,950 mi" (short) / "51,950 miles" (long); km stays km. */
export function formatMileage(test: Pick<VehicleMotTest, "odometer_value" | "odometer_unit">, long = false): string | null {
  if (test.odometer_value === null) return null;
  const unit = test.odometer_unit === "km" ? "km" : long ? "miles" : "mi";
  return `${test.odometer_value.toLocaleString("en-GB")} ${unit}`;
}

/** Most recent recorded mileage across tests (newest first). */
export function lastMileage(tests: VehicleMotTest[]): string | null {
  const test = tests.find((item) => item.odometer_value !== null);
  return test ? formatMileage(test) : null;
}

/** Difference between the two most recent readings in the same unit. */
export function milesBetweenTests(tests: VehicleMotTest[]): number | null {
  const readings = tests.filter((item) => item.odometer_value !== null);
  const [latest, previous] = readings;
  if (!latest || !previous || latest.odometer_unit !== previous.odometer_unit) return null;
  const diff = (latest.odometer_value ?? 0) - (previous.odometer_value ?? 0);
  return diff >= 0 ? diff : null;
}

const FAILURE = new Set(["dangerous", "major", "fail"]);

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "no defects or advisories" / "2 advisories" / "1 failure · 1 advisory". */
export function testSummary(test: VehicleMotTest): string {
  const failures = test.defects.filter((defect) => FAILURE.has(defect.category)).length;
  const minor = test.defects.filter((defect) => defect.category === "minor").length;
  const advisories = test.defects.filter((defect) => defect.category === "advisory").length;
  const parts = [
    failures ? plural(failures, "failure", "failures") : null,
    minor ? plural(minor, "minor defect", "minor defects") : null,
    advisories ? plural(advisories, "advisory", "advisories") : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "no defects or advisories";
}

export function isFailureDefect(category: string): boolean {
  return FAILURE.has(category);
}

/** "A", "A and B", "A, B and C". */
export function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
