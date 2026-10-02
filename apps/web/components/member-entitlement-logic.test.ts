import { describe, expect, it } from "vitest";
import type { CalendarUsage } from "@mykhaya/shared-types";
import {
  canAddMember,
  memberLimitMessage,
  memberOverLimitExplanation,
} from "./member-entitlement-logic";

function usage(overrides: Partial<CalendarUsage> = {}): CalendarUsage {
  return { count: 1, limit: 1, over_limit: false, ...overrides };
}

describe("canAddMember", () => {
  it("allows adding a member when unlimited", () => {
    expect(canAddMember(usage({ count: 5, limit: null }))).toBe(true);
  });

  it("allows adding a member when below the limit", () => {
    expect(canAddMember(usage({ count: 0, limit: 1 }))).toBe(true);
  });

  it("blocks adding a member at the Free limit", () => {
    expect(canAddMember(usage({ count: 1, limit: 1 }))).toBe(false);
  });

  it("blocks adding a member over the limit", () => {
    expect(canAddMember(usage({ count: 3, limit: 1 }))).toBe(false);
  });
});

describe("memberLimitMessage", () => {
  it("is null when there's still room", () => {
    expect(memberLimitMessage(usage({ count: 0, limit: 1 }))).toBeNull();
  });

  it("is null when unlimited", () => {
    expect(memberLimitMessage(usage({ count: 10, limit: null }))).toBeNull();
  });

  it("names the limit once reached, never mentioning a price", () => {
    const message = memberLimitMessage(usage({ count: 1, limit: 1 }));
    expect(message).toBe("Your Home currently supports 1 person on the Free plan.");
    expect(message).not.toMatch(/[£$€]/);
  });
});

describe("memberOverLimitExplanation", () => {
  it("is null when within the limit", () => {
    expect(memberOverLimitExplanation(usage({ count: 1, limit: 1, over_limit: false }))).toBeNull();
  });

  it("explains the over-limit state without evicting anyone or naming a price", () => {
    const message = memberOverLimitExplanation(usage({ count: 3, limit: 1, over_limit: true }));
    expect(message).toBe(
      "Your Home has 3 people. The Free plan includes 1 person. " +
        "Everyone's access is safe. Upgrade to Family to invite more household members.",
    );
    expect(message).not.toMatch(/[£$€]/);
  });
});
