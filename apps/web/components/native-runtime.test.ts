// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: vi.fn(),
    getPlatform: vi.fn(),
  },
}));

import { Capacitor } from "@capacitor/core";
import { isNativeShell, isPlatformControlCentre, isPlatformControlCentreHost, nativePlatform } from "./native-runtime";

describe("isNativeShell", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("returns true inside the Capacitor native shell", () => {
    vi.mocked(Capacitor.isNativePlatform).mockReturnValue(true);
    expect(isNativeShell()).toBe(true);
  });

  it("returns false in an ordinary browser tab", () => {
    vi.mocked(Capacitor.isNativePlatform).mockReturnValue(false);
    expect(isNativeShell()).toBe(false);
  });
});

describe("nativePlatform", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("reports ios", () => {
    vi.mocked(Capacitor.getPlatform).mockReturnValue("ios");
    expect(nativePlatform()).toBe("ios");
  });

  it("reports android", () => {
    vi.mocked(Capacitor.getPlatform).mockReturnValue("android");
    expect(nativePlatform()).toBe("android");
  });

  it("falls back to web for the browser platform value", () => {
    vi.mocked(Capacitor.getPlatform).mockReturnValue("web");
    expect(nativePlatform()).toBe("web");
  });
});

describe("platform surface detection", () => {
  it("recognises admin hosts independently of the middleware rewrite path", () => {
    Object.defineProperty(window, "location", { value: { hostname: "admin.dev.mykhaya.app" }, configurable: true });
    expect(isPlatformControlCentre()).toBe(true);
  });

  it("does not classify the consumer host as PCC", () => {
    Object.defineProperty(window, "location", { value: { hostname: "dev.mykhaya.app" }, configurable: true });
    expect(isPlatformControlCentre()).toBe(false);
  });

  it("supports the server-side root-layout boundary", () => {
    expect(isPlatformControlCentreHost("admin.dev.mykhaya.app:443")).toBe(true);
    expect(isPlatformControlCentreHost("dev.mykhaya.app")).toBe(false);
  });
});
