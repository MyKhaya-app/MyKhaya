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
import type { IncidentLifecycleState, ServiceState } from "./platform-types";

const SERVICE_STATE_LABELS: Record<ServiceState, string> = {
  operational: "Operational",
  degraded_performance: "Degraded Performance",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  maintenance: "Maintenance",
};

export function serviceStateLabel(state: ServiceState): string {
  return SERVICE_STATE_LABELS[state];
}

export function serviceStateTone(state: ServiceState): CcBadgeTone {
  switch (state) {
    case "operational":
      return "success";
    case "maintenance":
      return "info";
    case "degraded_performance":
      return "warning";
    case "partial_outage":
    case "major_outage":
      return "danger";
  }
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
