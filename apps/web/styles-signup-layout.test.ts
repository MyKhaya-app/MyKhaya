import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Normalised so the checks hold on Windows checkouts with CRLF line endings.
const read = (...parts: string[]) => readFileSync(join(__dirname, ...parts), "utf8").replace(/\r\n/g, "\n");
const signup = read("app", "signup-screen.css");
const register = read("app", "register", "register.css");
const signin = read("app", "login", "signin.css");
const tokens = read("app", "auth-tokens.css");
const registerPage = read("app", "register", "page.tsx");
const consent = read("components", "signup-legal-consent.tsx");

const AUTH_CSS = { "signup-screen.css": signup, "register.css": register, "signin.css": signin, "auth-tokens.css": tokens };

/** Removes /* ... *\/ comments so prose about a rule never satisfies a check. */
const code = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = code(css).match(new RegExp(`(?:^|\\n|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`));
  expect(match, `rule for ${selector}`).not.toBeNull();
  return match![1]!;
}

describe("sign-up screens: defects fixed at the source", () => {
  it("draws the password toggle inside its field, not as a global button", () => {
    expect(rule(signup, ".signup-screen .signup-password")).toMatch(/position: relative;/);
    const toggle = rule(signup, ".signup-screen .signup-password-toggle");
    expect(toggle).toMatch(/position: absolute;/);
    expect(toggle).toMatch(/right: 4px;/);
    expect(toggle).toMatch(/background: transparent;/);
    expect(toggle).toMatch(/width: 44px;/);
    expect(toggle).toMatch(/height: 44px;/);
    expect(rule(signup, ".signup-screen .signup-password input")).toMatch(/padding-right: 52px;/);
    expect(registerPage).toContain('className="signup-password-toggle"');
    expect(registerPage).toContain('aria-describedby="register-password-hint"');
  });

  it("styles the legal checkbox rows with the class the markup actually uses", () => {
    expect(consent).toContain('className="signup-check-row"');
    const row = rule(signup, ".signup-screen .signup-check-row");
    expect(row).toMatch(/display: flex;/);
    expect(row).toMatch(/min-height: 44px;/);
    // Sized explicitly: the global input rule would otherwise make it full width.
    expect(rule(signup, ".signup-screen .signup-check-row input")).toMatch(/width: 22px;/);
    expect(registerPage).not.toContain('"check-row"');
  });

  it("never wraps the auth styles in @scope (unsupported before iOS 17.4)", () => {
    for (const [name, css] of Object.entries(AUTH_CSS)) {
      expect(code(css), name).not.toMatch(/@scope/);
    }
  });

  it("uses @scope nowhere in app/ or components/ (the iOS app supports iOS 15.0)", () => {
    // Browsers without @scope drop the whole block, so a scoped rule silently
    // never applies on older iPhones. Covers stylesheets and CSS written
    // inside TS/TSX (style tags, template strings); comments are ignored.
    const offenders: string[] = [];
    for (const dir of ["app", "components"]) {
      const files = readdirSync(join(__dirname, dir), { recursive: true, encoding: "utf8" });
      for (const file of files) {
        if (!/\.(css|scss|ts|tsx)$/.test(file) || /\.test\.tsx?$/.test(file)) continue;
        const source = read(dir, file)
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .replace(/^\s*\/\/.*$/gm, "");
        if (/@scope\b/.test(source)) offenders.push(`${dir}/${file.replaceAll("\\", "/")}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("centres the wide form column without clipping a tall one", () => {
    const wide = code(signup).slice(code(signup).indexOf("@media (min-width: 801px)"));
    expect(wide).toMatch(/\.signup-screen \.signup-column \{[^}]*margin-block: auto;[^}]*max-width: 440px;/s);
    expect(wide).toMatch(/main\.signup-screen \{[^}]*grid-template-columns: minmax\(380px, 520px\) minmax\(0, 1fr\);/s);
  });
});

describe("sign-up screens: CSS rules", () => {
  it("uses no !important in any auth stylesheet", () => {
    for (const [name, css] of Object.entries(AUTH_CSS)) {
      expect(code(css), name).not.toContain("!important");
    }
  });

  it("is mobile first: wide layouts are min-width enhancements only", () => {
    for (const css of [signup, register]) {
      expect(code(css)).not.toMatch(/@media \(max-width/);
      expect(code(css)).toContain("@media (min-width: 801px)");
    }
  });

  it("has one shared auth token set, with no leftover --si-* or --rg-* tokens", () => {
    for (const [name, css] of Object.entries(AUTH_CSS)) {
      expect(code(css), name).not.toMatch(/--si-|--rg-/);
    }
    expect(tokens).toMatch(/:where\(\.signin-page, \.register-page, \.signup-screen\) \{/);
  });

  it("keeps fields at 16px text (no iOS focus zoom) and at least 48px tall", () => {
    const field = rule(signup, ".signup-screen .signup-field input");
    expect(field).toMatch(/font: 400 16px/);
    expect(field).toMatch(/height: 52px;/);
  });

  it("does not move or zoom anything for layout", () => {
    // "transform" as a property, not text-transform; "none" is the reset.
    expect(code(signup)).not.toMatch(/(?<![-\w])(zoom|transform):(?! none)/);
    expect(code(signup)).toMatch(/@media \(prefers-reduced-motion: no-preference\)/);
  });
});

function luminance(hex: string): number {
  const channels = hex.replace("#", "").match(/../g)!.map((pair) => parseInt(pair, 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}
const token = (name: string) => tokens.match(new RegExp(`--auth-${name}: (#[0-9a-f]{6})`))![1]!;

describe("sign-up screens: contrast (WCAG AA, 4.5:1 for text)", () => {
  it("muted copy is readable on the cream page and on surfaces", () => {
    expect(contrast(token("muted"), token("paper"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("muted"), "#fffefb")).toBeGreaterThanOrEqual(4.5);
  });

  it("Beta tint text and the primary button meet AA", () => {
    expect(contrast(token("beta-ink"), token("beta-bg"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("on-forest"), token("forest"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("ink"), token("paper"))).toBeGreaterThanOrEqual(4.5);
  });
});
