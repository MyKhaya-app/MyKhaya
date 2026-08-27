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

  it("get() returns the stored token", async () => {
    storageGet.mockResolvedValue("the-token");
    const store = new KeychainNativeSessionStore();

    expect(await store.get()).toEqual({ token: "the-token" });
  });

  it("get() fails safe (returns null) if the Keychain read itself fails", async () => {
    storageGet.mockRejectedValue(new StorageError("boom", "osError" as StorageErrorType));
    const store = new KeychainNativeSessionStore();

    expect(await store.get()).toBeNull();
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
  });

  it("clear() removes the key with sync disabled", async () => {
    const store = new KeychainNativeSessionStore();

    await store.clear();

    expect(storageRemove).toHaveBeenCalledWith("mykhaya.native.session.token", false);
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
