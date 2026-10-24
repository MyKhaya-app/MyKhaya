import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = process.cwd();
const css = readFileSync(join(appRoot, "app", "styles.css"), "utf8");
const page = readFileSync(join(appRoot, "app", "calendar", "page.tsx"), "utf8");
const monthView = readFileSync(join(appRoot, "app", "calendar", "month-view.tsx"), "utf8");

describe("native expanded Calendar presentation", () => {
  it("uses a scoped native-wide split without changing the compact month/day-sheet path", () => {
    expect(page).toContain('className="calendar-expanded-layout"');
    expect(page).toContain('className="calendar-expanded-agenda"');
    expect(page).toMatch(/nativeWideViewport \? null : day/);
    expect(page).toContain("<BottomSheet");
    // The layout wrapper dissolves into the page grid (month left, day
    // right) so the day panel can sit level with the month toolbar.
    expect(css).toMatch(
      /\.app-shell\.native-shell-app\.native-wide-viewport \.calendar-page:has\(> \.calendar-expanded-layout\)\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1\.15fr\) minmax\(0, 1fr\);/,
    );
    expect(css).toMatch(/\.app-shell\.native-shell-app\.native-wide-viewport \.calendar-expanded-layout\s*\{\s*display:\s*contents;/);
    expect(page).toContain("selectedKey={focusedDateKey}");
    expect(page).toContain("visibleRowCap={nativeWideShort ? EXPANDED_MONTH_VISIBLE_ROW_CAP : undefined}");
    // The floating add button would sit on the rail; Add moves into the toolbar.
    expect(css).toMatch(/\.app-shell\.native-shell-app\.native-wide-viewport \.calendar-fab\s*\{\s*display:\s*none;/);
  });

  it("derives selected-day and upcoming content from existing filtered calendar state", () => {
    expect(page).toContain("events={focusedEvents}");
    expect(page).toContain("Array.from(byDay.entries())");
    expect(page).not.toContain("api.listRoutines");
    expect(page).not.toContain("api.listReminders");
  });

  it("keeps the configured week start aligned across the swipe previews", () => {
    expect(monthView).toContain("monthCells(previousDate, weekStartsOn)");
    expect(monthView).toContain("monthCells(nextDate, weekStartsOn)");
    expect(monthView).toContain('weekStartsOn === "sunday"');
  });

  it("prevents the expanded agenda from creating a nested scroll region", () => {
    const blockStart = css.indexOf(".app-shell.native-shell-app.native-wide-viewport .calendar-expanded-agenda");
    const block = css.slice(blockStart, css.indexOf("\n}", blockStart) + 2);
    expect(block).not.toMatch(/overflow\s*:/);
    expect(css).toContain("min-width: 0;");
  });
});
