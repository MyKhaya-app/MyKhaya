import { afterEach, describe, expect, it, vi } from "vitest";
import type { StorageErrorType } from "@aparajita/capacitor-secure-storage";

const { storageGet, storageSet, storageRemove } = vi.hoisted(() => ({
  storageGet: vi.fn(),
  storageSet: vi.fn(),
  storageRemove: vi.fn(),
}));

vi.mock("@aparajita/capacitor-secure-storage", () => {
  class StorageError extends Error {
    code: string;
    constructor(message: string, code: string) {
      super(message);
      this.code = code;
    }
  }
  return {
    SecureStorage: { get: storageGet, set: storageSet, remove: storageRemove },
    KeychainAccess: { whenUnlockedThisDeviceOnly: 1 },
    StorageError,
  };
});

const { KeychainNativeSessionStore } = await import("./keychain-native-session-store");
const { StorageError } = await import("@aparajita/capacitor-secure-storage");

describe("KeychainNativeSessionStore", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("get() returns null when nothing is stored", async () => {
    storageGet.mockResolvedValue(null);
    const store = new KeychainNativeSessionStore();

    expect(await store.get()).toBeNull();
    expect(storageGet).toHaveBeenCalledWith("mykhaya.native.session.token", false, false);
  });

  it("get() returns the stored token when there is no device token", async () => {
    storageGet.mockImplementation((key: string) =>
      Promise.resolve(key === "mykhaya.native.session.token" ? "the-token" : null),
    );
    const store = new KeychainNativeSessionStore();

    expect(await store.get()).toEqual({ token: "the-token" });
  });

  it("get() also returns the device token when one is stored alongside the session", async () => {
    storageGet.mockImplementation((key: string) =>
      Promise.resolve(
        key === "mykhaya.native.session.token"
          ? "the-token"
          : key === "mykhaya.native.session.device_token"
            ? "the-device-token"
            : null,
      ),
    );
    const store = new KeychainNativeSessionStore();

    expect(await store.get()).toEqual({ token: "the-token", deviceToken: "the-device-token" });
  });

  it("propagates a Keychain read failure so startup cannot mistake it for signed-out", async () => {
    storageGet.mockRejectedValue(new StorageError("boom", "osError" as StorageErrorType));
    const store = new KeychainNativeSessionStore();

    await expect(store.get()).rejects.toBeInstanceOf(StorageError);
  });

  it("recovers the session across fresh store instances", async () => {
    const values = new Map<string, unknown>();
    storageSet.mockImplementation((key: string, value: unknown) => {
      values.set(key, value);
      return Promise.resolve();
    });
    storageGet.mockImplementation((key: string) => Promise.resolve(values.get(key) ?? null));

    await new KeychainNativeSessionStore().set({
      token: "persisted-session",
      deviceToken: "persisted-device",
    });
    const newStore = new KeychainNativeSessionStore();

    await expect(newStore.get()).resolves.toEqual({
      token: "persisted-session",
      deviceToken: "persisted-device",
    });
  });

  it("set() writes with sync disabled and whenUnlockedThisDeviceOnly access, every time", async () => {
    const store = new KeychainNativeSessionStore();

    await store.set({ token: "new-token" });

    expect(storageSet).toHaveBeenCalledWith(
      "mykhaya.native.session.token",
      "new-token",
      false,
      false,
      1,
    );
    // No deviceToken supplied — a rotate()-style refresh must never touch
    // (or clear) whatever device token is already stored.
    expect(storageSet).toHaveBeenCalledTimes(1);
  });

  it("set() also writes the device token when one is supplied, under its own key", async () => {
    const store = new KeychainNativeSessionStore();

    await store.set({ token: "new-token", deviceToken: "new-device-token" });

    expect(storageSet).toHaveBeenCalledWith(
      "mykhaya.native.session.token",
      "new-token",
      false,
      false,
      1,
    );
    expect(storageSet).toHaveBeenCalledWith(
      "mykhaya.native.session.device_token",
      "new-device-token",
      false,
      false,
      1,
    );
  });

  it("clear() removes both the session and device token keys, with sync disabled", async () => {
    const store = new KeychainNativeSessionStore();

    await store.clear();

    expect(storageRemove).toHaveBeenCalledWith("mykhaya.native.session.token", false);
    expect(storageRemove).toHaveBeenCalledWith("mykhaya.native.session.device_token", false);
  });

  it("clear() swallows a Keychain-level failure rather than throwing", async () => {
    storageRemove.mockRejectedValue(new StorageError("boom", "osError" as StorageErrorType));
    const store = new KeychainNativeSessionStore();

    await expect(store.clear()).resolves.toBeUndefined();
  });

  it("clearIfMatches() clears when the stored token matches", async () => {
    storageGet.mockResolvedValue("token-a");
    const store = new KeychainNativeSessionStore();

    await store.clearIfMatches("token-a");

    expect(storageRemove).toHaveBeenCalledWith("mykhaya.native.session.token", false);
  });

  it("clearIfMatches() is a no-op when a concurrent rotation already replaced the token", async () => {
    // Same compare-and-clear race Phase 2 tested against InMemoryNativeSessionStore
    // (packages/api-client/src/native-session-store.test.ts) — re-verified here
    // against the real storage backend's own get-then-remove path.
    storageGet.mockResolvedValue("token-b");
    const store = new KeychainNativeSessionStore();

    await store.clearIfMatches("token-a");

    expect(storageRemove).not.toHaveBeenCalled();
  });
});
