// Pure display logic for the Status & Incidents feature (public /service-status
// page and Platform Control Centre's /incidents pages) — labels, badge tones
// and the overall-banner wording, kept separate from page components so it
// can be unit-tested directly (this repo has no component-rendering test
// infra for Control Centre pages; see platform-mfa-logic.test.ts for the
// established pattern). Never re-derives *which* state applies — that stays
// server-side in mykhaya.status_aggregation; this only turns an
// already-resolved ServiceState/IncidentLifecycleState into something to
// show a person.
import type { CcBadgeTone } from "./control-centre/badge";
import type {
  IncidentLifecycleState,
  PublicStatusState,
  StatusConfidence,
} from "./platform-types";

const SERVICE_STATE_LABELS: Record<PublicStatusState, string> = {
  unknown: "Unknown",
  operational: "Operational",
  degraded_performance: "Degraded Performance",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  maintenance: "Maintenance",
};

export function serviceStateLabel(state: PublicStatusState): string {
  return SERVICE_STATE_LABELS[state] ?? "Unknown";
}

export function serviceStateTone(state: PublicStatusState): CcBadgeTone {
  switch (state) {
    case "unknown":
      return "neutral";
    case "operational":
      return "success";
    case "maintenance":
      return "info";
    case "degraded_performance":
      return "warning";
    case "partial_outage":
    case "major_outage":
      return "danger";
    default:
      return "neutral";
  }
}

// Short, customer-safe qualifier shown beside a service's state on the
// public page. Only "limited" and "none" need saying: a verified state, or
// an administrator override, is presented as the state itself.
export function confidenceNote(
  state: PublicStatusState,
  confidence: StatusConfidence | undefined,
): string | null {
  if (state === "unknown") return "Not currently verified";
  if (confidence === "limited") return "Limited monitoring";
  return null;
}

const LIFECYCLE_LABELS: Record<IncidentLifecycleState, string> = {
  investigating: "Investigating",
  identified: "Identified",
  monitoring: "Monitoring",
  resolved: "Resolved",
};

export function lifecycleStateLabel(state: IncidentLifecycleState): string {
  return LIFECYCLE_LABELS[state];
}

export function lifecycleStateTone(state: IncidentLifecycleState): CcBadgeTone {
  switch (state) {
    case "investigating":
      return "danger";
    case "identified":
      return "warning";
    case "monitoring":
      return "info";
    case "resolved":
      return "success";
  }
}

// Duration between two ISO timestamps, formatted as e.g. "1h 24m" or "8m" —
// used for a resolved incident's "how long did this last" summary.
export function formatDuration(startIso: string, endIso: string): string {
  const totalMinutes = Math.max(
    0,
    Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 60_000),
  );
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}
