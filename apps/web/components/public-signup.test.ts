import { describe, expect, it } from "vitest";
import type { PublicSignupState } from "@mykhaya/api-client";
import { signupCtaLabel, signupDestination } from "./public-signup";

const state = (mode: PublicSignupState["signup_mode"]): PublicSignupState => ({
  signup_mode: mode,
  registration_open: mode !== "closed",
  invitation_required: false,
  normal_signup_available: mode === "normal" || mode === "mixed",
  beta_joining_available: mode === "beta_only" || mode === "mixed",
  waitlist_available: false,
  joinable_count: null,
});

describe("public signup routing", () => {
  it.each([
    ["normal", "/register", "Get started free"],
    ["beta_only", "/founding-beta", "Join the Beta"],
    ["mixed", "/signup-choice", "Choose how to join"],
  ] as const)("routes %s through its authoritative journey", (mode, destination, label) => {
    expect(signupDestination(state(mode))).toBe(destination);
    expect(signupCtaLabel(state(mode))).toBe(label);
  });

  it("keeps the sign-in path available when registration is closed", () => {
    expect(signupDestination(state("closed"))).toBe("/register");
  });
});
