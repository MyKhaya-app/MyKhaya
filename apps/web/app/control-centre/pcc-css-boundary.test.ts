import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const pccCss = readFileSync(join(process.cwd(), "app", "control-centre", "pcc.css"), "utf8");
const globalCss = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8");
const routeLayout = readFileSync(join(process.cwd(), "app", "control-centre", "layout.tsx"), "utf8");

describe("PCC stylesheet ownership", () => {
  it("loads PCC CSS from the route layout", () => {
    expect(routeLayout).toContain('import "./pcc.css"');
  });

  it("keeps PCC tokens and core component styles out of consumer global CSS", () => {
    expect(pccCss).toContain("--cc-bg: #f4f7f8");
    expect(pccCss).toContain(".cc-page-header");
    expect(pccCss).toContain(".cc-card");
    expect(pccCss).toContain(".pcc-root button");
    expect(pccCss).toContain(".pcc-root input");
    expect(pccCss).toContain(".pcc-root .notice");
    expect(globalCss).not.toContain("--cc-bg: #f4f7f8");
    expect(globalCss).not.toContain(".cc-page-header {");
    expect(globalCss).not.toContain("background: var(--cc-surface);\n  border: 1px solid var(--cc-border);\n  border-radius: var(--cc-radius-md);\n  padding: 1.1rem;");
  });

  it("owns the legacy PCC shell and page selectors in the PCC stylesheet", () => {
    for (const selector of [
      ".platform-login",
      ".platform-shell",
      ".platform-page",
      ".metric-grid",
      ".table-scroll",
      ".overview-grid",
      ".diagnostic-list",
      ".usage-metric-grid",
      ".platform-holiday-table",
    ]) {
      expect(pccCss).toContain(selector);
      expect(globalCss).not.toMatch(new RegExp(`^${selector.replaceAll(".", "\\.")}\\s*\\{`, "m"));
    }
  });

  it("keeps the PCC component foundation out of global consumer CSS", () => {
    const pccSelectors = new Set(
      [...pccCss.matchAll(/^(\.cc-[A-Za-z0-9_-]+)(?=[\s:.,{])/gm)].flatMap((match) =>
        match[1] ? [match[1]] : [],
      ),
    );

    expect(pccSelectors.size).toBeGreaterThan(20);
    for (const selector of pccSelectors) {
      expect(globalCss).not.toMatch(
        new RegExp(`^${selector.replaceAll(".", "\\.")}\\s*[{,:]`, "m"),
      );
    }
  });

  it("does not add a PCC stylesheet import to the shared root layout", () => {
    const rootLayout = readFileSync(join(process.cwd(), "app", "layout.tsx"), "utf8");
    expect(rootLayout).not.toContain("control-centre/pcc.css");
  });
});
