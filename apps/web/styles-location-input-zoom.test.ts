import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression coverage for the "calendar appears zoomed/shifted after
// saving an event with a Location" bug. Root cause (proved by reading the
// CSS cascade, not guessed): app/calendar/page.tsx's Location <input> is
// the only real text-entry element that shares the `.icon-row-control`
// class with the Calendar/Calendar Tag <select> controls. That class sets
// its own font-size: 0.95rem (~15.2px), which — being a class selector —
// has higher specificity than the plain `input, select, textarea` rule the
// mobile breakpoint below already uses to force 16px and defeat WebKit's
// "auto-zoom the page on focusing a sub-16px text input" behaviour. So
// Location silently fell back below the zoom threshold: focusing it
// auto-zoomed the page in, and closing the event sheet afterwards left
// that zoom in effect — visually identical to what a screenshot of the
// bug shows (calendar content shifted/clipped, fixed bottom nav unaffected
// because it's pinned to the visual, not layout, viewport).
//
// jsdom has no real CSS cascade/box model, so the actual zoom-not-reset
// behaviour can't be reproduced here — this proves the *structural* fix:
// a same-or-higher-specificity mobile rule sets Location's real <input>
// back to 16px, without touching its <select> siblings (which never
// needed it and must keep their own compact styling).

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

// styles.css has several separate `@media (max-width: 800px)` blocks
// (not merged into one) — rather than trying to generically isolate "the"
// block, anchor directly on the specific rule this regression covers and
// work from its position in the whole file. Matches the rule's own opening
// line, not a prose mention of the same selector in a comment above it.
const specificRuleIndex = css.indexOf("\n  input.icon-row-control {");

describe("styles.css — Location input keeps the 16px anti-zoom font-size on mobile", () => {
  it(".icon-row-control sets a sub-16px font-size (the thing that needs overriding)", () => {
    const rule = css.match(/\.icon-row-control\s*\{([\s\S]*?)\n\}/)?.[1];
    expect(rule).toBeDefined();
    expect(rule).toMatch(/font-size:\s*0\.95rem/);
  });

  it("a mobile-breakpoint rule restores 16px specifically for input.icon-row-control", () => {
    expect(specificRuleIndex).toBeGreaterThan(-1);
    const ruleBody = css.slice(specificRuleIndex).match(/^\s*input\.icon-row-control\s*\{([\s\S]*?)\n\s*\}/)?.[1];
    expect(ruleBody).toBeDefined();
    expect(ruleBody).toMatch(/font-size:\s*16px/);
  });

  it("that rule sits inside an @media (max-width: 800px) block, not select.icon-row-control", () => {
    const nearestMediaBefore = css.lastIndexOf("@media (max-width: 800px)", specificRuleIndex);
    expect(nearestMediaBefore).toBeGreaterThan(-1);
    // No closing "}" of the media block appears between it and our rule.
    const between = css.slice(nearestMediaBefore, specificRuleIndex);
    const openBraces = (between.match(/\{/g) ?? []).length;
    const closeBraces = (between.match(/\}/g) ?? []).length;
    expect(openBraces).toBeGreaterThan(closeBraces);
  });

  it("does not widen the override to select.icon-row-control (selects never trigger the zoom bug)", () => {
    // The override is scoped to the "input." type+class selector, never a
    // "select.icon-row-control { font-size: 16px }" pairing anywhere.
    expect(css).not.toMatch(/select\.icon-row-control\s*\{[\s\S]{0,80}?font-size:\s*16px/);
  });

  it("the override rule appears after the plain input/select/textarea rule, so it isn't shadowed by source order at equal specificity", () => {
    // styles.css uses CRLF line endings (pre-existing, unrelated to this
    // change) — normalise before matching literal multi-line snippets.
    const normalized = css.replace(/\r\n/g, "\n");
    const normalizedSpecificIndex = normalized.indexOf("\n  input.icon-row-control {");
    const genericIndex = normalized.lastIndexOf("  input,\n  select,\n  textarea {\n    font-size: 16px;", normalizedSpecificIndex);
    expect(genericIndex).toBeGreaterThan(-1);
    expect(normalizedSpecificIndex).toBeGreaterThan(genericIndex);
  });
});
