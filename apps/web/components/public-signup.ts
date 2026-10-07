import type { PublicSignupState } from "@mykhaya/api-client";

export function signupDestination(state: PublicSignupState | null): string {
  if (state?.signup_mode === "beta_only") return "/founding-beta";
  if (state?.signup_mode === "mixed") return "/signup-choice";
  if (state?.signup_mode === "closed") return state.waitlist_available ? "/waitlist" : "/login";
  return "/register";
}

export function signupCtaLabel(state: PublicSignupState | null): string {
  if (state?.signup_mode === "beta_only") return "Join the Beta";
  if (state?.signup_mode === "mixed") return "Choose how to join";
  if (state?.signup_mode === "closed") return state.waitlist_available ? "Join the waitlist" : "Sign in";
  return "Get started free";
}

/** Signup state as a page holds it: `undefined` = still loading (render no
 *  mode-dependent wording yet), `null` = could not be loaded (fall back to the
 *  normal registration journey), otherwise the resolved state. */
export type SignupStateValue = PublicSignupState | null | undefined;

/** Whether the "Free to start · No card required · Set up in minutes" promise
 *  is true for the current signup mode. Normal, mixed and Beta joining are all
 *  free with no card; when sign-ups are closed (waitlist or sign-in only) the
 *  promise would be wrong, so it is not shown. `null` = not known yet. */
export function signupPromiseApplies(state: SignupStateValue): boolean | null {
  if (state === undefined) return null;
  return state?.signup_mode !== "closed";
}
