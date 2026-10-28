import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// native/plugin/ holds the canonical app-target Swift sources;
// scripts/install-widget-sources.sh copies each one into the committed Xcode
// project (ios/App/App/), which is what Xcode actually compiles. Editing only
// one side, or adding a plugin file the installer never copies, ships
// different native code from what the repository reviews. See
// docs/engineering/ios-engineering-standards.md, "Native source ownership".

function path(relative: string): string {
  return fileURLToPath(new URL(`../${relative}`, import.meta.url));
}

// Line endings differ between a Windows working copy and a Mac/Linux one;
// only the content matters.
function readSource(relative: string): string {
  return readFileSync(path(relative), "utf8").replace(/\r\n/g, "\n");
}

const CANONICAL_SOURCES = readdirSync(path("native/plugin"))
  .filter((name) => name.endsWith(".swift"))
  .sort();

describe("native/plugin Swift sources and their Xcode copies", () => {
  it("has canonical sources to check", () => {
    expect(CANONICAL_SOURCES.length).toBeGreaterThan(0);
  });

  it.each(CANONICAL_SOURCES)("install-widget-sources.sh copies %s into ios/App/App", (name) => {
    expect(readSource("scripts/install-widget-sources.sh")).toContain(
      `cp native/plugin/${name} ios/App/App/${name}`,
    );
  });

  it.each(CANONICAL_SOURCES)(
    "ios/App/App/%s matches native/plugin (edit native/plugin, then re-run scripts/install-widget-sources.sh)",
    (name) => {
      expect(readSource(`ios/App/App/${name}`)).toBe(readSource(`native/plugin/${name}`));
    },
  );
});
