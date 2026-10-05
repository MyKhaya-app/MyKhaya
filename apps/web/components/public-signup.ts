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
