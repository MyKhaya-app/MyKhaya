import {
  BiometricAuth,
  BiometryError,
  BiometryErrorType,
  BiometryType,
  type CheckBiometryResult,
} from "@aparajita/capacitor-biometric-auth";
import { nativePlatform } from "./native-runtime";

// Native biometric sign-in via @aparajita/capacitor-biometric-auth — on iOS,
// Face ID/Touch ID via LocalAuthentication (LAContext) under the hood; on
// Android, whatever BiometricPrompt/BiometricManager report as available
// (fingerprint, face, or iris, depending on device hardware and enrolment —
// see https://github.com/aparajita/capacitor-biometric-auth). Deliberately
// not PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable() or
// any other browser/WebAuthn capability check: that is
// components/passkey-client.ts's concern for the browser/PWA "Biometric
// sign-in" feature, a separate, untouched code path — see
// app/settings/security/page.tsx, which renders that card only outside the
// native shell and this module's "Quick Sign-In" card only inside it.
//
// `BiometricProvider` is the injectable seam Phase 17 asks for where the
// real native call can't be exercised in a unit test: production code
// always goes through the module-level `provider`, and tests substitute
// their own via `setBiometricProviderForTesting`.
export interface BiometricProvider {
  checkBiometry(): Promise<CheckBiometryResult>;
  authenticate(reason: string): Promise<void>;
}

function biometricDebug(event: string, fields: Record<string, unknown> = {}): void {
  console.info("[BIOMETRIC DEBUG]", event, fields);
}

// Historical note, kept because the failure mode it describes is worth
// remembering even though it's now fixed: `@aparajita/capacitor-biometric-
// auth` was for a time deliberately *not* a dependency of
// apps/android-shell, with every call here hard-blocked below this comment.
// That plugin's own `registerPlugin()` call (unlike widget-bridge.ts's
// repo-local WidgetBridge) declares an explicit `android` JS factory that
// just delegates to the native bridge — so Capacitor's normal "plugin not
// implemented" fast-fail (thrown only when a platform key is *absent*)
// never triggers on Android regardless of whether a native implementation
// is actually compiled in. With no native "BiometricAuthNative" plugin
// registered, the plugin's own `BiometricAuthNative` class (dist/esm/
// native.js) bound `this.checkBiometry = proxy.checkBiometry` — where
// `proxy` is that same outer Capacitor plugin proxy — so Capacitor's
// method-resolution fallback (no native header found) handed back that
// identical proxy method as the "implementation," making every call
// recurse into itself forever. Confirmed via a live Android emulator:
// calling checkBiometry() straight after login (NativeBiometricOffer's
// post-login effect, the one call site with no withNativeStartupTimeout
// guard) ran the WebView renderer's V8 heap from ~180MB to the ~1GB OOM
// ceiling in under 20 seconds — a hard renderer crash, not a slow leak.
//
// Fixed by adding `@aparajita/capacitor-biometric-auth` to
// apps/android-shell/package.json (pinned to the same 10.0.0 already used
// by apps/ios-shell) and running `cap sync android`, which now reports the
// plugin registered (`capacitor.settings.gradle`/`app/capacitor.build.gradle`
// include and link its real `android/` Gradle module — verified by
// decompiling a debug build: `BiometricAuthNative`/`AuthActivity` classes
// and the `android.permission.USE_BIOMETRIC` permission are present in the
// final APK). With a real `pluginHeader` now present, Capacitor's method
// resolution dispatches straight to the native bridge instead of ever
// reaching the self-referencing JS fallback above, so the recursion this
// guarded against can no longer happen. Do not remove the dependency (or
// re-add a platform block here) without re-verifying registration the same
// way — see the Phase 2B/Android-biometric investigation reports for the
// full reproduction.
const defaultProvider: BiometricProvider = {
  checkBiometry: () => BiometricAuth.checkBiometry(),
  // allowDeviceCredential: true — "device passcode/PIN/pattern fallback
  // where appropriate": if biometry itself is unavailable/fails, the OS
  // offers its own device-credential challenge as a fallback rather than
  // dead-ending the user. Handled identically by both native
  // implementations — iOS's LAPolicy and Android's
  // BiometricManager.Authenticators (confirmed in BiometricAuthNative.java:
  // reads the same `allowDeviceCredential` option this call sends) — so
  // this needs no platform branching at all.
  authenticate: (reason) => BiometricAuth.authenticate({ reason, allowDeviceCredential: true }),
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
   * "Enable {label}" button at all. */
  available: boolean;
  lockedOut: boolean;
  /** True only when hardware exists but nothing is enrolled — lets the UI
   * show "{label} isn't set up on this {device} yet" instead of a generic
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
      // Android fingerprint/face/iris authentication. Deliberately not
      // split into three distinct kinds: BiometricManager reports which
      // *modalities* the hardware supports, not which one the user will
      // actually be challenged with (a device with both a fingerprint
      // sensor and face unlock lets the system picker choose at prompt
      // time), so naming a single one here would just as often be wrong as
      // right — "biometric sign-in" is the honest, neutral label per the
      // Android biometric UX guidelines this plugin itself follows.
      return "other";
  }
}

/** "this iPhone" is only ever accurate on iOS — every other native platform
 *  (today, Android) gets a deliberately generic "this device" rather than a
 *  guess at device model/manufacturer. Always the full determiner + noun
 *  phrase (never a bare noun a caller has to remember to prefix with
 *  "this") so every call site composes it the same, safe way. Exported so
 *  quick-sign-in.tsx's copy (the only other place "iPhone" was previously
 *  hardcoded) can share it. */
export function deviceNoun(): string {
  return nativePlatform() === "ios" ? "this iPhone" : "this device";
}

/** Copy for the "Unlock MyKhaya" screen (app/page.tsx and app-shell.tsx's
 * `status === "locked"` branches) — rendered before any async capability
 * check can resolve, so unlike `biometricLabel()` this is a synchronous,
 * platform-only guess at what the OS will actually challenge with. Never
 * wrong in a way that matters: it's describing the *system* prompt that's
 * about to appear (or already did), not making a promise the app itself
 * has to keep. */
export function genericUnlockPromptCopy(): string {
  return nativePlatform() === "ios"
    ? "Face ID, Touch ID, or your device passcode"
    : "your biometric sign-in or device screen lock";
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
      // Only iOS has ever had a single named modality worth guessing at as
      // a fallback while the real check is still pending/unknown — Android
      // never had one "the" biometric, so falling back to "Face ID" there
      // would be actively wrong, not just imprecise.
      return nativePlatform() === "ios" ? "Face ID" : "biometric sign-in";
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

/** Prompts the platform's native biometric UI — Face ID/Touch ID on iOS,
 * BiometricPrompt on Android — with device-passcode fallback. Never throws —
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
