// Persists only "was the recommendation sheet recently dismissed" — never
// a permanent flag. The real OS permission status (checked live, see
// notification-permission.ts) is what actually prevents this from
// reappearing once the user has granted or denied it at the OS level; this
// cooldown only softens the "Not now"/"Maybe later" path so declining once
// doesn't loop the sheet back immediately. Mirrors install-prompt.tsx's
// existing plain-localStorage, dotted-key, cooldown pattern exactly — this
// isn't sensitive data, so Keychain (used for the biometric offer's
// undecided/declined flag) would be unnecessary ceremony here.
const DISMISSED_KEY = "mykhaya.native.notification-prompt.dismissed-at";
const DISMISS_DAYS = 14;

export function wasRecentlyDismissed(): boolean {
  const raw = typeof window !== "undefined" ? window.localStorage.getItem(DISMISSED_KEY) : null;
  if (!raw) return false;
  const elapsedDays = (Date.now() - Number(raw)) / (1000 * 60 * 60 * 24);
  return elapsedDays < DISMISS_DAYS;
}

export function recordDismissal(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DISMISSED_KEY, String(Date.now()));
}
