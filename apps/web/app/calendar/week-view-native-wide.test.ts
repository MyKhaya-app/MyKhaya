import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

describe("Calendar week view in the native shell on wide viewports", () => {
  it("stacks the week in the native shell above 800px (iPad, iPhone landscape)", () => {
    expect(css).toMatch(
      /@media\s*\(min-width:\s*801px\)\s*\{\s*\.native-shell-app \.week-grid\s*\{\s*grid-template-columns:\s*1fr;/s,
    );
    expect(css).toMatch(
      /\.native-shell-app \.week-grid > article\s*\{[^}]*grid-template-columns:\s*58px minmax\(0, 1fr\)/s,
    );
  });

  it("keeps the seven-column week grid as the browser default", () => {
    expect(css).toMatch(
      /\n\.week-grid\s*\{[^}]*grid-template-columns:\s*repeat\(7, minmax\(0, 1fr\)\)/s,
    );
  });

  it("leaves the phone stacked week rules unchanged", () => {
    expect(css).toMatch(
      /@media\s*\(max-width:\s*800px\)[\s\S]*?\.week-grid\s*\{\s*grid-template-columns:\s*1fr;\s*\}\s*\.week-grid > article\s*\{[^}]*grid-template-columns:\s*58px minmax\(0, 1fr\)/s,
    );
  });

  it("keeps a day's highlight and events in the content column", () => {
    expect(css).toMatch(
      /@media\s*\(min-width:\s*801px\)\s*\{[\s\S]*?\.native-shell-app \.week-grid > article > :not\(\.week-day-heading\)\s*\{\s*grid-column:\s*2;/s,
    );
    expect(css).toMatch(
      /@media\s*\(max-width:\s*800px\)[\s\S]*?\.week-grid > article > :not\(\.week-day-heading\)\s*\{\s*grid-column:\s*2;/s,
    );
  });
});

describe("Calendar month view in the native shell on tablets", () => {
  it("widens the Calendar page and fills the height only on tablet-sized viewports", () => {
    const block = css.match(
      /@media\s*\(min-width:\s*801px\) and \(min-height:\s*700px\)\s*\{([\s\S]*?)\n\}/,
    );
    expect(block).not.toBeNull();
    const body = block![1];
    expect(body).toMatch(/\.native-shell-app \.standard-page\.calendar-page\s*\{\s*max-width:\s*1320px;/);
    expect(body).toMatch(/\.native-shell-app \.calendar-week\s*\{[^}]*min-height:\s*max\(112px, calc\(\(100dvh - 330px\) \/ var\(--calendar-week-count\)\)\)/);
    const selectors = [...body.matchAll(/^\s*([^{}\n/][^{}\n]*?)\s*\{/gm)].map((m) => m[1]);
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) expect(selector.startsWith(".native-shell-app ")).toBe(true);
  });
});

