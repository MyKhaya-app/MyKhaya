import { describe, expect, it } from "vitest";
import { PRIMARY_NAV_DESTINATIONS, primaryNavDestinationsFor } from "./primary-nav-destinations";

describe("PRIMARY_NAV_DESTINATIONS", () => {
  it("names exactly the current four primary destinations", () => {
    expect(PRIMARY_NAV_DESTINATIONS.map((d) => d.id)).toEqual([
      "home",
      "calendar",
      "family",
      "more",
    ]);
  });
});

describe("primaryNavDestinationsFor", () => {
  it("includes the adult-only Family destination for an adult", () => {
    const ids = primaryNavDestinationsFor("adult").map((d) => d.id);
    expect(ids).toContain("family");
  });

  it("excludes the adult-only Family destination for a managed child", () => {
    const ids = primaryNavDestinationsFor("managed_child").map((d) => d.id);
    expect(ids).not.toContain("family");
  });

  it("includes all destinations when no principal type is given", () => {
    expect(primaryNavDestinationsFor().map((d) => d.id)).toHaveLength(4);
  });
});
