import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// A visually hidden control (such as the meal photo picker's file input)
// must not keep the global control min-height as an invisible 47px box,
// which a short sheet then has to scroll to reveal.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8").replace(/\r\n/g, "\n");

describe("styles.css — .visually-hidden", () => {
  it("collapses to 1px whatever the control's own minimum size", () => {
    const rule = css.match(/\n\.visually-hidden \{[^}]*\}/)?.[0] ?? "";
    expect(rule).toContain("height: 1px;");
    expect(rule).toContain("width: 1px;");
    expect(rule).toContain("min-height: 0;");
    expect(rule).toContain("min-width: 0;");
  });
});
