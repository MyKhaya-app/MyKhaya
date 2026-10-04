import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");
const timeRule = css.match(/\.home-event-date-stack \.home-event-time\s*\{([^}]*)\}/)?.[1] ?? "";

describe("styles.css — Home event time layout", () => {
  it("lets the compact time range use the gutter instead of clipping it to the date track", () => {
    expect(timeRule).toContain("max-width: none");
    expect(timeRule).toContain("overflow: visible");
    expect(timeRule).toContain("width: max-content");
    expect(timeRule).toContain("white-space: nowrap");
    expect(timeRule).not.toContain("overflow: hidden");
    expect(timeRule).not.toContain("min-width: 0");
  });
});
