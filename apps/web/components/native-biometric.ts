import {
  BiometricAuth,
  BiometryError,
  BiometryErrorType,
  BiometryType,
  type CheckBiometryResult,
} from "@aparajita/capacitor-biometric-auth";
import { nativePlatform } from "./native-runtime";

// Native Face ID/Touch ID, via LocalAuthentication under the hood (the
// plugin's native iOS implementation wraps LAContext directly — see
// https://github.com/aparajita/capacitor-biometric-auth). Deliberately not
// PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable() or any
// other browser/WebAuthn capability check: that is components/passkey-client.ts's
// concern for the browser/PWA "Biometric sign-in" feature, a separate,
// untouched code path — see app/settings/security/page.tsx, which renders
// that card only outside the native shell and this module's "Quick Sign-In"
// card only inside it.
//
// `BiometricProvider` is the injectable seam Phase 17 asks for where the
// real native call (LAContext, via this plugin) can't be exercised in a
// unit test: production code always goes through the module-level
// `provider`, and tests substitute their own via
// `setBiometricProviderForTesting`.
export interface BiometricProvider {
  checkBiometry(): Promise<CheckBiometryResult>;
  authenticate(reason: string): Promise<void>;
}

function biometricDebug(event: string, fields: Record<string, unknown> = {}): void {
  console.info("[BIOMETRIC DEBUG]", event, fields);
}

// `@aparajita/capacitor-biometric-auth` is deliberately not a dependency of
// apps/android-shell (Face ID/Touch ID via LocalAuthentication is an iOS
// concept; Android biometrics are an unimplemented future phase — see this
// file's top-of-file doc comment). But apps/web ships one JS bundle to both
// native shells, and this plugin's own `registerPlugin()` call (unlike
// widget-bridge.ts's repo-local WidgetBridge) declares an explicit `android`
// JS factory that just delegates to the native bridge — so Capacitor's
// normal "plugin not implemented" fast-fail (thrown only when a platform key
// is *absent*) never triggers. Instead, because the Android build has no
// native "BiometricAuthNative" plugin compiled in, `@aparajita/capacitor-
// biometric-auth`'s own `BiometricAuthNative` class (dist/esm/native.js)
// binds `this.checkBiometry = proxy.checkBiometry` — where `proxy` is that
// same outer Capacitor plugin proxy — so Capacitor's method-resolution
// fallback (no native header found) hands back that identical proxy method
// as the "implementation," making every call recurse into itself forever.
// Confirmed via a live Android emulator: calling checkBiometry() straight
// after login (NativeBiometricOffer's post-login effect, the one call site
// with no withNativeStartupTimeout guard) triggers unbounded async
// self-recursion that runs the WebView renderer's V8 heap from ~180MB to
// the ~1GB OOM ceiling in under 20 seconds — a hard renderer crash, not a
// slow leak. Guarding here, at the one place production code reaches the
// real plugin, keeps every current and future caller of
// getBiometricCapability()/authenticateWithBiometrics() safe without
// touching either of them or their callers, and leaves
// setBiometricProviderForTesting's injected providers (used by every test
// in native-biometric.test.ts) completely unaffected.
const defaultProvider: BiometricProvider = {
  checkBiometry: () => {
    if (nativePlatform() !== "ios") {
      return Promise.resolve({
        isAvailable: false,
        strongBiometryIsAvailable: false,
        biometryType: BiometryType.none,
        biometryTypes: [],
        deviceIsSecure: false,
        reason: "Biometric sign-in is not available on this device yet.",
        code: BiometryErrorType.none,
      });
    }
    return BiometricAuth.checkBiometry();
  },
  // allowDeviceCredential: true — Phase 4's "device passcode fallback where
  // appropriate": if biometry itself is unavailable/fails, iOS offers the
  // device passcode as a fallback rather than dead-ending the user.
  authenticate: (reason) => {
    if (nativePlatform() !== "ios") {
      return Promise.reject(
        new BiometryError(
          "Biometric sign-in is not available on this device yet.",
          BiometryErrorType.biometryNotAvailable,
        ),
      );
    }
    return BiometricAuth.authenticate({ reason, allowDeviceCredential: true });
  },
};

let provider: BiometricProvider = defaultProvider;

export function setBiometricProviderForTesting(next: BiometricProvider): void {
  provider = next;
}

export function resetBiometricProvider(): void {
  provider = defaultProvider;
}

export type BiometricKind = "faceId" | "touchId" | "other" | "none";

export interface BiometricCapability {
  kind: BiometricKind;
  /** Human, product-facing label — "Face ID"/"Touch ID" specifically when
   * known, matching Phase 4's "display the correct terminology" — never a
   * generic "browser"/"device" placeholder. */
  label: string;
  /** Hardware present *and* enrolled *and* not currently locked out — the
   * single flag the Quick Sign-In UI uses to decide whether to offer the
   * "Enable Face ID"/"Enable Touch ID" button at all. */
  available: boolean;
  lockedOut: boolean;
  /** True only when hardware exists but nothing is enrolled — lets the UI
   * show "Face ID isn't set up on this iPhone yet" instead of a generic
   * unavailable message. */
  notEnrolled: boolean;
  /** System-provided explanation when unavailable, empty string otherwise. */
  reason: string;
}

function kindFromType(type: BiometryType): BiometricKind {
  switch (type) {
    case BiometryType.faceId:
      return "faceId";
    case BiometryType.touchId:
      return "touchId";
    case BiometryType.none:
      return "none";
    default:
      // Android fingerprint/face/iris — not a MyKhaya iOS concern today,
      // but named honestly rather than mislabelled as Face ID/Touch ID.
      return "other";
  }
}

export function biometricLabel(kind: BiometricKind): string {
  switch (kind) {
    case "faceId":
      return "Face ID";
    case "touchId":
      return "Touch ID";
    case "other":
      return "biometric sign-in";
    case "none":
      return "Face ID";
  }
}

/** Native capability/enrolment check (Phase 4's "biometric capability,
 * biometric type, enrolled/not enrolled, unavailable, temporarily
 * locked"). Never throws — a check failure itself is reported as
 * `available: false` with `reason` set, since "can't even tell" and "not
 * available" both lead to the same UI (no Quick Sign-In offer). */
export async function getBiometricCapability(): Promise<BiometricCapability> {
  biometricDebug("availability_check_started");
  const result = await provider.checkBiometry();
  const kind = kindFromType(result.biometryType);
  biometricDebug("availability_result", { available: result.isAvailable, type: kind, code: result.code });
  return {
    kind,
    label: biometricLabel(kind),
    available: result.isAvailable,
    lockedOut: result.code === BiometryErrorType.biometryLockout,
    notEnrolled: result.code === BiometryErrorType.biometryNotEnrolled,
    reason: result.reason,
  };
}

export type BiometricAuthResult =
  | { ok: true }
  | { ok: false; code: BiometryErrorType | "unknown"; message: string };

/** Prompts Face ID/Touch ID (with device-passcode fallback). Never throws —
 * every failure mode from Phase 7 (cancelled, failed match, lockout, not
 * enrolled, no passcode set, ...) comes back as a typed, inspectable
 * result instead of an exception the caller has to know to catch, so a
 * plain cancellation can never be mistaken for — or accidentally handled
 * like — a destroyed session. */
export async function authenticateWithBiometrics(reason: string): Promise<BiometricAuthResult> {
  biometricDebug("challenge_requested");
  try {
    biometricDebug("challenge_started");
    await provider.authenticate(reason);
    biometricDebug("challenge_resolved");
    return { ok: true };
  } catch (error) {
    if (error instanceof BiometryError) {
      biometricDebug("challenge_rejected", { code: error.code });
      return { ok: false, code: error.code, message: error.message };
    }
    biometricDebug("challenge_rejected", { code: "unknown" });
    return {
      ok: false,
      code: "unknown",
      message: error instanceof Error ? error.message : "Biometric authentication failed.",
    };
  }
}

/** Cancellation/dismissal specifically — the one BiometricAuthResult that
 * must never be treated as "something is wrong": Phase 7's "a simple
 * biometric cancellation should not destroy a valid backend session." */
export function isBiometricCancellation(result: BiometricAuthResult): boolean {
  return (
    !result.ok &&
    (result.code === BiometryErrorType.userCancel || result.code === BiometryErrorType.appCancel)
  );
}
