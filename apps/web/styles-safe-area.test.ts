import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression coverage for the native iOS safe-area architecture (status
// bar / home indicator overlap). jsdom has no real CSS box model, so pixel
// layout can't be asserted here — see the E2E/simulator steps in the task
// completion report for that. What CAN be proven at this level, and is
// worth proving, is the *structural* contract: one shared set of
// safe-area custom properties, referenced everywhere a top-level page
// container needs to clear the status bar/notch/home indicator, with no
// leftover JS-toggled double mechanism.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");
// .platform-login is PCC-owned CSS (see pcc-css-boundary.test.ts — the
// control-centre layout imports pcc.css, and consumer global styles.css must
// never declare a top-level `.platform-login {` rule). Its safe-area
// handling is checked against pcc.css here, not styles.css, for that reason.
const pccCss = readFileSync(
  join(process.cwd(), "app", "control-centre", "pcc.css"),
  "utf8",
);

function rootBlock(): string {
  const match = css.match(/:root\s*\{([\s\S]*?)\n\}/);
  if (!match) throw new Error(":root block not found in styles.css");
  return match[1]!;
}

describe("styles.css — shared safe-area strategy", () => {
  it("defines --safe-top/--safe-bottom/--safe-left/--safe-right once, in :root, each falling back to 0px", () => {
    const root = rootBlock();
    for (const variable of ["--safe-top", "--safe-bottom", "--safe-left", "--safe-right"]) {
      expect(root).toMatch(new RegExp(`${variable}:\\s*env\\(safe-area-inset-\\w+,\\s*0px\\)`));
    }
  });

  it("the public marketing header (.mk-header) reads --safe-top — the specific route previously left unfixed", () => {
    const headerBlock = css.match(/\.mk-header\s*\{([\s\S]*?)\n\}/)?.[1];
    expect(headerBlock).toBeDefined();
    expect(headerBlock).toContain("var(--safe-top)");
  });

  it("every top-level pre-auth/public container reads the shared vars, not a one-off literal", () => {
    for (const selector of [".standard-page", ".auth-page", ".mk-header"]) {
      const pattern = new RegExp(
        `${selector.replace(".", "\\.")}\\s*\\{[\\s\\S]*?var\\(--safe-top\\)`,
      );
      expect(css, `${selector} should reference var(--safe-top) somewhere in its rule(s)`).toMatch(
        pattern,
      );
    }
  });

  it("PCC's .platform-login (owned by pcc.css, not this file) also reads the shared vars", () => {
    // The rule that actually wins the cascade in the browser is the
    // higher-specificity `.pcc-root .platform-login` — that's the one that
    // must be safe-area-correct for real rendered behaviour.
    expect(pccCss).toMatch(/\.pcc-root \.platform-login\s*\{[\s\S]*?var\(--safe-top\)/);
    expect(pccCss).toMatch(/\.pcc-root \.platform-login\s*\{[\s\S]*?var\(--safe-bottom\)/);
  });

  it("the authenticated app shell's header/scroll-region/bottom-nav still reference the shared vars (unaffected by the public-shell fix)", () => {
    expect(css).toMatch(/\.app-header\s*\{[\s\S]*?var\(--safe-top\)/);
    expect(css).toMatch(/\.bottom-nav\s*\{[\s\S]*?var\(--safe-bottom\)/);
    expect(css).toMatch(/\.app-main\s*\{[\s\S]*?var\(--safe-bottom\)/);
  });

  it("modal/sheet bottom content still clears the home indicator", () => {
    expect(css).toMatch(/\.sheet-content\s*\{[\s\S]*?var\(--safe-bottom\)/);
  });

  it("no leftover JS-toggled double safe-area mechanism (html.native-public-shell) remains", () => {
    expect(css).not.toContain("html.native-public-shell");
  });

  it("does not reintroduce a bare env(safe-area-inset-top/bottom) literal outside the shared :root definitions", () => {
    // Every *usage* site should go through the shared variables; only the
    // :root block itself (and prose comments, which don't start a CSS
    // property) should still spell out env(safe-area-inset-*) directly.
    const usageLines = css
      .split("\n")
      .filter((line) => /env\(safe-area-inset-(top|bottom)\)/.test(line))
      .filter((line) => !/--safe-(top|bottom):/.test(line));
    expect(usageLines).toEqual([]);
  });
});
