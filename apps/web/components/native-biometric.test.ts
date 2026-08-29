import { afterEach, describe, expect, it } from "vitest";
import { BiometryError, BiometryErrorType, BiometryType } from "@aparajita/capacitor-biometric-auth";
import {
  authenticateWithBiometrics,
  biometricLabel,
  getBiometricCapability,
  isBiometricCancellation,
  resetBiometricProvider,
  setBiometricProviderForTesting,
  type BiometricProvider,
} from "./native-biometric";

function provider(overrides: Partial<BiometricProvider> = {}): BiometricProvider {
  return {
    checkBiometry: async () => ({
      isAvailable: true,
      strongBiometryIsAvailable: true,
      biometryType: BiometryType.faceId,
      biometryTypes: [BiometryType.faceId],
      deviceIsSecure: true,
      reason: "",
      code: BiometryErrorType.none,
    }),
    authenticate: async () => {},
    ...overrides,
  };
}

afterEach(() => {
  resetBiometricProvider();
});

describe("getBiometricCapability", () => {
  it("reports Face ID as available and correctly labelled", async () => {
    setBiometricProviderForTesting(provider());

    const capability = await getBiometricCapability();

    expect(capability).toMatchObject({ kind: "faceId", label: "Face ID", available: true });
  });

  it("reports Touch ID with the correct label", async () => {
    setBiometricProviderForTesting(
      provider({
        checkBiometry: async () => ({
          isAvailable: true,
          strongBiometryIsAvailable: true,
          biometryType: BiometryType.touchId,
          biometryTypes: [BiometryType.touchId],
          deviceIsSecure: true,
          reason: "",
          code: BiometryErrorType.none,
        }),
      }),
    );

    const capability = await getBiometricCapability();

    expect(capability).toMatchObject({ kind: "touchId", label: "Touch ID" });
  });

  it("reports not-enrolled distinctly from generally unavailable", async () => {
    setBiometricProviderForTesting(
      provider({
        checkBiometry: async () => ({
          isAvailable: false,
          strongBiometryIsAvailable: false,
          biometryType: BiometryType.faceId,
          biometryTypes: [BiometryType.faceId],
          deviceIsSecure: true,
          reason: "No identities enrolled.",
          code: BiometryErrorType.biometryNotEnrolled,
        }),
      }),
    );

    const capability = await getBiometricCapability();

    expect(capability.available).toBe(false);
    expect(capability.notEnrolled).toBe(true);
    expect(capability.lockedOut).toBe(false);
    // Still says "Face ID" — never "the browser doesn't support this".
    expect(capability.label).toBe("Face ID");
  });

  it("reports a temporary lockout distinctly", async () => {
    setBiometricProviderForTesting(
      provider({
        checkBiometry: async () => ({
          isAvailable: false,
          strongBiometryIsAvailable: false,
          biometryType: BiometryType.faceId,
          biometryTypes: [BiometryType.faceId],
          deviceIsSecure: true,
          reason: "Too many failed attempts.",
          code: BiometryErrorType.biometryLockout,
        }),
      }),
    );

    const capability = await getBiometricCapability();

    expect(capability.lockedOut).toBe(true);
    expect(capability.available).toBe(false);
  });

  it("reports hardware absence as kind 'none'", async () => {
    setBiometricProviderForTesting(
      provider({
        checkBiometry: async () => ({
          isAvailable: false,
          strongBiometryIsAvailable: false,
          biometryType: BiometryType.none,
          biometryTypes: [],
          deviceIsSecure: true,
          reason: "Biometry not available.",
          code: BiometryErrorType.biometryNotAvailable,
        }),
      }),
    );

    const capability = await getBiometricCapability();

    expect(capability.kind).toBe("none");
    expect(capability.available).toBe(false);
  });
});

describe("authenticateWithBiometrics", () => {
  it("returns ok:true on success", async () => {
    setBiometricProviderForTesting(provider());

    const result = await authenticateWithBiometrics("Unlock MyKhaya");

    expect(result).toEqual({ ok: true });
  });

  it("returns a typed failure on user cancellation, never throwing", async () => {
    setBiometricProviderForTesting(
      provider({
        authenticate: async () => {
          throw new BiometryError("User cancelled", BiometryErrorType.userCancel);
        },
      }),
    );

    const result = await authenticateWithBiometrics("Unlock MyKhaya");

    expect(result.ok).toBe(false);
    expect(!result.ok && result.code).toBe(BiometryErrorType.userCancel);
    expect(isBiometricCancellation(result)).toBe(true);
  });

  it("returns a typed failure on lockout, distinct from cancellation", async () => {
    setBiometricProviderForTesting(
      provider({
        authenticate: async () => {
          throw new BiometryError("Locked out", BiometryErrorType.biometryLockout);
        },
      }),
    );

    const result = await authenticateWithBiometrics("Unlock MyKhaya");

    expect(result.ok).toBe(false);
    expect(isBiometricCancellation(result)).toBe(false);
  });

  it("returns a typed failure on failed match", async () => {
    setBiometricProviderForTesting(
      provider({
        authenticate: async () => {
          throw new BiometryError("Face not recognised", BiometryErrorType.authenticationFailed);
        },
      }),
    );

    const result = await authenticateWithBiometrics("Unlock MyKhaya");

    expect(result.ok).toBe(false);
    expect(!result.ok && result.code).toBe(BiometryErrorType.authenticationFailed);
  });

  it("wraps an unexpected non-BiometryError as code 'unknown' rather than throwing", async () => {
    setBiometricProviderForTesting(
      provider({
        authenticate: async () => {
          throw new Error("something else entirely");
        },
      }),
    );

    const result = await authenticateWithBiometrics("Unlock MyKhaya");

    expect(result).toEqual({ ok: false, code: "unknown", message: "something else entirely" });
  });
});

describe("biometricLabel", () => {
  it("names every kind correctly, never mentioning a browser", () => {
    expect(biometricLabel("faceId")).toBe("Face ID");
    expect(biometricLabel("touchId")).toBe("Touch ID");
    expect(biometricLabel("other")).not.toMatch(/browser|web|pwa/i);
    expect(biometricLabel("none")).not.toMatch(/browser|web|pwa/i);
  });
});
