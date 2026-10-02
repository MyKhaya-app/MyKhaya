import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcBadge, toneFromStateClass } from "./badge";

describe("CcBadge", () => {
  it("renders the given tone class and children", () => {
    render(<CcBadge tone="danger">Failed</CcBadge>);
    const badge = screen.getByText("Failed");
    expect(badge.className).toContain("cc-badge-danger");
  });

  it("defaults to the neutral tone", () => {
    render(<CcBadge>Unknown</CcBadge>);
    expect(screen.getByText("Unknown").className).toContain("cc-badge-neutral");
  });
});

describe("toneFromStateClass", () => {
  it("maps healthy state classes to success", () => {
    expect(toneFromStateClass("state-healthy")).toBe("success");
  });

  it("maps warning-ish state classes to warning", () => {
    expect(toneFromStateClass("state-warning")).toBe("warning");
    expect(toneFromStateClass("state-not-configured")).toBe("warning");
    expect(toneFromStateClass("state-queued")).toBe("warning");
  });

  it("maps failure-ish state classes to danger", () => {
    expect(toneFromStateClass("state-degraded")).toBe("danger");
    expect(toneFromStateClass("state-unavailable")).toBe("danger");
    expect(toneFromStateClass("state-failed")).toBe("danger");
  });

  it("falls back to neutral for anything else", () => {
    expect(toneFromStateClass("state-not-applicable")).toBe("neutral");
  });
});
