import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(resolve(process.cwd(), "app/styles.css"), "utf8");
const budgetRules = (styles.match(/[^{}]*\.budget[^{}]*\{[^{}]*\}/g) ?? []).join("\n");

describe("Budget native layout contract", () => {
  it("keeps the Budget layout scoped and non-scaling", () => {
    expect(budgetRules).not.toMatch(/\bzoom\s*:/);
    expect(budgetRules).not.toMatch(/transform\s*:\s*scale/);
    expect(budgetRules).not.toMatch(/position\s*:\s*fixed/);
    expect(budgetRules).not.toMatch(/\b100vw\b/);
    expect(budgetRules).toMatch(/\.budget-page[\s\S]*min-width\s*:\s*0/);
    expect(budgetRules).toMatch(/\.budget-page[\s\S]*overflow-x\s*:\s*clip/);
  });

  it("styles the sheets' checkbox rows wherever they render, with no form sizing of its own", () => {
    // The + Add sheets on Overview and Income render outside .budget-page;
    // field sizing comes from the shared form primitives.
    expect(styles).toMatch(/(?:^|\n)\.budget-sheet-toggle \{/);
    expect(styles).not.toContain(".budget-page .budget-sheet-toggle");
    expect(styles).not.toContain(".budget-field-hint");
  });

  it("does not add global viewport or body geometry rules", () => {
    expect(budgetRules).not.toMatch(/(?:^|\})\s*(?:html|body|:root)\s*\{/);
  });
});
