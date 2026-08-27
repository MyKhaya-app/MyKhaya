import { describe, expect, it } from "vitest";
import { NATIVE_API_ORIGINS, nativeApiBaseUrl } from "./native-config";

describe("native-config", () => {
  it("names exactly the dev and production native API origins", () => {
    expect(NATIVE_API_ORIGINS.development).toBe("https://api.dev.mykhaya.app");
    expect(NATIVE_API_ORIGINS.production).toBe("https://api.mykhaya.app");
  });

  it("appends FastAPI's own /api/v1 mount prefix for each environment", () => {
    expect(nativeApiBaseUrl("development")).toBe("https://api.dev.mykhaya.app/api/v1");
    expect(nativeApiBaseUrl("production")).toBe("https://api.mykhaya.app/api/v1");
  });
});
