const PLATFORM_CONTROL_CENTRE_HOSTS: ReadonlySet<string> = new Set([
  "admin.mykhaya.app",
  "admin.dev.mykhaya.app",
  "admin.localhost",
]);
const CONSUMER_HOSTS: ReadonlySet<string> = new Set([
  "mykhaya.app",
  "dev.mykhaya.app",
  "localhost",
  "127.0.0.1",
]);
const STATUS_HOSTS: ReadonlySet<string> = new Set([
  "status.mykhaya.app",
  "status.dev.mykhaya.app",
  "status.localhost",
]);

function normalizeHostname(hostname: string): string {
  if (typeof hostname !== "string") return "";

  const value = hostname.trim().toLowerCase();
  const match = /^([^:;\\/@]+)(?::([0-9]{1,5}))?$/.exec(value);
  if (!match) return "";

  const port = match[2];
  if (port !== undefined && (Number(port) < 1 || Number(port) > 65535)) return "";
  return match[1] ?? "";
}

export type ApplicationHostKind = "consumer" | "admin" | "status" | "unknown";

export function applicationHostKind(hostname: string): ApplicationHostKind {
  const normalized = normalizeHostname(hostname);
  if (PLATFORM_CONTROL_CENTRE_HOSTS.has(normalized)) return "admin";
  if (STATUS_HOSTS.has(normalized)) return "status";
  if (CONSUMER_HOSTS.has(normalized)) return "consumer";
  return "unknown";
}

/** Pure, shared host classification for the platform Control Centre surface. */
export function isPlatformControlCentreHost(hostname: string): boolean {
  return applicationHostKind(hostname) === "admin";
}
