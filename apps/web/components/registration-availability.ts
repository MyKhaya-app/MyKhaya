import type { PublicSignupState } from "@mykhaya/api-client";

/** Why the ordinary "Create your account" form cannot be used right now, or
 *  null when it can (or when the state is unknown — the server decides).
 *  Pure and display-only; precedence lives in the API
 *  (apps/api/mykhaya/platform_runtime.py SignupPolicy). */
export function registrationUnavailableReason(
  state: PublicSignupState | null,
  hasInvitation: boolean,
  betaRequested = false,
): string | null {
  if (!state) return null;
  if (!state.registration_open) {
    return state.signup_mode === "closed"
      ? "New registrations are currently closed. If you already have an account, you can still sign in."
      : "New account registration is currently paused. If you already have an account, you can still sign in.";
  }
  if (betaRequested) {
    if (state.invitation_required && !hasInvitation) {
      return "A valid Founding Beta invitation is required to register.";
    }
    if (!state.beta_joining_available && !hasInvitation) {
      return state.waitlist_available
        ? "The Founding Beta is currently using the waiting list."
        : "Founding Beta places are currently unavailable.";
    }
    return null;
  }
  if (!state.normal_signup_available) {
    return "New accounts can’t be created from this page right now. If you already have an account, you can still sign in.";
  }
  if (state.invitation_required && !hasInvitation) {
    return "Registration is currently by invitation only. Please use the link in your invitation email.";
  }
  return null;
}
