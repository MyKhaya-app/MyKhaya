const PLATFORM_CONTROL_CENTRE_HOSTS: ReadonlySet<string> = new Set([
  "admin.mykhaya.app",
  "admin.dev.mykhaya.app",
  "admin.localhost",
]);

function normalizeHostname(hostname: string): string {
  if (typeof hostname !== "string") return "";

  const value = hostname.trim().toLowerCase();
  const match = /^([^:;\\/@]+)(?::([0-9]{1,5}))?$/.exec(value);
  if (!match) return "";

  const port = match[2];
  if (port !== undefined && Number(port) > 65535) return "";
  return match[1] ?? "";
}

/** Pure, shared host classification for the platform Control Centre surface. */
export function isPlatformControlCentreHost(hostname: string): boolean {
  return PLATFORM_CONTROL_CENTRE_HOSTS.has(normalizeHostname(hostname));
}
