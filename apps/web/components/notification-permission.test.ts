// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const platform = vi.hoisted(() => ({ value: "ios" as "ios" | "android" | "web" }));
const nativePush = vi.hoisted(() => ({
  requestNativePermissionOnly: vi.fn(),
  nativePushPermission: vi.fn(),
}));
const settingsBridge = vi.hoisted(() => ({ openAppSettings: vi.fn() }));

vi.mock("./native-runtime", () => ({ nativePlatform: () => platform.value }));
vi.mock("./native-push", () => nativePush);
vi.mock("./system-settings-bridge", () => settingsBridge);

beforeEach(() => {
  platform.value = "ios";
  nativePush.requestNativePermissionOnly.mockReset();
  nativePush.nativePushPermission.mockReset();
  settingsBridge.openAppSettings.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.resetModules();
});

describe("getNotificationPermissionAdapter — platform selection", () => {
  it("returns the native push adapter on iOS", async () => {
    const { getNotificationPermissionAdapter } = await import("./notification-permission");
    nativePush.nativePushPermission.mockResolvedValue({ receive: "granted" });

    const adapter = getNotificationPermissionAdapter();
    await expect(adapter.getPermissionStatus()).resolves.toBe("granted");
  });

  it("returns the same native push adapter on Android — one implementation, no separate Android settings experience", async () => {
    platform.value = "android";
    nativePush.nativePushPermission.mockResolvedValue({ receive: "granted" });
    const { getNotificationPermissionAdapter } = await import("./notification-permission");

    const adapter = getNotificationPermissionAdapter();
    await expect(adapter.getPermissionStatus()).resolves.toBe("granted");
  });

  it("returns the unsupported stub adapter on web", async () => {
    platform.value = "web";
    const { getNotificationPermissionAdapter } = await import("./notification-permission");

    const adapter = getNotificationPermissionAdapter();
    await expect(adapter.getPermissionStatus()).resolves.toBe("unsupported");
    await expect(adapter.requestPermission()).resolves.toBe("unsupported");
    await expect(adapter.openSystemNotificationSettings()).resolves.toBeUndefined();
    expect(settingsBridge.openAppSettings).not.toHaveBeenCalled();
  });
});

describe.each([["ios"], ["android"]] as const)(
  "native push adapter on %s — status mapping from Capacitor PermissionState",
  (platformValue) => {
    beforeEach(() => {
      platform.value = platformValue;
    });

    it.each([
      ["granted", "granted"],
      ["denied", "denied"],
      ["prompt", "not_requested"],
      ["prompt-with-rationale", "not_requested"],
    ] as const)("maps checkPermissions() receive=%s to %s", async (receive, expected) => {
      nativePush.nativePushPermission.mockResolvedValue({ receive });
      const { getNotificationPermissionAdapter } = await import("./notification-permission");

      await expect(getNotificationPermissionAdapter().getPermissionStatus()).resolves.toBe(expected);
    });
  },
);

describe("native push adapter (iOS, default platform in this file's beforeEach) — remaining behaviour", () => {
  it("maps a null permission (unsupported) to 'unsupported'", async () => {
    nativePush.nativePushPermission.mockResolvedValue(null);
    const { getNotificationPermissionAdapter } = await import("./notification-permission");

    await expect(getNotificationPermissionAdapter().getPermissionStatus()).resolves.toBe("unsupported");
  });

  it("refreshPermissionStatus performs the same live check as getPermissionStatus", async () => {
    nativePush.nativePushPermission.mockResolvedValueOnce({ receive: "denied" });
    nativePush.nativePushPermission.mockResolvedValueOnce({ receive: "granted" });
    const { getNotificationPermissionAdapter } = await import("./notification-permission");
    const adapter = getNotificationPermissionAdapter();

    await expect(adapter.getPermissionStatus()).resolves.toBe("denied");
    await expect(adapter.refreshPermissionStatus()).resolves.toBe("granted");
  });

  it("requestPermission delegates to requestNativePermissionOnly (never conflates registration outcome)", async () => {
    nativePush.requestNativePermissionOnly.mockResolvedValue("granted");
    const { getNotificationPermissionAdapter } = await import("./notification-permission");

    await expect(getNotificationPermissionAdapter().requestPermission()).resolves.toBe("granted");
    expect(nativePush.requestNativePermissionOnly).toHaveBeenCalledTimes(1);
  });

  it("openSystemNotificationSettings delegates to the system-settings-bridge", async () => {
    const { getNotificationPermissionAdapter } = await import("./notification-permission");

    await getNotificationPermissionAdapter().openSystemNotificationSettings();
    expect(settingsBridge.openAppSettings).toHaveBeenCalledTimes(1);
  });
});
