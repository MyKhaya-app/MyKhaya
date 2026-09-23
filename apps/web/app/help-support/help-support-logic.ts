// Pure display logic for the Help & Support hub (Phase 2C) — kept separate
// from the page component so it's directly unit-testable, matching this
// app's established convention (see app/home/routine-utils.ts,
// app/home/birthday-utils.ts). Never re-derives real state itself; only
// turns an already-resolved value into what a person sees.

import type { NativePlatform } from "@/components/native-runtime";
import type { ServiceState } from "@/components/platform-types";
import type { SupportTicketPriorityValue } from "@/components/support-logic";

// The public Status page's own overall_message (mykhaya.status_aggregation)
// is written for that page's fuller context ("Operational", "Scheduled
// maintenance in progress", …). The hub only has room for a single
// glanceable line, so severity-graded states collapse to one of the three
// plain-language forms product asked for; Operational and Maintenance keep
// their own honest wording rather than being forced into a "some services
// have problems" framing that wouldn't be true of a Maintenance window.
export function hubStatusMessage(overall: ServiceState, backendMessage: string): string {
  switch (overall) {
    case "operational":
      return "All systems operational";
    case "maintenance":
      return backendMessage;
    case "degraded_performance":
    case "partial_outage":
      return "Some services are experiencing problems";
    case "major_outage":
      return "Service disruption";
    default:
      return backendMessage;
  }
}

export function platformLabel(platform: NativePlatform): string {
  switch (platform) {
    case "ios":
      return "iOS app";
    case "android":
      return "Android app";
    case "web":
    default:
      return "Web browser";
  }
}

// Mirrors app/about/page.tsx's own PERMISSION_LABELS exactly — kept as a
// separate small map here (not imported from that page, which doesn't
// export it) rather than introducing a shared-label module for five
// strings; see useNotificationPermission's own status union.
const NOTIFICATION_PERMISSION_LABELS: Record<string, string> = {
  granted: "Enabled",
  denied: "Off",
  not_requested: "Not requested",
  restricted: "Restricted",
  unsupported: "Unsupported",
};

export function notificationPermissionLabel(status: string): string {
  return NOTIFICATION_PERMISSION_LABELS[status] ?? "Unknown";
}

export function connectivityLabel(online: boolean | null): string {
  if (online === null) return "Unknown";
  return online ? "Online" : "Offline";
}

// --- Report a bug (Phase 2D) --------------------------------------------------

// The form's own user-facing severity choice — deliberately not the same
// vocabulary as SupportTicketPriorityValue (backend/PCC language). Maps
// exactly 1:1 onto it; the backend remains authoritative for what a
// priority value actually means/does.
export type SeverityValue = "minor" | "problematic" | "blocking";

export const SEVERITY_TO_PRIORITY: Record<SeverityValue, SupportTicketPriorityValue> = {
  minor: "normal",
  problematic: "elevated",
  blocking: "blocking",
};

export const SEVERITY_OPTIONS: { value: SeverityValue; label: string; description: string }[] = [
  { value: "minor", label: "Minor", description: "Small issue" },
  { value: "problematic", label: "Problematic", description: "Affects usage" },
  { value: "blocking", label: "Blocking", description: "Can't use this feature" },
];

// Only the fields the Help & Support hub's own "Helpful diagnostics"
// summary already truthfully sources (Phase 2C) — app version/build,
// platform, runtime, notification permission, connectivity. Deliberately
// does NOT include os_version/push_registration_state/
// background_refresh_state/api_connectivity: none of those are genuinely
// available from existing production code on this page today (Phase 2F's
// real collector is where they belong), so sending them would mean
// fabricating values rather than reusing real ones. `network_state` is the
// one connectivity-shaped field the strict backend schema actually has;
// online/offline is what navigator.onLine can truthfully say.
export type BugReportDiagnosticsSource = {
  appVersion: string | null;
  buildNumber: string | null;
  platform: NativePlatform;
  runtime: "native" | "web";
  notificationPermission: string;
  online: boolean | null;
};

export type BugReportDiagnosticsPayload = {
  app_version?: string;
  build_number?: string;
  platform?: string;
  runtime?: string;
  notification_permission?: string;
  network_state?: string;
  client_timestamp?: string;
};

export function buildBugReportDiagnostics(
  source: BugReportDiagnosticsSource,
  now: Date = new Date(),
): BugReportDiagnosticsPayload {
  const payload: BugReportDiagnosticsPayload = {
    platform: source.platform,
    runtime: source.runtime,
    notification_permission: source.notificationPermission,
    client_timestamp: now.toISOString(),
  };
  if (source.appVersion) payload.app_version = source.appVersion;
  if (source.buildNumber) payload.build_number = source.buildNumber;
  if (source.online !== null) payload.network_state = source.online ? "online" : "offline";
  return payload;
}
