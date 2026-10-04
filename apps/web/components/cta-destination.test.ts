import { describe, expect, it } from "vitest";
import { resolveCtaDestination } from "./cta-destination";

describe("resolveCtaDestination", () => {
  it("sends an anonymous visitor to /register carrying their plan intent", () => {
    expect(
      resolveCtaDestination({ authenticated: false, homesCount: 0 }, { plan: "family", interval: "year" }),
    ).toBe("/register?plan=family&interval=year");
  });

  it("carries a Free selection into /register too", () => {
    expect(
      resolveCtaDestination({ authenticated: false, homesCount: 0 }, { plan: "free", interval: "month" }),
    ).toBe("/register?plan=free&interval=month");
  });

  it("sends a signed-in visitor with no Home yet to onboarding, never back to /register", () => {
    expect(
      resolveCtaDestination({ authenticated: true, homesCount: 0 }, { plan: "family", interval: "year" }),
    ).toBe("/onboarding");
  });

  it("routes an existing Home's Family CTA to the authenticated Plan & Billing page, never a fresh Checkout", () => {
    expect(
      resolveCtaDestination({ authenticated: true, homesCount: 1 }, { plan: "family", interval: "month" }),
    ).toBe("/settings/billing");
  });

  it("routes an existing Home's Free CTA straight into the app", () => {
    expect(
      resolveCtaDestination({ authenticated: true, homesCount: 1 }, { plan: "free", interval: "month" }),
    ).toBe("/home");
  });
});
