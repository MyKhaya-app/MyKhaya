import { describe, expect, it } from "vitest";
import type { BillingStatus } from "@mykhaya/shared-types";
import {
  canShowPortalAction,
  canShowUpgradeOptions,
  checkoutBannerKind,
  intervalName,
  intervalSuffix,
  periodLabel,
  resolvePlanCardKind,
} from "./billing-logic";

describe("checkoutBannerKind", () => {
  it("recognises a successful checkout redirect", () => {
    expect(checkoutBannerKind("success")).toBe("success");
  });

  it("recognises a cancelled checkout redirect", () => {
    expect(checkoutBannerKind("cancelled")).toBe("cancelled");
  });

  it("shows no banner for a missing or unrecognised param", () => {
    expect(checkoutBannerKind(null)).toBeNull();
    expect(checkoutBannerKind("something-else")).toBeNull();
  });
});

describe("periodLabel", () => {
  it("reads 'Access ends' when cancel_at_period_end is set", () => {
    expect(periodLabel(true)).toBe("Access ends");
  });

  it("reads 'Renews' otherwise", () => {
    expect(periodLabel(false)).toBe("Renews");
  });
});

describe("intervalSuffix", () => {
  it("abbreviates month and year", () => {
    expect(intervalSuffix("month")).toBe("mo");
    expect(intervalSuffix("year")).toBe("yr");
  });
});

describe("intervalName", () => {
  it("names month and year", () => {
    expect(intervalName("month")).toBe("Monthly");
    expect(intervalName("year")).toBe("Annual");
  });
});

function billingStatus(overrides: Partial<BillingStatus>): BillingStatus {
  return {
    stored_plan: "free",
    provider: "free",
    status: "active",
    effective_plan: "free",
    effective_status_reason: null,
    billing_interval: null,
    price: null,
    current_period_end: null,
    cancel_at_period_end: false,
    complimentary_expires_at: null,
    can_manage_billing: true,
    has_stripe_customer: false,
    stripe_billing_available: true,
    calendar_usage: { count: 1, limit: 1, over_limit: false },
    category_usage: { count: 1, limit: 1, over_limit: false },
    member_usage: { count: 1, limit: 1, over_limit: false },
    household_routines_enabled: false,
    shared_events_enabled: false,
    external_invites_enabled: false,
    ...overrides,
  };
}

describe("resolvePlanCardKind", () => {
  it("reads a plain Free Home with no commercial history as 'free'", () => {
    expect(resolvePlanCardKind(billingStatus({}))).toBe("free");
  });

  it("distinguishes expired complimentary access from a plain Free Home", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "complimentary",
      effective_plan: "free",
    });
    expect(resolvePlanCardKind(status)).toBe("free_expired_complimentary");
  });

  it("distinguishes an ended Stripe subscription from a plain Free Home", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "stripe",
      status: "cancelled",
      effective_plan: "free",
    });
    expect(resolvePlanCardKind(status)).toBe("free_ended_stripe");
  });

  it("reads non-expiring complimentary access", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "complimentary",
      effective_plan: "family",
      complimentary_expires_at: null,
    });
    expect(resolvePlanCardKind(status)).toBe("complimentary_no_expiry");
  });

  it("reads complimentary access with a future expiry", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "complimentary",
      effective_plan: "family",
      complimentary_expires_at: "2026-12-31T00:00:00Z",
    });
    expect(resolvePlanCardKind(status)).toBe("complimentary_with_expiry");
  });

  it("reads an active Stripe subscription", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "stripe",
      status: "active",
      effective_plan: "family",
    });
    expect(resolvePlanCardKind(status)).toBe("stripe_active");
  });

  it("reads a trialing Stripe subscription as active (not a distinct state)", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "stripe",
      status: "trialing",
      effective_plan: "family",
    });
    expect(resolvePlanCardKind(status)).toBe("stripe_active");
  });

  it("reads a past_due Stripe subscription while Family is still granted", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "stripe",
      status: "past_due",
      effective_plan: "family",
    });
    expect(resolvePlanCardKind(status)).toBe("stripe_past_due");
  });

  it("reads a Stripe subscription scheduled to cancel", () => {
    const status = billingStatus({
      stored_plan: "family",
      provider: "stripe",
      status: "cancel_at_period_end",
      effective_plan: "family",
    });
    expect(resolvePlanCardKind(status)).toBe("stripe_cancelling");
  });
});

describe("canShowPortalAction", () => {
  it("shows the Portal action only for a Stripe-backed Home with a Customer and billing_manage", () => {
    expect(
      canShowPortalAction({ provider: "stripe", has_stripe_customer: true, can_manage_billing: true }),
    ).toBe(true);
  });

  it("hides the Portal action for Complimentary access even with billing_manage", () => {
    expect(
      canShowPortalAction({
        provider: "complimentary",
        has_stripe_customer: false,
        can_manage_billing: true,
      }),
    ).toBe(false);
  });

  it("hides the Portal action without billing_manage", () => {
    expect(
      canShowPortalAction({ provider: "stripe", has_stripe_customer: true, can_manage_billing: false }),
    ).toBe(false);
  });

  it("hides the Portal action before any Stripe Customer exists", () => {
    expect(
      canShowPortalAction({ provider: "stripe", has_stripe_customer: false, can_manage_billing: true }),
    ).toBe(false);
  });
});

describe("canShowUpgradeOptions", () => {
  it("shows upgrade options for an eligible Free Home with billing_manage", () => {
    expect(
      canShowUpgradeOptions({
        effective_plan: "free",
        can_manage_billing: true,
        stripe_billing_available: true,
      }),
    ).toBe(true);
  });

  it("hides upgrade options for a Family Home", () => {
    expect(
      canShowUpgradeOptions({
        effective_plan: "family",
        can_manage_billing: true,
        stripe_billing_available: true,
      }),
    ).toBe(false);
  });

  it("hides upgrade options without billing_manage", () => {
    expect(
      canShowUpgradeOptions({
        effective_plan: "free",
        can_manage_billing: false,
        stripe_billing_available: true,
      }),
    ).toBe(false);
  });

  it("hides upgrade options when Stripe billing is not configured", () => {
    expect(
      canShowUpgradeOptions({
        effective_plan: "free",
        can_manage_billing: true,
        stripe_billing_available: false,
      }),
    ).toBe(false);
  });
});
