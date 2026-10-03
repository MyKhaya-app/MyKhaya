import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Contract for the Settings -> Calendar settings page styles (app/styles.css). jsdom has no
// layout engine, so this asserts the structural rules the page was checked against in real
// browsers (Chromium and WebKit, 320-1440px, web and native-shell, 100% and 200% text):
// the rules are isolated to this page, the controls meet the 44px touch target and show a
// visible keyboard focus, nothing can force horizontal overflow, and every design token the
// block relies on actually exists.

const read = (path: string) => readFileSync(path, "utf8").replace(/\r\n/g, "\n");
const css = read(join(process.cwd(), "app", "styles.css"));
const tokens = read(join(process.cwd(), "..", "..", "packages", "design-tokens", "src", "tokens.css"));

const START = "/* Calendar settings uses the existing SettingsPage/card vocabulary";
const start = css.indexOf(START);
const mediaStart = css.indexOf("@media (max-width: 520px) {", start);
const block = css.slice(start, css.indexOf("\n}\n", mediaStart) + 3);

function rules(): Array<{ selector: string; body: string }> {
  const found: Array<{ selector: string; body: string }> = [];
  const withoutComments = block.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    found.push({ selector: match[1]!.trim(), body: match[2]! });
  }
  return found;
}

function body(selector: string): string {
  const rule = rules().find((r) => r.selector === selector);
  if (!rule) throw new Error(`rule ${selector} not found in the Calendar settings block`);
  return rule.body;
}

describe("styles.css — Calendar settings block", () => {
  it("is found, and is not empty", () => {
    expect(start).toBeGreaterThan(-1);
    expect(mediaStart).toBeGreaterThan(start);
    expect(rules().length).toBeGreaterThan(20);
  });

  it("applies only inside the Calendar settings page: every selector is a .calendar-settings-* selector", () => {
    for (const { selector } of rules()) {
      for (const part of selector.split(",").map((s) => s.trim())) {
        expect(part, `selector "${part}" must start with .calendar-settings-`).toMatch(
          /^\.calendar-settings-/,
        );
      }
    }
  });

  it("the custom checkbox has a tappable area of at least 44x44 CSS px", () => {
    const label = body(".calendar-settings-check");
    expect(label).toMatch(/min-height:\s*44px/);
    expect(label).toMatch(/min-width:\s*44px/);
    // ...and that area is what the (invisible) input covers.
    const input = body(".calendar-settings-check input");
    expect(input).toMatch(/height:\s*100%/);
    expect(input).toMatch(/width:\s*100%/);
  });

  it("the custom checkbox shows a visible focus ring, because its input is invisible", () => {
    expect(body(".calendar-settings-check input")).toMatch(/opacity:\s*0/);
    expect(body(".calendar-settings-check input:focus-visible + span")).toMatch(
      /outline:\s*3px solid var\(--colour-mustard\)/,
    );
  });

  it("selects can shrink and ellipsize instead of forcing overflow (long names, large text)", () => {
    expect(body(".calendar-settings-select")).toMatch(/max-width:\s*100%/);
    expect(body(".calendar-settings-select")).toMatch(/min-width:\s*0/);
    const select = body(".calendar-settings-select select");
    expect(select).toMatch(/max-width:\s*100%/);
    expect(select).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("the info banner wraps its text under the icon when there is no room beside it", () => {
    expect(body(".calendar-settings-info")).toMatch(/flex-wrap:\s*wrap/);
    expect(body(".calendar-settings-info > div")).toMatch(/min-width:\s*0/);
  });

  it("uses no viewport units, fixed positioning or fixed layout widths that could break small screens", () => {
    expect(block).not.toMatch(/\d(vw|vh|dvh|svh|lvh)\b/);
    expect(block).not.toMatch(/position:\s*fixed/);
    // A fixed pixel width of 100px or more (the 44px touch-target minimum is fine).
    expect(block).not.toMatch(/(?<![\w-])width:\s*\d{3,}px/);
  });

  it("only references design tokens that exist (an undefined var() with no fallback silently drops the whole declaration)", () => {
    const defined = new Set<string>();
    for (const source of [tokens, css]) {
      for (const match of source.matchAll(/(--[a-z0-9-]+)\s*:/g)) defined.add(match[1]!);
    }
    const missing: string[] = [];
    for (const match of block.matchAll(/var\((--[a-z0-9-]+)\s*(,[^)]*)?\)/g)) {
      const [, name, fallback] = match;
      if (!fallback && !defined.has(name!)) missing.push(name!);
    }
    expect(missing).toEqual([]);
  });

  it("row separators use a real colour (the previous --colour-border token was never defined, so no line was drawn)", () => {
    expect(body(".calendar-settings-row")).toMatch(/border-top:\s*1px solid #[0-9a-f]{6}/i);
  });
});
