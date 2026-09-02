import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

describe("Calendar toolbar responsive layout", () => {
  it("keeps the complete toolbar on one non-wrapping row", () => {
    expect(css).toMatch(
      /\.calendar-month-row\s*\{[\s\S]*?flex-wrap:\s*nowrap[\s\S]*?\}/s,
    );
    expect(css).not.toContain("flex: 1 0 100%");
  });

  it("scales controls progressively at 430px, 400px, and 380px", () => {
    expect(css).toMatch(
      /@media\s*\(max-width:\s*430px\)[\s\S]*?\.calendar-page \.calendar-month-label\s*\{[\s\S]*?min-width:\s*7rem/s,
    );
    expect(css).toMatch(
      /@media\s*\(max-width:\s*430px\)[\s\S]*?min-width:\s*40px[\s\S]*?min-width:\s*36px/s,
    );
    expect(css).toMatch(/@media\s*\(max-width:\s*400px\)[\s\S]*?min-width:\s*32px/s);
    expect(css).toMatch(/@media\s*\(max-width:\s*380px\)[\s\S]*?min-width:\s*30px/s);
    expect(css).toContain(".calendar-page .calendar-month-row-actions .calendar-add-desktop");
  });
});
