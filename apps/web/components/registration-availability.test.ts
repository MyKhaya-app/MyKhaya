import { describe, expect, it } from "vitest";
import type { PublicSignupState } from "@mykhaya/api-client";
import { registrationUnavailableReason } from "./registration-availability";

const open: PublicSignupState = {
  signup_mode: "normal",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: true,
  beta_joining_available: false,
  waitlist_available: false,
  joinable_count: null,
};

describe("registrationUnavailableReason", () => {
  it("is null while registration is open, and when the state is unknown", () => {
    expect(registrationUnavailableReason(open, false)).toBeNull();
    expect(registrationUnavailableReason(null, false)).toBeNull();
  });

  it("explains a closed registration without blocking existing users", () => {
    const reason = registrationUnavailableReason(
      { ...open, registration_open: false, normal_signup_available: false },
      false,
    );
    expect(reason).toMatch(/currently paused/);
    expect(reason).toMatch(/still sign in/);
  });

  it("explains when ordinary signup is not the open path (Beta only)", () => {
    const reason = registrationUnavailableReason(
      { ...open, signup_mode: "beta_only", normal_signup_available: false },
      false,
    );
    expect(reason).toMatch(/can’t be created from this page/);
  });

  it("asks for an invitation only when one is required and none is present", () => {
    const inviteOnly = { ...open, invitation_required: true };
    expect(registrationUnavailableReason(inviteOnly, false)).toMatch(/invitation only/);
    expect(registrationUnavailableReason(inviteOnly, true)).toBeNull();
  });

  it("allows Beta registration when Beta joining is available even though normal signup is closed", () => {
    expect(
      registrationUnavailableReason(
        { ...open, signup_mode: "beta_only", normal_signup_available: false, beta_joining_available: true },
        false,
        true,
      ),
    ).toBeNull();
  });

  it("reports Beta-specific blocked reasons", () => {
    expect(registrationUnavailableReason({ ...open, beta_joining_available: false, waitlist_available: true }, false, true)).toMatch(/waiting list/);
    expect(registrationUnavailableReason({ ...open, invitation_required: true }, false, true)).toMatch(/valid Founding Beta invitation/);
    expect(registrationUnavailableReason({ ...open, signup_mode: "closed", registration_open: false }, false, true)).toMatch(/currently closed/);
  });
});
