import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Contract for the public homepage's Pricing section styles (app/styles.css). jsdom has no
// layout engine, so this asserts the structural rules the section was checked against in real
// browsers: the rules are scoped to the pricing section only (the protected consumer
// mobile/native geometry is untouched), the three plans share one aligned row on desktop and
// stack on narrower screens, nothing can force horizontal overflow, controls meet the 44px
// touch target, and every design token the block uses exists.

const read = (path: string) => readFileSync(path, "utf8").replace(/\r\n/g, "\n");
const css = read(join(process.cwd(), "app", "styles.css"));
const tokens = read(join(process.cwd(), "..", "..", "packages", "design-tokens", "src", "tokens.css"));

const start = css.indexOf("/* --- Pricing ---");
const end = css.indexOf("/* --- Final CTA ---");
const block = css.slice(start, end);

function rules(source: string): Array<{ selector: string; body: string }> {
  const found: Array<{ selector: string; body: string }> = [];
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    found.push({ selector: match[1]!.trim(), body: match[2]! });
  }
  return found;
}

function body(selector: string): string {
  const rule = rules(block).find((r) => r.selector === selector);
  if (!rule) throw new Error(`rule ${selector} not found in the Pricing block`);
  return rule.body;
}

describe("styles.css — public Pricing block", () => {
  it("is found and not empty", () => {
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    expect(rules(block).length).toBeGreaterThan(40);
  });

  it("applies only inside the pricing section: every selector is a .mk-pricing / .mk-plan / .mk-assurance selector", () => {
    for (const { selector } of rules(block)) {
      for (const part of selector.split(",").map((s) => s.trim())) {
        expect(part, `selector "${part}" must be scoped to the pricing section`).toMatch(
          /^\.mk-(pricing|plan|assurance)/,
        );
      }
    }
  });

  it("lays the three plans out as one equal, stretched row on desktop", () => {
    const grid = body(".mk-pricing-grid");
    expect(grid).toMatch(/grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
    expect(grid).toMatch(/align-items:\s*stretch/);
  });

  it("makes each card a flex column so the call to action sits at the bottom", () => {
    const card = body(".mk-plan");
    expect(card).toMatch(/display:\s*flex/);
    expect(card).toMatch(/flex-direction:\s*column/);
    expect(card).toMatch(/min-width:\s*0/);
    expect(body(".mk-plan-cta")).toMatch(/margin-top:\s*auto/);
  });

  it("marks Family with a strong green border, tinted background and a centred floating badge", () => {
    const family = body(".mk-plan-family");
    expect(family).toMatch(/border:\s*2px solid var\(--colour-forest\)/);
    expect(family).toMatch(/background:\s*var\(--mk-plan-green-tint\)/);
    const badge = body(".mk-plan-badge");
    expect(badge).toMatch(/position:\s*absolute/);
    expect(badge).toMatch(/left:\s*50%/);
    expect(badge).toMatch(/translate\(-50%,\s*-50%\)/);
  });

  it("gives each plan its own colour identity: green Free, peach Family, lavender Ultimate", () => {
    expect(body(".mk-plan-free .mk-plan-icon")).toMatch(/--mk-plan-green-tile/);
    expect(body(".mk-plan-family .mk-plan-icon")).toMatch(/--mk-plan-peach-tile/);
    expect(body(".mk-plan-ultimate .mk-plan-icon")).toMatch(/--mk-plan-lavender-tile/);
    expect(body(".mk-plan-ultimate .mk-plan-toggle .toggle-active")).toMatch(
      /--mk-plan-lavender-soft/,
    );
  });

  it("billing selector buttons meet the 44px touch target", () => {
    expect(body(".mk-plan-toggle button")).toMatch(/min-height:\s*44px/);
    expect(body(".mk-plan-cta")).toMatch(/min-height:\s*52px/);
  });

  it("stacks the plans in a single, bounded column at 1100px and below, and the reassurances 2-up then 1-up", () => {
    const media1100 = css.slice(css.indexOf("@media (max-width: 1100px) {\n  .mk-pricing-grid"));
    expect(media1100).toMatch(/\.mk-pricing-grid\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    expect(media1100).toMatch(/max-width:\s*32rem/);
    expect(media1100).toMatch(/\.mk-pricing-assurances\s*{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    const media520 = css.slice(css.indexOf("@media (max-width: 520px) {\n  .mk-pricing-assurances"));
    expect(media520).toMatch(/\.mk-pricing-assurances\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  });

  it("uses no viewport units, fixed positioning, transforms-as-scaling or fixed layout widths", () => {
    expect(block).not.toMatch(/\d(vw|vh|dvh|svh|lvh)\b/);
    expect(block).not.toMatch(/position:\s*fixed/);
    expect(block).not.toMatch(/scale\(/);
    expect(block).not.toMatch(/(?<![\w-])width:\s*\d{3,}px/);
    expect(block).not.toMatch(/!important/);
  });

  it("keeps the background washes inside the section and non-interactive (no blur filter, no overflow)", () => {
    const wash = body(".mk-pricing::before");
    expect(wash).toMatch(/pointer-events:\s*none/);
    expect(wash).toMatch(/inset:\s*0/);
    expect(wash).toMatch(/radial-gradient/);
    expect(block).not.toMatch(/filter:\s*blur/);
  });

  it("only references design tokens that exist (an undefined var() with no fallback drops the declaration)", () => {
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
});
