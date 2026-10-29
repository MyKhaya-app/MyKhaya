import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Structural contract for the shared form layout and sheet containment
// (components/form-layout.tsx, docs/design/forms.md). jsdom has no layout:
// rendered geometry is measured by scripts/form-layout-harness.mjs.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");
const rule = (selector: string) => {
  // Anchored to the start of a line, so ".form-section-body" does not match
  // the end of a compound selector.
  const start = css.indexOf(`
${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
};
const DATE_TIME = 'input[type="date"], input[type="time"], input[type="datetime-local"], input[type="month"]';

describe("shared form layout CSS", () => {
  it("normalises consumer date/time controls without outranking module rules or reaching PCC", () => {
    expect(rule(`:where(${DATE_TIME}):where(:not(.pcc-root *))`)).toMatch(/-webkit-appearance:\s*none;[\s\S]*appearance:\s*none;/);
    expect(rule("input,\nselect,\ntextarea")).toContain("min-width: 0;");
    expect(css).toContain(`.consumer-date-time-control,\n.form-field > :is(${DATE_TIME}) {`);
  });

  it("contains every primitive within its parent", () => {
    for (const selector of [".form-layout", ".form-section-body", ".form-field"]) {
      expect(rule(selector)).toContain("grid-template-columns: minmax(0, 1fr);");
      expect(rule(selector)).toContain("min-width: 0;");
    }
    expect(rule(".form-section")).toContain("min-inline-size: 0;");
    expect(rule(".form-row")).toMatch(/repeat\(\s*auto-fit,\s*minmax\(\s*min\(100%,/);
    expect(rule(".form-field > :is(input, select, textarea)")).toContain("max-width: 100%;");
  });

  it("does not hide overflow globally", () => {
    expect(css).not.toMatch(/(^|\n)(html|body|html,\s*body)\s*\{[^}]*overflow-x:\s*hidden/);
    expect(rule(".form-layout")).not.toContain("overflow");
  });

  it("keeps sheets inside the side safe areas and above the keyboard", () => {
    expect(rule(".sheet-backdrop")).toContain("padding: max(1rem, var(--safe-top)) var(--safe-right) 0 var(--safe-left);");
    expect(rule(".sheet-backdrop.sheet-follows-visual-viewport")).toMatch(/height:\s*var\(--sheet-viewport-height\);[\s\S]*top:\s*var\(--sheet-viewport-top\);/);
    expect(rule(".sheet-backdrop.sheet-follows-visual-viewport > .bottom-sheet")).toContain("max-height: 100%;");
    expect(rule(".bottom-sheet.has-footer > .sheet-content")).toContain("padding-bottom: 1.5rem;");
    expect(rule(".sheet-footer")).toContain("calc(0.75rem + var(--safe-bottom))");
  });

  it("gives the sheet close button a 44px hit area", () => {
    expect(rule(".bottom-sheet-close::after")).toContain("inset: -5px;");
  });
});
