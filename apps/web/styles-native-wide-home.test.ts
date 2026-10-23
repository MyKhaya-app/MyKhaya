import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");
const home = readFileSync(join(process.cwd(), "app", "home", "page.tsx"), "utf8");
const W = ".app-shell.native-shell-app.native-wide-viewport";
// Rules shared with the Duo outer-screen rail layout.
const R = ".app-shell.native-shell-app:is(.native-wide-viewport, .native-compact-rail)";
const rule = (selector: string) => {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
};

describe("native expanded Home presentation (iPhone Duo mockup page 3)", () => {
  it("keeps the compact native shell as the base", () => {
    expect(css).toMatch(/html\.native-shell \.bottom-nav\s*\{[\s\S]*?position:\s*static;/);
    expect(css).toMatch(/\.home-hero \.home-hero-logo,\s*\.home-hero \.home-hero-home-name\s*\{\s*display:\s*none;/);
  });

  it("puts notifications/profile and the rail in a right-hand column that clears the safe area", () => {
    expect(rule(R)).toMatch(/--native-rail-column:\s*max\(4\.75rem, calc\(var\(--safe-right\) \+ 0\.75rem\)\)/);
    // The previous version positioned the pill at top: 100% of the shell,
    // which put notifications and profile off-screen.
    expect(rule(`${R} .app-header-actions`)).toMatch(/position:\s*fixed;[\s\S]*top:\s*calc\(var\(--safe-top\) \+ 4\.25rem\)/);
    expect(rule(`${R} .bottom-nav`)).toContain("position: fixed;");
    expect(rule(`${R} .bottom-nav`)).toContain("bottom: calc(var(--safe-bottom) + 0.75rem);");
    // Content is padded on .app-main, not the scroll region (whose green
    // background used to show as a strip down the right-hand side).
    expect(rule(`${R} .app-main`)).toContain("padding-right: var(--native-rail-column)");
    expect(css).not.toMatch(/native-wide-viewport \.app-content-scroll-region \{\s*padding-right/);
  });

  it("uses a shallow one-row hero with real Home data", () => {
    expect(rule(`${W} .home-hero`)).toMatch(/grid-template-areas:\s*"logo eyebrow eyebrow strip"\s*"logo name date strip"/);
    expect(home).toContain('<span className="home-hero-home-name"> · {activeHome.name}</span>');
    expect(rule(`${W}:has(.home-hero) .app-header`)).toContain("height: 0");
  });

  it("places Today and Nudges left, Meals, Coming up and Around the House right", () => {
    expect(rule(`${W} .home-page`)).toContain("grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr)");
    expect(rule(`${W} .home-page > .home-today-card`)).toContain("grid-column: 1");
    expect(rule(`${W} .home-page > .home-todo-section`)).toContain("grid-column: 1");
    expect(rule(`${W} .home-page > .home-meals-card`)).toContain("grid-column: 2");
    expect(rule(`${W} .home-page > .home-coming-up-card`)).toContain("grid-column: 2");
    expect(rule(`${W} .home-page > .home-around-house-card`)).toContain("grid-column: 2");
  });
});

describe("iPhone Duo outer screen (mockup pages 1-2)", () => {
  const layout = readFileSync(join(process.cwd(), "components", "native-layout.ts"), "utf8");
  const shell = readFileSync(join(process.cwd(), "components", "app-shell.tsx"), "utf8");
  const C = ".app-shell.native-shell-app.native-compact-rail";

  it("only targets a screen wider than any iPhone in portrait and smaller than any iPad", () => {
    expect(layout).toContain(
      '"(min-width: 450px) and (max-width: 759px) and (min-height: 450px) and (max-height: 800px)"',
    );
    // Set only inside the native shell, and never together with the wide class.
    expect(shell).toContain("setNativeCompactRail(!wide.matches && compactRail.matches)");
    expect(shell).toMatch(/if \(!isNativeShell\(\)\) return;\s*const wide = window\.matchMedia\(NATIVE_WIDE_QUERY\)/);
  });

  it("shares the right-hand rail and pill with the expanded layout", () => {
    expect(rule(`${R} .bottom-nav`)).toContain("position: fixed;");
    expect(rule(`${R} .app-header-actions`)).toContain("position: fixed;");
    expect(rule(`${R} .app-main`)).toContain("padding-right: var(--native-rail-column)");
  });

  it("lays the hero out as on page 1 and moves the Calendar tools into the column", () => {
    expect(rule(`${C} .home-hero`)).toMatch(/grid-template-areas:\s*"eyebrow eyebrow"\s*"name name"\s*"date strip"/);
    expect(rule(`${C} .calendar-page .calendar-month-row-actions`)).toContain("position: fixed;");
    expect(rule(`${C} .calendar-page .calendar-add-desktop`)).toContain("order: -1;");
    expect(rule(`${C} .calendar-fab`)).toContain("display: none;");
  });
});
