// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const plugin = vi.hoisted(() => ({ openAppSettings: vi.fn() }));
const platform = vi.hoisted(() => ({ native: true, value: "ios" as "ios" | "android" | "web" }));

vi.mock("@capacitor/core", () => ({ registerPlugin: () => plugin }));
vi.mock("./native-runtime", () => ({
  isNativeShell: () => platform.native,
  nativePlatform: () => platform.value,
}));

beforeEach(() => {
  platform.native = true;
  platform.value = "ios";
  plugin.openAppSettings.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.resetModules();
});

describe("openAppSettings", () => {
  it("no-ops outside the native shell", async () => {
    platform.native = false;
    const { openAppSettings } = await import("./system-settings-bridge");

    await openAppSettings();
    expect(plugin.openAppSettings).not.toHaveBeenCalled();
  });

  it("calls the native SystemSettings plugin when available", async () => {
    const { openAppSettings } = await import("./system-settings-bridge");

    await openAppSettings();
    expect(plugin.openAppSettings).toHaveBeenCalledTimes(1);
  });

  it("calls the same SystemSettings plugin on Android — one JS call site, no platform branching", async () => {
    platform.value = "android";
    const { openAppSettings } = await import("./system-settings-bridge");

    await openAppSettings();
    expect(plugin.openAppSettings).toHaveBeenCalledTimes(1);
  });

  it("falls back to the app-settings: URL scheme if the native plugin call fails", async () => {
    plugin.openAppSettings.mockRejectedValue(new Error("plugin not implemented"));
    const originalLocation = window.location;
    // jsdom's window.location isn't directly assignable — replace it for
    // this test only, matching the well-known jsdom-navigation test idiom.
    // @ts-expect-error -- intentional test-only override
    delete window.location;
    // @ts-expect-error -- minimal stub, only `href` is exercised
    window.location = { href: "" };

    const { openAppSettings } = await import("./system-settings-bridge");
    await openAppSettings();

    expect(window.location.href).toBe("app-settings:");
    // @ts-expect-error -- restoring jsdom's real Location after the test-only override above
    window.location = originalLocation;
  });

  it("does not attempt the iOS URL-scheme fallback on Android — there is no equivalent there", async () => {
    platform.value = "android";
    plugin.openAppSettings.mockRejectedValue(new Error("plugin not implemented"));
    const originalLocation = window.location;
    // @ts-expect-error -- intentional test-only override
    delete window.location;
    // @ts-expect-error -- minimal stub, only `href` is exercised
    window.location = { href: "" };

    const { openAppSettings } = await import("./system-settings-bridge");
    await expect(openAppSettings()).resolves.toBeUndefined();

    expect(window.location.href).toBe("");
    // @ts-expect-error -- restoring jsdom's real Location after the test-only override above
    window.location = originalLocation;
  });

  it("never throws even if both the plugin and the fallback fail", async () => {
    plugin.openAppSettings.mockRejectedValue(new Error("plugin not implemented"));
    const originalLocation = window.location;
    // @ts-expect-error -- intentional test-only override
    delete window.location;
    // @ts-expect-error -- a location whose href setter itself throws
    window.location = {
      set href(_value: string) {
        throw new Error("navigation blocked");
      },
    };

    const { openAppSettings } = await import("./system-settings-bridge");
    await expect(openAppSettings()).resolves.toBeUndefined();
    // @ts-expect-error -- restoring jsdom's real Location after the test-only override above
    window.location = originalLocation;
  });
});
