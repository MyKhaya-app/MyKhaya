/**
 * Shared "is this safe to navigate to internally" check — used anywhere a
 * destination path arrives from something other than a hardcoded literal:
 * a service-worker postMessage (see service-worker-register.tsx) or a
 * `?next=` query param carried through the login redirect (see
 * app/login/page.tsx and components/app-shell.tsx). Rejects anything that
 * isn't a plain same-origin path, so neither source can be used as an open
 * redirect: no protocol-relative URL ("//host/..."), no scheme
 * ("javascript:", "data:", "https://...") hiding after a leading slash.
 */
export function isSafeInternalPath(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0) return false;
  if (!value.startsWith("/") || value.startsWith("//")) return false;
  if (/^\/+[a-z][a-z0-9+.-]*:/i.test(value)) return false;
  return true;
}
