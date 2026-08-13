import { describe, expect, it } from "vitest";
import {
  eventTypeLabel,
  hasEffectiveDivergence,
  isExpired,
  isExpiringSoon,
  planBadgeClass,
  planLabel,
  providerBadgeClass,
  providerLabel,
  statusBadgeClass,
  statusLabel,
} from "./subscriptions-logic";

describe("planLabel", () => {
  it("labels free and family", () => {
    expect(planLabel("free")).toBe("Free");
    expect(planLabel("family")).toBe("Family");
  });

  it("falls back to the raw value for an unknown plan", () => {
    expect(planLabel("mystery")).toBe("mystery");
  });
});

describe("providerLabel", () => {
  it("labels every known provider", () => {
    expect(providerLabel("free")).toBe("Free");
    expect(providerLabel("complimentary")).toBe("Complimentary");
    expect(providerLabel("stripe")).toBe("Stripe");
    expect(providerLabel("apple")).toBe("Apple");
    expect(providerLabel("google")).toBe("Google");
  });
});

describe("statusLabel", () => {
  it("renders cancel_at_period_end in human wording, not the raw enum", () => {
    expect(statusLabel("cancel_at_period_end")).toBe("Cancels at period end");
  });

  it("renders every other known status", () => {
    expect(statusLabel("active")).toBe("Active");
    expect(statusLabel("trialing")).toBe("Trialing");
    expect(statusLabel("past_due")).toBe("Past due");
    expect(statusLabel("cancelled")).toBe("Cancelled");
  });
});

describe("planBadgeClass", () => {
  it("reads family as healthy and free as not-configured", () => {
    expect(planBadgeClass("family")).toBe("state-healthy");
    expect(planBadgeClass("free")).toBe("state-not-configured");
  });
});

describe("statusBadgeClass", () => {
  it("reads active/trialing as healthy", () => {
    expect(statusBadgeClass("active")).toBe("state-healthy");
    expect(statusBadgeClass("trialing")).toBe("state-healthy");
  });

  it("reads past_due/cancel_at_period_end/cancelled as unavailable", () => {
    expect(statusBadgeClass("past_due")).toBe("state-unavailable");
    expect(statusBadgeClass("cancel_at_period_end")).toBe("state-unavailable");
    expect(statusBadgeClass("cancelled")).toBe("state-unavailable");
  });
});

describe("providerBadgeClass", () => {
  it("reads complimentary as healthy, everything else as not-configured", () => {
    expect(providerBadgeClass("complimentary")).toBe("state-healthy");
    expect(providerBadgeClass("stripe")).toBe("state-not-configured");
    expect(providerBadgeClass("free")).toBe("state-not-configured");
  });
});

describe("hasEffectiveDivergence", () => {
  it("is false when stored and effective plans match", () => {
    expect(hasEffectiveDivergence("free", "free")).toBe(false);
    expect(hasEffectiveDivergence("family", "family")).toBe(false);
  });

  it("is true when complimentary access has expired (stored Family, effective Free)", () => {
    expect(hasEffectiveDivergence("family", "free")).toBe(true);
  });
});

describe("isExpiringSoon", () => {
  const now = new Date("2026-08-13T00:00:00Z");

  it("is false for no expiry", () => {
    expect(isExpiringSoon(null, now)).toBe(false);
  });

  it("is true for an expiry 3 days away", () => {
    expect(isExpiringSoon("2026-08-16T00:00:00Z", now)).toBe(true);
  });

  it("is false for an expiry 30 days away", () => {
    expect(isExpiringSoon("2026-09-12T00:00:00Z", now)).toBe(false);
  });

  it("is false once the expiry has already passed (that's 'expired', not 'expiring soon')", () => {
    expect(isExpiringSoon("2026-08-01T00:00:00Z", now)).toBe(false);
  });
});

describe("isExpired", () => {
  const now = new Date("2026-08-13T00:00:00Z");

  it("is false for no expiry", () => {
    expect(isExpired(null, now)).toBe(false);
  });

  it("is true once the expiry has passed", () => {
    expect(isExpired("2026-08-01T00:00:00Z", now)).toBe(true);
  });

  it("is false for a future expiry", () => {
    expect(isExpired("2026-09-01T00:00:00Z", now)).toBe(false);
  });
});

describe("eventTypeLabel", () => {
  it("labels known event types in human wording", () => {
    expect(eventTypeLabel("created")).toBe("Home created on Free");
    expect(eventTypeLabel("complimentary_granted")).toBe("Complimentary Family access granted");
    expect(eventTypeLabel("downgraded")).toBe("Returned to Free");
  });

  it("falls back to a de-slugged version of an unknown event type", () => {
    expect(eventTypeLabel("some_future_event")).toBe("some future event");
  });
});
