import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readMainViewController(): string {
  return readFileSync(
    fileURLToPath(new URL("../ios/App/App/MainViewController.swift", import.meta.url)),
    "utf8",
  );
}

describe("iOS native cold-start bootstrap", () => {
  it("normalizes a plain restored /login before React mounts", () => {
    const source = readMainViewController();
    expect(source).toContain("WKUserScript");
    expect(source).toContain("injectionTime: .atDocumentStart");
    expect(source).toContain('path === "/login" && !hasQuery && !deepLink');
    expect(source).toContain('window.location.replace("/")');
  });

  it("keeps intentional native deep links out of the startup normalizer", () => {
    const source = readMainViewController();
    expect(source).toContain('mykhaya.native.deep-link-start');
    expect(source).toContain('launch_source: deepLink ? "deep_link" : "cold_start"');
  });
});
