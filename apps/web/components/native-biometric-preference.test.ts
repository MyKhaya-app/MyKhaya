import { describe, expect, it, vi } from "vitest";
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
    StorageError,
  };
});

const { getBiometricPreference, isBiometricSignInEnabled, setBiometricSignInEnabled, declineBiometricSignIn } = await import(
  "./native-biometric-preference"
);
const { StorageError } = await import("@aparajita/capacitor-secure-storage");

describe("isBiometricSignInEnabled", () => {
  it("is false when nothing is stored", async () => {
    storageGet.mockResolvedValue(null);
    expect(await isBiometricSignInEnabled()).toBe(false);
  });

  it("is true once enabled", async () => {
    storageGet.mockResolvedValue(true);
    expect(await isBiometricSignInEnabled()).toBe(true);
  });

  it("fails safe (false) if the Keychain read itself fails", async () => {
    storageGet.mockRejectedValue(new StorageError("boom", "osError" as StorageErrorType));
    expect(await isBiometricSignInEnabled()).toBe(false);
  });
});

describe("biometric preference lifecycle", () => {
  it("distinguishes an undecided preference from a deliberate Not now", async () => {
    storageGet.mockImplementation((key: string) => Promise.resolve(key.endsWith("declined") ? true : null));
    await expect(getBiometricPreference()).resolves.toBe("declined");
  });

  it("records Not now without storing a credential", async () => {
    await declineBiometricSignIn();
    expect(storageSet).toHaveBeenCalledWith("mykhaya.native.biometric.declined", true, false, false);
  });
});

describe("setBiometricSignInEnabled", () => {
  it("writes true with sync disabled when enabling", async () => {
    await setBiometricSignInEnabled(true);
    expect(storageSet).toHaveBeenCalledWith(
      "mykhaya.native.biometric.enabled",
      true,
      false,
      false,
    );
  });

  it("removes the key when disabling", async () => {
    await setBiometricSignInEnabled(false);
    expect(storageRemove).toHaveBeenCalledWith("mykhaya.native.biometric.enabled", false);
  });

  it("swallows a Keychain-level failure when disabling rather than throwing", async () => {
    storageRemove.mockRejectedValue(new StorageError("boom", "osError" as StorageErrorType));
    await expect(setBiometricSignInEnabled(false)).resolves.toBeUndefined();
  });
});
