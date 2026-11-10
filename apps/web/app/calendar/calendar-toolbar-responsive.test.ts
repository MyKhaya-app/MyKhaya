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
    expect(css).toMatch(
      /@media\s*\(max-width:\s*400px\)[\s\S]*?\.calendar-page \.calendar-month-label\s*\{[\s\S]*?font-size:\s*0\.84rem/s,
    );
    expect(css).toMatch(/@media\s*\(max-width:\s*380px\)[\s\S]*?min-width:\s*30px/s);
    expect(css).toContain(".calendar-page .calendar-month-row-actions .calendar-add-desktop");
  });
});

// The Everyone and view pickers: iOS zooms the page when a focused control
// is under 16px, so on phones and touch screens they (and the matching Tags
// pill) are 16px with 44px targets, and their row wraps by space instead.
const TOUCH_PILLS = /@media \(max-width: 800px\), \(hover: none\) and \(pointer: coarse\) \{\s*\.calendar-page \.calendar-selectors-row \{\s*flex-wrap: wrap;\s*\}([\s\S]*?)\n\}/;

describe("Calendar toolbar pickers", () => {
  it("are 16px with 44px targets on phones and touch screens", () => {
    const block = css.match(TOUCH_PILLS)?.[1];
    expect(block, "the phone and touch-screen pill rule").toBeDefined();
    expect(block).toMatch(/\.calendar-page \.calendar-selector select,\s*\.calendar-page \.calendar-selector-button \{[^}]*font-size: 16px;[^}]*min-height: 44px;/);
    expect(block).toMatch(/\.calendar-page \.calendar-selector \{[^}]*max-width: 100%;[^}]*min-width: 0;/);
  });

  it("wraps the picker row by space on phones and touch screens, never the month row", () => {
    expect(css).toMatch(TOUCH_PILLS);
    expect(css).toMatch(/\.calendar-selectors-row \{\s*display: flex;\s*flex-wrap: nowrap;/);
  });

  it("keeps the compact desktop pills", () => {
    expect(css).toMatch(/\n\.calendar-selector select \{[^}]*font-size: 0\.78rem;[^}]*min-height: 34px;/);
    expect(css).toMatch(/\n\.calendar-selector-button \{[^}]*font-size: 0\.78rem;[^}]*min-height: 34px;/);
  });

  it("comes after the compact rules it overrides", () => {
    expect(css.search(TOUCH_PILLS)).toBeGreaterThan(css.indexOf("\n.calendar-selector-button {"));
  });
});

describe("Calendar month row by available width", () => {
  it("compacts its controls by the row's own width, in the browser only", () => {
    expect(css).toMatch(/\.app-shell:not\(\.native-shell-app\) \.calendar-page \.calendar-month-row \{\s*container: calendar-month-row \/ inline-size;\s*\}/);
    expect(css).toMatch(/@container calendar-month-row \(max-width: 440px\) \{[\s\S]*?\.calendar-page \.calendar-month-row-actions \.icon-button \{\s*min-height: 40px;\s*min-width: 36px;/);
  });

  it("never sizes the native shell's month row by container", () => {
    expect(css).not.toMatch(/native-shell-app(?!\))[^{}]*\{[^}]*container:/);
  });
});
