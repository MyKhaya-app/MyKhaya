import type { NativePlatform } from "./native-runtime";

export type SupportDiagnosticsPayload = {
  app_version?: string;
  build_number?: string;
  platform?: string;
  os_version?: string;
  runtime?: string;
  notification_permission?: string;
  push_registration_state?: string;
  api_connectivity?: string;
  network_state?: string;
  background_refresh_state?: string;
  client_timestamp?: string;
};

export type SupportDiagnosticsSource = {
  appVersion: string | null;
  buildNumber: string | null;
  platform: NativePlatform;
  runtime: "native" | "web";
  notificationPermission: string;
  online: boolean | null;
  osVersion?: string | null;
  pushRegistrationState?: string | null;
  apiConnectivity?: string | null;
  backgroundRefreshState?: string | null;
};

export function collectSupportDiagnostics(
  source: SupportDiagnosticsSource,
  now: Date = new Date(),
): SupportDiagnosticsPayload {
  const payload: SupportDiagnosticsPayload = {
    platform: source.platform,
    runtime: source.runtime,
    notification_permission: source.notificationPermission,
    client_timestamp: now.toISOString(),
  };
  if (source.appVersion) payload.app_version = source.appVersion;
  if (source.buildNumber) payload.build_number = source.buildNumber;
  if (source.osVersion) payload.os_version = source.osVersion;
  if (source.pushRegistrationState) payload.push_registration_state = source.pushRegistrationState;
  if (source.apiConnectivity) payload.api_connectivity = source.apiConnectivity;
  if (source.backgroundRefreshState) payload.background_refresh_state = source.backgroundRefreshState;
  if (source.online !== null) payload.network_state = source.online ? "online" : "offline";
  return payload;
}

export type DiagnosticCheckStatus = "checking" | "passed" | "good" | "enabled" | "unavailable" | "offline" | "problem" | "unknown" | "deferred";
export type DiagnosticCheck = { id: string; label: string; detail: string; status: DiagnosticCheckStatus };

export async function runSupportDiagnosticChecks(input: {
  source: SupportDiagnosticsSource;
  checkService: () => Promise<boolean>;
  checkAccount: () => Promise<boolean>;
}): Promise<DiagnosticCheck[]> {
  const [service, account] = await Promise.allSettled([input.checkService(), input.checkAccount()]);
  const serviceOk = service.status === "fulfilled" && service.value;
  const accountOk = account.status === "fulfilled" && account.value;
  const notification = input.source.notificationPermission;
  return [
    { id: "service", label: "MyKhaya service", detail: serviceOk ? "MyKhaya can be reached" : "MyKhaya is unavailable right now", status: serviceOk ? "passed" : "unavailable" },
    { id: "internet", label: "Internet connection", detail: input.source.online === true ? "Internet connection is available" : input.source.online === false ? "This device is offline" : "Connection status is unknown", status: input.source.online === true ? "good" : input.source.online === false ? "offline" : "unknown" },
    { id: "notifications", label: "Notifications", detail: notification === "granted" ? "Notifications are enabled" : notification === "denied" ? "Notifications are disabled" : notification === "unsupported" ? "Not supported on this device" : "Permission status is unknown", status: notification === "granted" ? "enabled" : notification === "unsupported" ? "unavailable" : notification === "denied" ? "problem" : "unknown" },
    { id: "account", label: "Account sync", detail: accountOk ? "Account communication is healthy" : "We could not confirm account communication", status: accountOk ? "passed" : "problem" },
    { id: "app", label: "App version", detail: input.source.appVersion ?? "Version unavailable", status: input.source.appVersion ? "passed" : "unknown" },
    { id: "platform", label: "Platform", detail: input.source.platform === "ios" ? "iOS app" : input.source.platform === "android" ? "Android app" : "Web browser", status: "passed" },
    { id: "push", label: "Push registration", detail: input.source.pushRegistrationState ?? "Unavailable", status: input.source.pushRegistrationState ? "unknown" : "unavailable" },
    { id: "background", label: "Background refresh", detail: "Not supported by this app version", status: "deferred" },
  ];
}
