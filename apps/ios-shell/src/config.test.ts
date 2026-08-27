import { describe, expect, it } from "vitest";
import {
  allowedNavigationHosts,
  liveFrontendOrigin,
  resolveIosShellEnvironment,
} from "./config";

describe("resolveIosShellEnvironment", () => {
  it("defaults to production when MYKHAYA_IOS_ENV is unset", () => {
    expect(resolveIosShellEnvironment({})).toBe("production");
  });

  it("accepts an explicit production value", () => {
    expect(resolveIosShellEnvironment({ MYKHAYA_IOS_ENV: "production" })).toBe("production");
  });

  it("accepts an explicit development value", () => {
    expect(resolveIosShellEnvironment({ MYKHAYA_IOS_ENV: "development" })).toBe("development");
  });

  it("fails clearly on an unrecognised value rather than silently defaulting", () => {
    expect(() => resolveIosShellEnvironment({ MYKHAYA_IOS_ENV: "staging" })).toThrow(
      /must be "development" or "production"/,
    );
  });
});

describe("liveFrontendOrigin", () => {
  it("resolves the canonical dev live frontend", () => {
    expect(liveFrontendOrigin("development")).toBe("https://dev.mykhaya.app");
  });

  it("resolves the canonical production live frontend", () => {
    expect(liveFrontendOrigin("production")).toBe("https://mykhaya.app");
  });
});

describe("allowedNavigationHosts", () => {
  it("is a short, explicit, non-wildcard list for development", () => {
    const hosts = allowedNavigationHosts("development");
    expect(hosts).toEqual(["dev.mykhaya.app", "api.dev.mykhaya.app"]);
    expect(hosts.some((host) => host.includes("*"))).toBe(false);
  });

  it("is a short, explicit, non-wildcard list for production", () => {
    const hosts = allowedNavigationHosts("production");
    expect(hosts).toEqual(["mykhaya.app", "api.mykhaya.app"]);
    expect(hosts.some((host) => host.includes("*"))).toBe(false);
  });

  it("never includes an unrelated third-party host such as Stripe's checkout domain", () => {
    // Regression guard for the explicitly-flagged Stripe finding in ADR
    // 0012 — allowNavigation must stay a deliberate allow-list, never
    // grown casually to work around a navigation failure.
    for (const environment of ["development", "production"] as const) {
      expect(allowedNavigationHosts(environment).join(",")).not.toMatch(/stripe/i);
    }
  });
});
