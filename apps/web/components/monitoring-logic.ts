// Pure display logic for Platform Control Centre's automated monitoring
// panel (Health page). Mirrors mykhaya.routers.platform_monitoring's
// response shapes. Never re-derives state: the server decides it, this only
// turns it into labels and badge tones.
import type { CcBadgeTone } from "./control-centre/badge";

export type MonitorComponentState =
  | "healthy"
  | "degraded"
  | "unavailable"
  | "unknown"
  | "not_applicable"
  | "disabled";

export type MonitorComponent = {
  key: string;
  name: string;
  category: "internal" | "external";
  provider: string | null;
  check_type: string | null;
  verifies: string | null;
  customer_impact: string | null;
  services: { key: string; name: string }[];
  state: MonitorComponentState;
  stored_state: string;
  confidence: "verified" | "limited" | null;
  enabled: boolean;
  interval_seconds: number;
  timeout_seconds: number;
  failure_threshold: number;
  recovery_threshold: number;
  public_visible: boolean;
  severity: "critical" | "warning" | "info";
  consecutive_failures: number;
  consecutive_successes: number;
  last_attempted_at: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_latency_ms: number | null;
  last_failure_category: string | null;
  last_failure_label: string | null;
  last_failure_detail: string | null;
  state_changed_at: string | null;
  stale_after_seconds: number;
  simulating_until: string | null;
  // DEV only: failed solely because of fault injection (the simulation has
  // ended but its recovery has not run yet). "Stop simulation" recovers it.
  simulated_failure_held?: boolean;
  watchdog_managed: boolean;
  // Vantage-dependent (public hostname / third-party) check: PCC-only until
  // validated on the live environment and public reporting is enabled.
  requires_live_validation?: boolean;
};

export type MonitorOverride = {
  id: string;
  service_key: string;
  service_name: string;
  mode: "suppress" | "force";
  forced_state: string | null;
  reason: string;
  starts_at: string;
  expires_at: string;
  revoked_at: string | null;
  active: boolean;
};

export type MonitorTransition = {
  id: string;
  component_key: string;
  component_name: string;
  occurred_at: string;
  from_state: string;
  to_state: string;
  failure_label: string | null;
  detail: string | null;
  incident_id: string | null;
};

export type MonitoringOverview = {
  environment: string;
  monitoring_enabled: boolean;
  fault_injection_available: boolean;
  runner: { active: boolean; last_cycle_at: string | null; detail: string | null };
  components: MonitorComponent[];
  public_preview: {
    overall: string;
    overall_message: string;
    services: { key: string; name: string; state: string; confidence: string }[];
  };
  overrides: MonitorOverride[];
  recent_transitions: MonitorTransition[];
  unacknowledged_alerts: number;
};

export type AlertDelivery = {
  attempt: string;
  recipient: string;
  channel: string;
  // queued | sent | failed | cancelled | skipped (NotificationDeliveryStatus)
  status: string;
  attempted_at: string | null;
  retry_count: number;
  failure_reason: string | null;
};

export type MonitorAlert = {
  id: string;
  created_at: string;
  kind: string;
  severity: string;
  component_key: string | null;
  component_name: string | null;
  incident_id: string | null;
  subject: string;
  summary: string;
  suppressed_reason: string | null;
  recipient_count: number;
  deliveries: AlertDelivery[];
  acknowledged_at: string | null;
  acknowledged_by: string | null;
};

export type AlertSettings = {
  enabled: boolean;
  roles: string[];
  // Only present for Owners/Administrators; other roles get the count.
  additional_recipients?: string[];
  additional_recipient_count?: number;
  can_manage?: boolean;
  cooldown_minutes: number;
  email_warning_severity: boolean;
  recipient_count: number;
  receiving_alerts: boolean;
};

const STATE_LABELS: Record<MonitorComponentState, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  unavailable: "Unavailable",
  unknown: "Unknown",
  not_applicable: "Not in use",
  disabled: "Disabled",
};

export function componentStateLabel(state: string): string {
  return STATE_LABELS[state as MonitorComponentState] ?? state;
}

export function componentStateTone(state: string): CcBadgeTone {
  switch (state) {
    case "healthy":
      return "success";
    case "degraded":
      return "warning";
    case "unavailable":
      return "danger";
    case "unknown":
      return "warning";
    default:
      return "neutral";
  }
}

const ALERT_KIND_LABELS: Record<string, string> = {
  degraded: "Degraded",
  unavailable: "Unavailable",
  recovered: "Recovered",
  monitoring_stale: "Monitoring stopped",
  monitoring_recovered: "Monitoring resumed",
};

export function alertKindLabel(kind: string): string {
  return ALERT_KIND_LABELS[kind] ?? kind;
}

export function alertKindTone(kind: string): CcBadgeTone {
  if (kind === "recovered" || kind === "monitoring_recovered") return "success";
  if (kind === "degraded") return "warning";
  return "danger";
}

const SUPPRESSION_LABELS: Record<string, string> = {
  cooldown: "Not emailed: same alert sent recently (cooldown)",
  alerting_disabled: "Not emailed: alert emails are disabled",
  info_severity: "Not emailed: informational severity",
  warning_severity_email_disabled: "Not emailed: warning-severity emails are disabled",
  no_recipients: "Not emailed: no recipients are configured",
  awaiting_validation: "Not emailed: check awaiting live validation (commissioning)",
};

export function suppressionLabel(reason: string | null): string | null {
  if (!reason) return null;
  return SUPPRESSION_LABELS[reason] ?? `Not emailed: ${reason}`;
}

// "2 sent · 1 failed" — what the delivery records say, never assumed.
export function deliverySummary(deliveries: AlertDelivery[]): string {
  if (deliveries.length === 0) return "No email deliveries";
  const counts = new Map<string, number>();
  for (const delivery of deliveries) {
    counts.set(delivery.status, (counts.get(delivery.status) ?? 0) + 1);
  }
  const order = ["sent", "queued", "failed", "cancelled", "skipped"];
  const position = (status: string) => (order.includes(status) ? order.indexOf(status) : order.length);
  return [...counts.entries()]
    .sort(([a], [b]) => position(a) - position(b))
    .map(([status, count]) => `${count} ${status}`)
    .join(" · ");
}

export function hasFailedDelivery(deliveries: AlertDelivery[]): boolean {
  return deliveries.some((delivery) => delivery.status === "failed" || delivery.status === "cancelled");
}

export function formatLatency(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${ms} ms`;
}

export function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

// Components that need attention first, then by name.
export function sortComponents(components: MonitorComponent[]): MonitorComponent[] {
  const rank: Record<string, number> = {
    unavailable: 0,
    degraded: 1,
    unknown: 2,
    healthy: 3,
    disabled: 4,
    not_applicable: 5,
  };
  return [...components].sort(
    (a, b) => (rank[a.state] ?? 9) - (rank[b.state] ?? 9) || a.name.localeCompare(b.name),
  );
}

// Shown beside a component's state so nobody mistakes a PCC-only check for one
// that feeds the public page.
export function publicReportingNote(component: MonitorComponent): string | null {
  if (component.public_visible) return null;
  if (component.requires_live_validation) return "PCC only: awaiting live validation";
  return "PCC only";
}
