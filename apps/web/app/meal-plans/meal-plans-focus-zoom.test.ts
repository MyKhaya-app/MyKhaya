import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// iOS zooms the page when a focused text control computes under 16px, and
// stays zoomed after the keyboard closes. These guard the rules that keep
// controls at 16px on phones and touch screens without touching desktop.
const styles = readFileSync(resolve(process.cwd(), "app/styles.css"), "utf8").replace(/\r\n/g, "\n");

/** Top-level @media blocks as [prelude, body], matched by brace depth. */
function mediaBlocks(css: string): Array<[string, string]> {
  const blocks: Array<[string, string]> = [];
  const pattern = /@media([^{]+)\{/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(css))) {
    let depth = 1;
    let index = pattern.lastIndex;
    while (depth && index < css.length) {
      if (css[index] === "{") depth += 1;
      if (css[index] === "}") depth -= 1;
      index += 1;
    }
    blocks.push([(match[1] ?? "").trim(), css.slice(pattern.lastIndex, index - 1)]);
    pattern.lastIndex = index;
  }
  return blocks;
}

const TOUCH = "(hover: none) and (pointer: coarse)";
const blocks = mediaBlocks(styles);

describe("Meals filter focus zoom", () => {
  it("keeps its small text on desktop", () => {
    expect(styles).toMatch(/\n\.meal-filter-control select \{[^}]*font-size: var\(--font-small\)/);
  });

  it("is 16px on phones and on touch screens of any width", () => {
    const rule = blocks.find(([prelude, body]) =>
      prelude.includes("(max-width: 800px)") && prelude.includes(TOUCH) && /\.meal-filter-control select \{[^}]*font-size: 16px/.test(body));
    expect(rule, "a 16px .meal-filter-control select rule for phones and touch screens").toBeDefined();
  });

  it("comes after the small-text rule, which has the same specificity", () => {
    const base = styles.indexOf(".meal-filter-control select {\n  font-size: var(--font-small)");
    const phone = styles.search(/@media \(max-width: 800px\), \(hover: none\) and \(pointer: coarse\) \{\s*\.meal-filter-control select/);
    expect(base).toBeGreaterThan(-1);
    expect(phone).toBeGreaterThan(base);
  });

  it("changes only the font size, so the filter's behaviour and box are unchanged", () => {
    const [, body] = blocks.find(([prelude, ruleBody]) => prelude.includes(TOUCH) && ruleBody.includes(".meal-filter-control select"))!;
    expect(body.replace(/\s+/g, " ").trim()).toBe(".meal-filter-control select { font-size: 16px; }");
  });
});

describe("Plan this meal focus zoom", () => {
  it("keeps Date and Meal at 16px on phones and on touch screens of any width", () => {
    const rule = blocks.find(([prelude, body]) =>
      prelude.includes("(max-width: 800px)") && prelude.includes(TOUCH) && /\.plan-meal-field-input \{[^}]*font-size: 16px/.test(body));
    expect(rule, "a 16px .plan-meal-field-input rule for phones and touch screens").toBeDefined();
  });
});

describe("Touch-screen text controls", () => {
  it("are 16px on any touch screen, not only under 800px wide", () => {
    const rule = blocks.find(([prelude]) => prelude === TOUCH);
    expect(rule, `an @media ${TOUCH} block`).toBeDefined();
    expect(rule![1]).toMatch(/:is\(input, select, textarea\):where\(:not\(\.pcc-root \*\)\) \{\s*font-size: 16px;\s*\}/);
  });

  it("never applies to a device with a fine, hovering pointer", () => {
    for (const [prelude, body] of blocks) {
      if (!/font-size: 16px/.test(body) || !prelude.includes("pointer")) continue;
      expect(prelude).toContain("(hover: none) and (pointer: coarse)");
    }
  });

  it("keeps the Platform Control Centre's own control styling", () => {
    const [, body] = blocks.find(([prelude]) => prelude === TOUCH)!;
    expect(body).toContain(":where(:not(.pcc-root *))");
  });
});
