import { describe, expect, it } from "vitest";
import {
  allowedNavigationHosts,
  androidShellConfiguration,
  liveFrontendOrigin,
  nativeApiBaseUrl,
  resolveAndroidShellEnvironment,
} from "./config";

describe("resolveAndroidShellEnvironment", () => {
  it("defaults to development when MYKHAYA_ANDROID_ENV is unset", () => {
    expect(resolveAndroidShellEnvironment({})).toBe("development");
  });

  it("accepts an explicit production value", () => {
    expect(resolveAndroidShellEnvironment({ MYKHAYA_ANDROID_ENV: "production" })).toBe(
      "production",
    );
  });

  it("accepts an explicit development value", () => {
    expect(resolveAndroidShellEnvironment({ MYKHAYA_ANDROID_ENV: "development" })).toBe(
      "development",
    );
  });

  it("fails clearly on an unrecognised value rather than silently defaulting", () => {
    expect(() => resolveAndroidShellEnvironment({ MYKHAYA_ANDROID_ENV: "staging" })).toThrow(
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

describe("androidShellConfiguration", () => {
  it("resolves development frontend and same-origin API route", () => {
    expect(androidShellConfiguration("development")).toEqual({
      environment: "development",
      frontend: "https://dev.mykhaya.app",
      api: "https://dev.mykhaya.app/api/v1",
    });
    expect(nativeApiBaseUrl("development")).toBe("https://dev.mykhaya.app/api/v1");
  });

  it("resolves production frontend and same-origin API route", () => {
    expect(androidShellConfiguration("production")).toEqual({
      environment: "production",
      frontend: "https://mykhaya.app",
      api: "https://mykhaya.app/api/v1",
    });
    expect(nativeApiBaseUrl("production")).toBe("https://mykhaya.app/api/v1");
  });
});

describe("allowedNavigationHosts", () => {
  it("is a short, explicit, non-wildcard list for development", () => {
    const hosts = allowedNavigationHosts("development");
    expect(hosts).toEqual(["dev.mykhaya.app"]);
    expect(hosts.some((host) => host.includes("*"))).toBe(false);
  });

  it("is a short, explicit, non-wildcard list for production", () => {
    const hosts = allowedNavigationHosts("production");
    expect(hosts).toEqual(["mykhaya.app"]);
    expect(hosts.some((host) => host.includes("*"))).toBe(false);
  });

  it("never includes an unrelated third-party host such as Stripe's checkout domain", () => {
    // Regression guard mirroring apps/ios-shell/src/config.test.ts —
    // allowNavigation must stay a deliberate allow-list, never grown
    // casually to work around a navigation failure (see ADR 0012's Stripe
    // finding, which applies to this shell identically).
    for (const environment of ["development", "production"] as const) {
      expect(allowedNavigationHosts(environment).join(",")).not.toMatch(/stripe/i);
    }
  });

  it("never includes localhost — the live deployed origin is the only target, in every environment", () => {
    for (const environment of ["development", "production"] as const) {
      expect(allowedNavigationHosts(environment).join(",")).not.toMatch(/localhost|127\.0\.0\.1/i);
    }
  });
});
