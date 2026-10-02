// ---------------------------------------------------------------------------
// Local "this device has signed in as this child before" hint — UX only,
// never an authentication boundary, exactly like passkey-client.ts's
// biometric hint. The child's PIN is NEVER written here (or anywhere in
// browser storage) — the returning-child screen still requires the PIN to
// be typed and verified server-side (POST /auth/child/login) on every
// sign-in, same as the first-time form. This module only remembers enough
// to skip re-typing the Home code and username: the Home code (a
// household-shared secret already handed out on paper/verbally, not a
// per-child credential), the normalised username, and non-secret display
// info for the "Welcome back" greeting.
//
// Stored as a small array (not a single slot) so a shared family device can
// remember more than one child without any of this turning into a full
// profile-management system — see getRememberedChildAccounts/
// rememberChildAccount/forgetChildAccount below.
// ---------------------------------------------------------------------------

const CHILD_ACCOUNTS_KEY = "mk_child_accounts";
const MAX_REMEMBERED_ACCOUNTS = 5;

export interface RememberedChildAccount {
  /** Canonical form: normalise_home_code's trim().toUpperCase() (security.py). */
  homeCode: string;
  /** Canonical form: normalise_child_username's casefolded form (security.py). */
  username: string;
  userId: string;
  displayName: string;
  avatarVersion: string | null;
  lastUsedAt: string;
}

function isRememberedChildAccount(value: unknown): value is RememberedChildAccount {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.homeCode === "string" &&
    typeof record.username === "string" &&
    typeof record.userId === "string" &&
    typeof record.displayName === "string" &&
    (record.avatarVersion === null || typeof record.avatarVersion === "string") &&
    typeof record.lastUsedAt === "string"
  );
}

function sameAccount(a: { homeCode: string; username: string }, b: { homeCode: string; username: string }) {
  return a.homeCode === b.homeCode && a.username === b.username;
}

/** Most recently used first. */
export function getRememberedChildAccounts(): RememberedChildAccount[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CHILD_ACCOUNTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isRememberedChildAccount)
      .sort((left, right) => right.lastUsedAt.localeCompare(left.lastUsedAt));
  } catch {
    return [];
  }
}

/** Called only after a successful `POST /auth/child/login` — never on a
 *  failed attempt. Upserts by (homeCode, username): an existing entry is
 *  refreshed in place (new display name/avatar/lastUsedAt) rather than
 *  duplicated. Caps the remembered list at MAX_REMEMBERED_ACCOUNTS,
 *  evicting the least-recently-used entry — a shared device can remember a
 *  handful of children, not an unbounded history. */
export function rememberChildAccount(account: RememberedChildAccount): void {
  if (typeof window === "undefined") return;
  const existing = getRememberedChildAccounts().filter((row) => !sameAccount(row, account));
  const next = [account, ...existing].slice(0, MAX_REMEMBERED_ACCOUNTS);
  window.localStorage.setItem(CHILD_ACCOUNTS_KEY, JSON.stringify(next));
}

/** Removes exactly one remembered account (e.g. "Forget this account") —
 *  the device stops offering the simplified sign-in for it and falls back
 *  to the full Home code / username / PIN form next time. */
export function forgetChildAccount(homeCode: string, username: string): void {
  if (typeof window === "undefined") return;
  const remaining = getRememberedChildAccounts().filter(
    (row) => !sameAccount(row, { homeCode, username }),
  );
  if (remaining.length === 0) {
    window.localStorage.removeItem(CHILD_ACCOUNTS_KEY);
  } else {
    window.localStorage.setItem(CHILD_ACCOUNTS_KEY, JSON.stringify(remaining));
  }
}
