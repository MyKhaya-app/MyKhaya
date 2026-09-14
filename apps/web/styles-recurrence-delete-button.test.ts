import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression coverage for the recurring-event "Delete recurring event"
// bottom sheet, whose destructive options went invisible (white-on-white)
// after the PCC refactor (commit 304960d) repointed the shared
// `button.danger` rule at --cc-danger-strong/--cc-surface — tokens scoped
// to .platform-login/.platform-shell (the admin Control Centre) and unset
// everywhere else, including the consumer Calendar page that
// .recurrence-delete-menu belongs to. jsdom has no real CSS engine, so
// this asserts the structural contract in the stylesheet source instead.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

function ruleBlock(selectorPattern: string): string {
  const match = css.match(new RegExp(`${selectorPattern}\\s*\\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`rule for ${selectorPattern} not found in styles.css`);
  return match[1]!;
}

describe("styles.css — recurrence delete sheet destructive buttons stay visible", () => {
  it("button.danger falls back to the original hardcoded red/white when the PCC-scoped tokens are unset", () => {
    const block = ruleBlock("button\\.danger,\\s*\\n\\.danger-zone button\\.danger");
    expect(block).toMatch(/background:\s*var\(--cc-danger-strong,\s*#8c3d35\)/);
    expect(block).toMatch(/color:\s*var\(--cc-surface,\s*white\)/);
  });

  it(".recurrence-delete-menu still overrides .sheet-menu-item.danger text to white, scoped to the delete chooser only", () => {
    const block = ruleBlock("\\.recurrence-delete-menu \\.sheet-menu-item\\.danger");
    expect(block).toMatch(/color:\s*white/);
  });

  it(".recurrence-delete-menu keeps the dark red background on hover/press, not the shared sage hover", () => {
    const block = ruleBlock("\\.recurrence-delete-menu \\.sheet-menu-item\\.danger:hover");
    expect(block).toMatch(/background:\s*#8c3d35/);
  });

  it("the base .sheet-menu-item.danger rule (used by non-destructive-sheet contexts like Log out) is untouched text-only styling", () => {
    const block = ruleBlock("\\.sheet-menu-item\\.danger");
    expect(block).toMatch(/color:\s*var\(--colour-danger\)/);
    expect(block).not.toMatch(/background/);
  });
});
