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
    expect(rule(R)).toContain("--native-rail-column: 4.75rem;");
    // Header and hero rows sit beside the status column and clear the full inset.
    expect(rule(R)).toContain("--native-status-inset: max(var(--native-rail-column), var(--safe-right));");
    expect(rule(`${R} .app-header`)).toContain("var(--native-status-inset)");
    // The previous version positioned the pill at top: 100% of the shell,
    // which put notifications and profile off-screen.
    // Below the clock/Wi-Fi/battery column (~106pt on the unfolded Duo, measured).
    expect(rule(`${R} .app-header-actions`)).toMatch(/position:\s*fixed;[\s\S]*top:\s*calc\(var\(--safe-top\) \+ 8rem\)/);
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

  it("places Today, Nudges and Meals left, Coming up and Around the House right", () => {
    // Two independent stacks in page order, breaking before Coming up.
    expect(rule(`${W} .home-page`)).toContain("columns: 2;");
    expect(css).toMatch(/native-wide-viewport \.home-page > \.home-coming-up-card,[\s\S]*?\{\s*break-before: column;/);
    const order = ["home-today-card", "home-todo-section", "<MealPlansTodayCard", "home-coming-up-card", "home-around-house-card"].map((m) => home.indexOf(m));
    expect(order.every((index, i) => index > -1 && (i === 0 || index > order[i - 1]!))).toBe(true);
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

describe("notifications/profile pill overlays", () => {
  it("keeps the tray and profile sheet (rendered inside the header) when the Home header collapses", () => {
    expect(css).toContain(
      ".app-shell.native-shell-app.native-wide-viewport:has(.home-hero) .app-header > :is(.app-header-logo, .app-header-home, .app-header-botanical) {",
    );
    expect(css).not.toContain(".app-header > :not(.app-header-actions)");
  });

  it("stacks the header (and the sheets inside it) above the fixed rail", () => {
    const R = ".app-shell.native-shell-app:is(.native-wide-viewport, .native-compact-rail)";
    expect(rule(`${R} .app-header`)).toContain("z-index: 25;");
    expect(rule(`${R} .bottom-nav`)).toContain("z-index: 19;");
  });
});

describe("tall expanded right-hand column (Duo unfolded, iPad)", () => {
  const TALL = "@media (min-width: 760px) and (min-height: 521px) {";
  const W = ".app-shell.native-shell-app.native-wide-viewport";
  const block = () => {
    const start = css.indexOf(TALL);
    expect(start).toBeGreaterThan(-1);
    return css.slice(start, css.indexOf("\n}\n", start));
  };
  const shell = readFileSync(join(process.cwd(), "components", "app-shell.tsx"), "utf8");

  it("is gated on height so an iPhone in landscape keeps the short-screen rules", () => {
    // The complement of the existing short-screen block; iPhones in landscape
    // are at most ~440pt tall, so they never match.
    expect(css).toContain("@media (min-width: 760px) and (max-height: 520px) {");
    expect(css.split(TALL)).toHaveLength(2);
    // Only the native expanded class: never the compact rail, browser or PCC.
    const selectors = block().match(/^\s*\.[^{]+\{/gm) ?? [];
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) expect(selector.trim().startsWith(W)).toBe(true);
    expect(block()).not.toContain("native-compact-rail");
  });

  it("centres the rail, pill and column on the status inset", () => {
    expect(block()).toContain(
      "--native-rail-centre: max(calc(var(--native-rail-width) / 2 + 0.5rem), calc(var(--safe-right) / 2));",
    );
    expect(block()).toContain("--native-rail-inset: calc(var(--native-rail-centre) - var(--native-rail-width) / 2);");
    // The pill and the rail both use --native-rail-inset.
    expect(rule(`${R} .app-header-actions`)).toContain("right: var(--native-rail-inset);");
    expect(rule(`${R} .bottom-nav`)).toContain("right: var(--native-rail-inset);");
    // The base column stays fixed for the compact rail.
    expect(rule(R)).toContain("--native-rail-column: 4.75rem;");
  });

  it("gives every rail label room and never lets it overflow", () => {
    expect(block()).toContain("--native-rail-width: 4.25rem;");
    expect(block()).toMatch(/\.bottom-nav a span \{[^}]*text-overflow: ellipsis;/);
  });

  it("puts floating Add buttons just above the rail, centred on it", () => {
    expect(block()).toMatch(
      /\.rr-fab \{\s*bottom: calc\(var\(--safe-bottom\) \+ 0\.75rem \+ var\(--native-dock-height, [^;]+\) \+ 12px\);\s*right: calc\(var\(--native-rail-centre\) - 30px\);/,
    );
    expect(block()).toMatch(/\.rr-fab\.drv-fab \{[^}]*width: 60px;/);
    // Measured only in the native expanded layout.
    expect(shell).toContain("if (!nativeWideViewport || keyboardOpen || !shellElement) return;");
    expect(shell).toContain('shellElement.style.setProperty("--native-dock-height"');
  });

  it("moves the pill clear of the FAB and rail in short iPad windows only", () => {
    const SHORT = "@media (min-width: 760px) and (min-height: 521px) and (max-height: 639px) {";
    const start = css.indexOf(SHORT);
    expect(start).toBeGreaterThan(-1);
    const short = css.slice(start, css.indexOf("\n}\n", start));
    // Top of the column with no right inset; below the status column with one.
    expect(short).toContain(`${W} .app-header-actions {`);
    expect(short).toContain("top: calc(var(--safe-top) + 0.75rem + min(7.25rem, var(--safe-right) * 1000));");
  });
});
