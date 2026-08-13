import type { InvitationState, PlatformActor, PlatformSessionStatus } from "./platform-types";

/** Where the login flow sends the browser next, based purely on the session
 * status a login/verify response reports — the single decision every MFA
 * transition (login, TOTP/passkey/recovery verify, mandatory enrollment)
 * ultimately funnels through. Kept as a pure function so the state machine
 * itself is unit-testable without mounting the login page. */
export function resolveLoginDestination(
  status: PlatformSessionStatus,
): "home" | "setup-mfa" | "verify" {
  if (status === "full") return "home";
  if (status === "mfa_setup_required") return "setup-mfa";
  return "verify";
}

export function isSelfAdministrator(me: PlatformActor | null, viewedId: string): boolean {
  return me?.id === viewedId;
}

/** Styling for an invitation's state badge — "pending" and "accepted" read as
 * healthy (both are working as intended), "expired" and "revoked" read as
 * unavailable (both need the Owner's attention). */
export function invitationStateBadgeClass(state: InvitationState): string {
  return state === "pending" || state === "accepted" ? "state-healthy" : "state-unavailable";
}

/** Resend/revoke only make sense while an invitation could still be accepted
 * — the backend rejects both once accepted_at or revoked_at is set, so the
 * UI mirrors that here rather than showing actions that would just 409. */
export function invitationActionsAvailable(state: InvitationState): boolean {
  return state === "pending" || state === "expired";
}
