import { describe, expect, it } from "vitest";
import { checkoutBannerKind, intervalSuffix, periodLabel } from "./billing-logic";

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
