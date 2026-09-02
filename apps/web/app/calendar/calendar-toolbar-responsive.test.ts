import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

describe("Calendar toolbar responsive layout", () => {
  it("wraps the action group below the month controls on narrow phones", () => {
    expect(css).toMatch(
      /@media\s*\(max-width:\s*480px\)[\s\S]*?\.calendar-page \.calendar-month-row\s*\{[\s\S]*?flex-wrap:\s*wrap[\s\S]*?\}[\s\S]*?\.calendar-page \.calendar-month-row-actions\s*\{[\s\S]*?flex:\s*1 0 100%[\s\S]*?min-width:\s*0/s,
    );
  });

  it("reduces action controls to 40px without hiding any toolbar controls", () => {
    expect(css).toMatch(
      /@media\s*\(max-width:\s*380px\)[\s\S]*?\.calendar-page \.calendar-month-row-actions \.icon-button\s*\{[\s\S]*?min-height:\s*40px[\s\S]*?min-width:\s*40px/s,
    );
    expect(css).toContain(".calendar-page .calendar-month-row-actions .calendar-add-desktop");
  });
});
