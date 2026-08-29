import {
  BiometricAuth,
  BiometryError,
  BiometryErrorType,
  BiometryType,
  type CheckBiometryResult,
} from "@aparajita/capacitor-biometric-auth";

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

const defaultProvider: BiometricProvider = {
  checkBiometry: () => BiometricAuth.checkBiometry(),
  // allowDeviceCredential: true — Phase 4's "device passcode fallback where
  // appropriate": if biometry itself is unavailable/fails, iOS offers the
  // device passcode as a fallback rather than dead-ending the user.
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
  const result = await provider.checkBiometry();
  const kind = kindFromType(result.biometryType);
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
  try {
    await provider.authenticate(reason);
    return { ok: true };
  } catch (error) {
    if (error instanceof BiometryError) {
      return { ok: false, code: error.code, message: error.message };
    }
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
