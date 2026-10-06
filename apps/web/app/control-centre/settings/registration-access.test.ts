import { describe, expect, it } from "vitest";
import type { PublicSignupState } from "@mykhaya/api-client";
import { registrationSummary } from "./registration-access";

const settings = (values: Record<string, unknown>) =>
  Object.entries(values).map(([key, value]) => ({ key, value })) as Array<{
    key: string;
    value: string | number | boolean | string[] | null;
  }>;

const state = (overrides: Partial<PublicSignupState> = {}): PublicSignupState => ({
  signup_mode: "mixed",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: true,
  beta_joining_available: true,
  waitlist_available: true,
  joinable_count: 4,
  ...overrides,
});

describe("registration access summary", () => {
  it("reports the effective normal, Beta, waitlist, invitation and sign-in state", () => {
    expect(registrationSummary(settings({ email_verification_required: true }), state())).toEqual({
      signupMode: "Mixed",
      normalSignup: "Enabled",
      betaSignup: "Enabled",
      waitlist: "Enabled",
      invitation: "Not required",
      emailVerification: "Required",
      signIn: "Available",
    });
  });

  it("reflects the master switch and invitation-only precedence through resolved state", () => {
    expect(registrationSummary(settings({ email_verification_required: false }), state({
      signup_mode: "closed",
      registration_open: false,
      normal_signup_available: false,
      beta_joining_available: false,
      waitlist_available: true,
      invitation_required: true,
    }))).toMatchObject({
      signupMode: "Closed",
      normalSignup: "Disabled",
      betaSignup: "Disabled",
      waitlist: "Enabled",
      invitation: "Required",
      emailVerification: "Optional",
    });
  });

  it("updates the displayed Signup Mode when the resolved mode changes", () => {
    expect(registrationSummary(settings({}), state({ signup_mode: "beta_only" })).signupMode).toBe("Founding Beta only");
    expect(registrationSummary(settings({}), state({ signup_mode: "normal" })).signupMode).toBe("Normal");
  });
});
