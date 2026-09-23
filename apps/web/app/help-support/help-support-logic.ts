// Pure display logic for the Help & Support hub (Phase 2C) — kept separate
// from the page component so it's directly unit-testable, matching this
// app's established convention (see app/home/routine-utils.ts,
// app/home/birthday-utils.ts). Never re-derives real state itself; only
// turns an already-resolved value into what a person sees.

import type { NativePlatform } from "@/components/native-runtime";
import type { ServiceState } from "@/components/platform-types";

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
