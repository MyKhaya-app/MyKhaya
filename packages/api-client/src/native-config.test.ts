import { describe, expect, it } from "vitest";
import {
  NATIVE_API_ORIGINS,
  nativeApiBaseUrl,
  nativeApiBaseUrlForWebHost,
} from "./native-config";

describe("native-config", () => {
  it("names exactly the dev and production native API origins", () => {
    expect(NATIVE_API_ORIGINS.development).toBe("https://dev.mykhaya.app");
    expect(NATIVE_API_ORIGINS.production).toBe("https://mykhaya.app");
  });

  it("appends FastAPI's own /api/v1 mount prefix for each environment", () => {
    expect(nativeApiBaseUrl("development")).toBe("https://dev.mykhaya.app/api/v1");
    expect(nativeApiBaseUrl("production")).toBe("https://mykhaya.app/api/v1");
  });
});

describe("nativeApiBaseUrlForWebHost", () => {
  it("resolves the dev live frontend host to the dev native API", () => {
    expect(nativeApiBaseUrlForWebHost("dev.mykhaya.app")).toBe(
      "https://dev.mykhaya.app/api/v1",
    );
  });

  it("resolves the production live frontend host to the production native API", () => {
    expect(nativeApiBaseUrlForWebHost("mykhaya.app")).toBe("https://mykhaya.app/api/v1");
  });

  it("throws clearly for an unrecognised host rather than guessing", () => {
    expect(() => nativeApiBaseUrlForWebHost("evil.example.com")).toThrow(
      /No native API origin is configured/,
    );
  });
});
