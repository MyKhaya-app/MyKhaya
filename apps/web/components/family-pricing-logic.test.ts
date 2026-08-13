import { describe, expect, it } from "vitest";
import type { FamilyPricing } from "@mykhaya/shared-types";
import { isBestValueInterval, pricingOptionFor, savingLabelFor } from "./family-pricing-logic";

function pricing(overrides: Partial<FamilyPricing> = {}): FamilyPricing {
  return {
    plan: "family",
    options: [
      { interval: "month", provider: "stripe", currency: "GBP", unit_amount: 399, formatted_amount: "£3.99" },
      { interval: "year", provider: "stripe", currency: "GBP", unit_amount: 3900, formatted_amount: "£39.00" },
    ],
    annual_saving_formatted: "£8.88",
    annual_is_best_value: true,
    ...overrides,
  };
}

describe("pricingOptionFor", () => {
  it("finds the matching interval option", () => {
    expect(pricingOptionFor(pricing(), "month")?.formatted_amount).toBe("£3.99");
    expect(pricingOptionFor(pricing(), "year")?.formatted_amount).toBe("£39.00");
  });

  it("returns null when an interval is not offered", () => {
    expect(pricingOptionFor(pricing({ options: [] }), "month")).toBeNull();
  });
});

describe("isBestValueInterval", () => {
  it("is true only for annual when the backend says it's mathematically cheaper", () => {
    expect(isBestValueInterval(pricing({ annual_is_best_value: true }), "year")).toBe(true);
  });

  it("is false for annual when the backend says it is not cheaper", () => {
    expect(isBestValueInterval(pricing({ annual_is_best_value: false }), "year")).toBe(false);
  });

  it("is never true for monthly, even if annual_is_best_value is set", () => {
    expect(isBestValueInterval(pricing({ annual_is_best_value: true }), "month")).toBe(false);
  });
});

describe("savingLabelFor", () => {
  it("shows the backend-provided saving for annual", () => {
    expect(savingLabelFor(pricing(), "year")).toBe("Save £8.88 per year");
  });

  it("is null for monthly", () => {
    expect(savingLabelFor(pricing(), "month")).toBeNull();
  });

  it("is null when the backend has no saving figure to show", () => {
    expect(savingLabelFor(pricing({ annual_saving_formatted: null }), "year")).toBeNull();
  });
});
