import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

describe("Calendar week view in the native shell on wide viewports", () => {
  it("stacks the week in the native shell above 800px (iPad, iPhone landscape)", () => {
    expect(css).toMatch(
      /@media\s*\(min-width:\s*801px\)\s*\{\s*\.native-shell-app \.week-grid\s*\{\s*grid-template-columns:\s*1fr;/s,
    );
    expect(css).toMatch(
      /\.native-shell-app \.week-grid > article\s*\{[^}]*grid-template-columns:\s*58px minmax\(0, 1fr\)/s,
    );
  });

  it("keeps the seven-column week grid as the browser default", () => {
    expect(css).toMatch(
      /\n\.week-grid\s*\{[^}]*grid-template-columns:\s*repeat\(7, minmax\(0, 1fr\)\)/s,
    );
  });

  it("leaves the phone stacked week rules unchanged", () => {
    expect(css).toMatch(
      /@media\s*\(max-width:\s*800px\)[\s\S]*?\.week-grid\s*\{\s*grid-template-columns:\s*1fr;\s*\}\s*\.week-grid > article\s*\{[^}]*grid-template-columns:\s*58px minmax\(0, 1fr\)/s,
    );
  });
});
