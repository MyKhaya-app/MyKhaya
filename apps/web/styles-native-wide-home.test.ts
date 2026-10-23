import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");

describe("native expanded Home presentation", () => {
  it("keeps the compact native shell as the base and scopes the expanded rail to wide viewports", () => {
    expect(css).toMatch(/html\.native-shell \.bottom-nav\s*\{[\s\S]*?position:\s*static;/);
    expect(css).toMatch(/\.app-shell\.native-shell-app\.native-wide-viewport\s*\{[\s\S]*?position:\s*relative;/);
    expect(css).toMatch(/\.app-shell\.native-shell-app\.native-wide-viewport \.bottom-nav\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?right:\s*1rem;/);
    expect(css).toMatch(/\.app-shell\.native-shell-app\.native-wide-viewport \.app-header-actions\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?right:\s*1rem;/);
  });

  it("uses the existing Home cards in a two-column expanded composition", () => {
    expect(css).toMatch(
      /\.app-shell\.native-shell-app\.native-wide-viewport \.home-page\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1\.15fr\) minmax\(240px, 0\.85fr\);/,
    );
    for (const selector of [
      "home-today-card",
      "home-todo-section",
      "home-meals-card",
      "home-coming-up-card",
      "home-around-house-card",
    ]) {
      expect(css).toContain(`.app-shell.native-shell-app.native-wide-viewport .home-page > .${selector}`);
    }
  });
});
