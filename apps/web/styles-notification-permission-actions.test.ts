import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression coverage for the NotificationPermissionPrompt footer layout
// (Enable notifications / Not now, Open phone settings / Maybe later): a
// single flex row, equal-height/aligned buttons, a consistent gap, an
// asymmetric ~70/30 width split favouring the primary action, and no label
// wrapping. jsdom has no real CSS box model, so pixel layout can't be
// asserted here — see the task's Playwright screenshot verification at
// 393px/320px for that; this proves the structural CSS contract instead.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

function ruleBlock(selectorPattern: string): string {
  const match = css.match(new RegExp(`${selectorPattern}\\s*\\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`rule for ${selectorPattern} not found in styles.css`);
  return match[1]!;
}

describe("styles.css — .notification-permission-actions footer row", () => {
  it("lays the two actions out as a single flex row with a consistent gap", () => {
    const block = ruleBlock("\\.notification-permission-actions");
    expect(block).toMatch(/display:\s*flex/);
    expect(block).toMatch(/gap:\s*\S+/);
    expect(block).toMatch(/align-items:\s*stretch/);
  });

  it("gives the primary action roughly 70% and the secondary roughly 30% of the row", () => {
    const primaryBlock = ruleBlock("\\.notification-permission-actions > button:first-child");
    const secondaryBlock = ruleBlock("\\.notification-permission-actions > button\\.secondary");
    const primaryFlex = primaryBlock.match(/flex:\s*(\d+)/)?.[1];
    const secondaryFlex = secondaryBlock.match(/flex:\s*(\d+)/)?.[1];
    expect(primaryFlex).toBeDefined();
    expect(secondaryFlex).toBeDefined();
    const primary = Number(primaryFlex);
    const secondary = Number(secondaryFlex);
    const primaryShare = primary / (primary + secondary);
    expect(primaryShare).toBeGreaterThanOrEqual(0.65);
    expect(primaryShare).toBeLessThanOrEqual(0.7);
  });

  it("prevents either label from wrapping", () => {
    const block = ruleBlock("\\.notification-permission-actions > button");
    expect(block).toMatch(/white-space:\s*nowrap/);
  });

  it("does not override the shared button colour, radius or padding — only the row's width distribution", () => {
    for (const selector of [
      "\\.notification-permission-actions",
      "\\.notification-permission-actions > button",
      "\\.notification-permission-actions > button:first-child",
      "\\.notification-permission-actions > button\\.secondary",
    ]) {
      const block = ruleBlock(selector);
      expect(block).not.toMatch(/background/);
      expect(block).not.toMatch(/border-radius/);
      expect(block).not.toMatch(/^\s*padding/m);
      expect(block).not.toMatch(/color:/);
    }
  });
});
