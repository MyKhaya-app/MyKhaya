import type { PublicSignupState } from "@mykhaya/api-client";

export function signupDestination(state: PublicSignupState | null): string {
  if (state?.signup_mode === "beta_only") return "/founding-beta";
  if (state?.signup_mode === "mixed") return "/signup-choice";
  return "/register";
}

export function signupCtaLabel(state: PublicSignupState | null): string {
  if (state?.signup_mode === "beta_only") return "Join the Beta";
  if (state?.signup_mode === "mixed") return "Choose how to join";
  return "Get started free";
}
