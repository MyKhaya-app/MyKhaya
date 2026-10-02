import { describe, expect, it } from "vitest";
import { isSafeInternalPath } from "./internal-path";

describe("isSafeInternalPath", () => {
  it("accepts a plain internal path", () => {
    expect(isSafeInternalPath("/home")).toBe(true);
  });

  it("accepts an internal path with a query string", () => {
    expect(isSafeInternalPath("/calendar-shares/accept?token=abc123")).toBe(true);
  });

  it("rejects a non-string value", () => {
    expect(isSafeInternalPath(null)).toBe(false);
    expect(isSafeInternalPath(undefined)).toBe(false);
    expect(isSafeInternalPath(42)).toBe(false);
    expect(isSafeInternalPath({ toString: () => "/home" })).toBe(false);
  });

  it("rejects an empty string", () => {
    expect(isSafeInternalPath("")).toBe(false);
  });

  it("rejects a path that does not start with a slash", () => {
    expect(isSafeInternalPath("home")).toBe(false);
  });

  it("rejects a protocol-relative URL", () => {
    expect(isSafeInternalPath("//evil.example/phish")).toBe(false);
  });

  it("rejects a fully external absolute URL", () => {
    expect(isSafeInternalPath("https://evil.example/phish")).toBe(false);
    expect(isSafeInternalPath("http://evil.example")).toBe(false);
  });

  it("rejects a scheme smuggled after a leading slash", () => {
    expect(isSafeInternalPath("/javascript:alert(1)")).toBe(false);
    expect(isSafeInternalPath("/data:text/html,evil")).toBe(false);
  });
});
