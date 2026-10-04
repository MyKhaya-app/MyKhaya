import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "app", "styles.css"), "utf8");
const settingsPage = readFileSync(join(__dirname, "components", "settings-page.tsx"), "utf8");

describe("shared page-header rhythm", () => {
  it("defines the spacing tokens once and uses them in the shared rules", () => {
    for (const token of ["--page-top-gap", "--page-back-offset", "--page-eyebrow-gap", "--page-heading-gap"]) {
      expect(css).toContain(`${token}:`);
    }
    expect(css).toMatch(/\.module-page \{\s*padding-top: var\(--page-top-gap\)/);
    expect(css).toMatch(/\.support-back-link \{[^}]*margin: var\(--page-back-offset\) 0 0;[^}]*min-height: 44px/s);
    expect(css).toMatch(/\.page-heading \{[^}]*margin-bottom: var\(--page-heading-gap\)/s);
    expect(css).toMatch(/\.page-heading p\.eyebrow \{[^}]*margin: 0;/s);
  });

  it("applies module-page to SettingsPage detail pages only (not the More root)", () => {
    expect(settingsPage).toContain('children ? " module-page" : ""');
  });
});
