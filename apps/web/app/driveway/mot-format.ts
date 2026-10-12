// Presentation helpers for Driveway MOT data. Pure functions so the wording
// is unit-tested once and shared by the vehicle card, the history page and
// the Driveway list. Inputs are the backend's provider-neutral values — this
// file never sees (or needs to know) DVSA field names.
import type {
  VehicleMotDefect,
  VehicleMotDefectCategory,
  VehicleMotStatus,
  VehicleMotSummary,
  VehicleMotTest,
} from "@mykhaya/shared-types";

const STATUS_LABELS: Record<VehicleMotStatus, string> = {
  valid: "Valid",
  expired: "Expired",
  not_yet_due: "Not yet due",
  no_record: "No MOT record",
};

export function motStatusLabel(status: string | null | undefined): string | null {
  if (!status) return null;
  return STATUS_LABELS[status as VehicleMotStatus] ?? status;
}

export type MotTone = "good" | "warning" | "neutral";

export function motStatusTone(status: string | null | undefined): MotTone {
  if (status === "valid" || status === "not_yet_due") return "good";
  if (status === "expired") return "warning";
  return "neutral";
}

export function formatLongDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

/** The one line under the status: when it expires / expired / is first due. */
export function motDateLine(summary: VehicleMotSummary): string | null {
  const date = formatLongDate(summary.due_date);
  switch (summary.status) {
    case "valid":
      return date ? `Expires ${date}` : null;
    case "expired":
      return date ? `Expired ${date}` : "No current MOT";
    case "not_yet_due":
      return date ? `First MOT due ${date}` : null;
    case "no_record":
      return "No MOT history found for this registration.";
    default:
      return null;
  }
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  const seconds = Math.round((then.getTime() - now.getTime()) / 1000);
  const format = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function formatMileage(test: VehicleMotTest): string | null {
  if (test.odometer_value !== null) {
    const unit = test.odometer_unit === "km" ? "km" : "miles";
    return `${test.odometer_value.toLocaleString("en-GB")} ${unit}`;
  }
  if (test.odometer_result === "no_odometer") return "No odometer";
  if (test.odometer_result === "unreadable") return "Odometer unreadable";
  return null;
}

export type DefectGroup = { key: string; title: string; items: VehicleMotDefect[] };

const GROUPS: { key: string; title: string; categories: VehicleMotDefectCategory[] }[] = [
  { key: "failures", title: "Reasons for failure", categories: ["dangerous", "major", "fail"] },
  { key: "fixed", title: "Fixed during the test", categories: ["prs"] },
  { key: "minor", title: "Minor defects", categories: ["minor"] },
  { key: "advisories", title: "Advisories", categories: ["advisory"] },
  { key: "other", title: "Other notes", categories: ["user_entered", "other"] },
];

/** Groups a test's defects into plain-language sections, most serious first,
 *  dropping empty groups. Dangerous items lead within their group. */
export function groupDefects(defects: VehicleMotDefect[]): DefectGroup[] {
  return GROUPS.map(({ key, title, categories }) => ({
    key,
    title,
    items: defects
      .filter((defect) => categories.includes(defect.category))
      .sort((a, b) => Number(b.dangerous) - Number(a.dangerous)),
  })).filter((group) => group.items.length > 0);
}

export function motResultLabel(result: string): string {
  if (result === "passed") return "Passed";
  if (result === "failed") return "Failed";
  return "Result unavailable";
}
