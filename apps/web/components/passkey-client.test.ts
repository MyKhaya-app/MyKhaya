import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  authenticateWithPasskey,
  biometricLabel,
  biometricSignInAvailable,
  clearBiometricHint,
  createPasskey,
  getBiometricHint,
  passkeyWasCancelled,
  passkeysSupported,
  setBiometricHint,
} from "./passkey-client";

const browserMocks = vi.hoisted(() => ({
  startAuthentication: vi.fn(async () => ({ id: "assertion" })),
  startRegistration: vi.fn(async () => ({ id: "registration" })),
}));

vi.mock("@simplewebauthn/browser", () => browserMocks);

describe("passkey browser helpers", () => {
  it("reports unsupported browsers without affecting password fallback", () => {
    expect(passkeysSupported()).toBe(false);
  });

  it("passes server options to the registration and authentication ceremonies", async () => {
    const creation = await createPasskey('{"challenge":"create"}');
    const assertion = await authenticateWithPasskey('{"challenge":"get"}');

    expect(creation).toEqual({ id: "registration" });
    expect(assertion).toEqual({ id: "assertion" });
    expect(browserMocks.startRegistration).toHaveBeenCalledWith({
      optionsJSON: { challenge: "create" },
    });
    expect(browserMocks.startAuthentication).toHaveBeenCalledWith({
      optionsJSON: { challenge: "get" },
    });
  });

  it("recognises platform cancellation separately from verification errors", () => {
    expect(passkeyWasCancelled(new DOMException("cancelled", "NotAllowedError"))).toBe(true);
    expect(passkeyWasCancelled(new Error("failed"))).toBe(false);
  });
});

// Patches individual navigator/window properties in place (via
// defineProperty, restored in afterEach) rather than vi.stubGlobal, which
// would replace the *entire* navigator/window object — jsdom globals are
// shared with other test files in this worker, and a wholesale replacement
// leaked into unrelated suites (e.g. app-shell's use of matchMedia) the
// first time this was tried.
function patchProperty<T extends object, K extends keyof T>(
  target: T,
  key: K,
  value: T[K],
): () => void {
  const original = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { value, configurable: true, writable: true });
  return () => {
    if (original) Object.defineProperty(target, key, original);
    else delete (target as Record<string, unknown>)[key as string];
  };
}

describe("biometricSignInAvailable", () => {
  const restores: (() => void)[] = [];
  afterEach(() => {
    while (restores.length) restores.pop()?.();
  });

  it("is false when the browser has no WebAuthn support at all", async () => {
    expect(await biometricSignInAvailable()).toBe(false);
  });

  it("is true only when the platform authenticator check resolves true", async () => {
    restores.push(
      patchProperty(window, "PublicKeyCredential", {
        isUserVerifyingPlatformAuthenticatorAvailable: vi.fn(async () => true),
      } as unknown as typeof PublicKeyCredential),
      patchProperty(navigator, "credentials", {
        get: vi.fn(),
        create: vi.fn(),
      } as unknown as CredentialsContainer),
    );
    expect(await biometricSignInAvailable()).toBe(true);
  });

  it("is false when no platform authenticator is available (e.g. desktop with no Windows Hello)", async () => {
    restores.push(
      patchProperty(window, "PublicKeyCredential", {
        isUserVerifyingPlatformAuthenticatorAvailable: vi.fn(async () => false),
      } as unknown as typeof PublicKeyCredential),
      patchProperty(navigator, "credentials", {
        get: vi.fn(),
        create: vi.fn(),
      } as unknown as CredentialsContainer),
    );
    expect(await biometricSignInAvailable()).toBe(false);
  });

  it("does not throw when the platform check itself rejects", async () => {
    restores.push(
      patchProperty(window, "PublicKeyCredential", {
        isUserVerifyingPlatformAuthenticatorAvailable: vi.fn(async () => {
          throw new Error("blocked");
        }),
      } as unknown as typeof PublicKeyCredential),
      patchProperty(navigator, "credentials", {
        get: vi.fn(),
        create: vi.fn(),
      } as unknown as CredentialsContainer),
    );
    expect(await biometricSignInAvailable()).toBe(false);
  });
});

describe("biometricLabel", () => {
  const restores: (() => void)[] = [];
  afterEach(() => {
    while (restores.length) restores.pop()?.();
  });

  it("guesses Face ID on iPhone", () => {
    restores.push(
      patchProperty(navigator, "userAgent", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"),
    );
    expect(biometricLabel()).toBe("Face ID");
  });

  it("guesses Windows Hello on Windows", () => {
    restores.push(patchProperty(navigator, "userAgent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"));
    expect(biometricLabel()).toBe("Windows Hello");
  });

  it("falls back to generic biometrics wording on Android, never claiming a specific modality", () => {
    restores.push(patchProperty(navigator, "userAgent", "Mozilla/5.0 (Linux; Android 14)"));
    expect(biometricLabel()).toBe("biometrics");
  });

  it("falls back to generic device-security wording for anything unrecognised", () => {
    restores.push(patchProperty(navigator, "userAgent", "SomeOtherBrowser/1.0"));
    expect(biometricLabel()).toBe("device security");
  });
});

describe("biometric enrolment hint (local UX hint only, never a credential)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("is null until a hint is set", () => {
    expect(getBiometricHint()).toBeNull();
  });

  it("stores and retrieves only non-sensitive identity fields", () => {
    setBiometricHint({ userId: "user-1", displayName: "Anthony", avatarVersion: "v2" });
    expect(getBiometricHint()).toEqual({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: "v2",
    });
    expect(window.localStorage.getItem("mk_biometric_hint")).not.toContain("token");
    expect(window.localStorage.getItem("mk_biometric_hint")).not.toContain("credential");
  });

  it("clears the hint on disable", () => {
    setBiometricHint({ userId: "user-1", displayName: "Anthony", avatarVersion: null });
    clearBiometricHint();
    expect(getBiometricHint()).toBeNull();
  });

  it("ignores malformed/tampered localStorage content rather than throwing", () => {
    window.localStorage.setItem("mk_biometric_hint", "not json");
    expect(getBiometricHint()).toBeNull();
    window.localStorage.setItem("mk_biometric_hint", JSON.stringify({ foo: "bar" }));
    expect(getBiometricHint()).toBeNull();
  });
});
