import { describe, expect, it } from "vitest";
import {
  invitationActionsAvailable,
  invitationStateBadgeClass,
  isSelfAdministrator,
  resolveLoginDestination,
} from "./platform-mfa-logic";
import type { InvitationState, PlatformActor } from "./platform-types";

describe("resolveLoginDestination", () => {
  it("sends a fully authenticated session home", () => {
    expect(resolveLoginDestination("full")).toBe("home");
  });

  it("sends an administrator with no MFA enrolled, under a policy that requires it, to setup", () => {
    expect(resolveLoginDestination("mfa_setup_required")).toBe("setup-mfa");
  });

  it("sends an administrator who already has MFA enrolled to the verify step", () => {
    expect(resolveLoginDestination("pending_mfa")).toBe("verify");
  });
});

describe("isSelfAdministrator", () => {
  const actor: PlatformActor = {
    id: "admin-1",
    email: "owner@example.com",
    display_name: "Owner",
    role: "platform_owner",
    mfa_enrolled: true,
    session_status: "full",
  };

  it("is true when viewing your own administrator page", () => {
    expect(isSelfAdministrator(actor, "admin-1")).toBe(true);
  });

  it("is false when viewing another administrator", () => {
    expect(isSelfAdministrator(actor, "admin-2")).toBe(false);
  });

  it("is false before the current administrator has loaded", () => {
    expect(isSelfAdministrator(null, "admin-1")).toBe(false);
  });
});

describe("invitationStateBadgeClass", () => {
  it("reads pending as healthy", () => {
    expect(invitationStateBadgeClass("pending")).toBe("state-healthy");
  });

  it("reads accepted as healthy", () => {
    expect(invitationStateBadgeClass("accepted")).toBe("state-healthy");
  });

  it("reads expired as unavailable", () => {
    expect(invitationStateBadgeClass("expired")).toBe("state-unavailable");
  });

  it("reads revoked as unavailable", () => {
    expect(invitationStateBadgeClass("revoked")).toBe("state-unavailable");
  });
});

describe("invitationActionsAvailable", () => {
  const cases: [InvitationState, boolean][] = [
    ["pending", true],
    ["expired", true],
    ["accepted", false],
    ["revoked", false],
  ];

  it.each(cases)("for state %s returns %s", (state, expected) => {
    expect(invitationActionsAvailable(state)).toBe(expected);
  });
});
