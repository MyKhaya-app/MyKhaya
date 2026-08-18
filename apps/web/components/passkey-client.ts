import { startAuthentication, startRegistration } from "@simplewebauthn/browser";

// The user-facing name for this feature is "Biometric sign-in" — WebAuthn/
// passkey terminology is an implementation detail (see the biometric
// sign-in report). This module is the one place browser feature-detection
// happens, so the UI never needs its own copy of these checks.

export function passkeysSupported() {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.get === "function" &&
    typeof navigator.credentials?.create === "function"
  );
}

/** True only when this device has a usable built-in platform authenticator
 *  (Face ID, Touch ID, Windows Hello, Android fingerprint/face/device
 *  security) — the actual capability gate for offering "Enable biometric
 *  sign-in". Falls back to `passkeysSupported()` alone on a browser old
 *  enough not to expose this static method at all (feature-detected, never
 *  assumed) — deliberately not a User-Agent check, which the WebAuthn spec
 *  itself warns is unreliable for capability decisions. */
export async function biometricSignInAvailable(): Promise<boolean> {
  if (!passkeysSupported()) return false;
  if (typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable !== "function") {
    return true;
  }
  try {
    return await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

/** Best-effort *copy only* — never a security or capability decision (that's
 *  biometricSignInAvailable above). Deliberately conservative: falls back to
 *  generic wording rather than guessing wrong, since the actual modality
 *  (Face ID vs Touch ID vs fingerprint) is intentionally not exposed to the
 *  page by WebAuthn — this is a platform guess from the user agent, nothing
 *  more. */
export function biometricLabel(): string {
  if (typeof navigator === "undefined") return "device security";
  const ua = navigator.userAgent;
  if (/iPhone|iPod/.test(ua)) return "Face ID";
  if (/iPad/.test(ua)) return "Face ID or Touch ID";
  if (/Macintosh/.test(ua)) return "Touch ID";
  if (/Windows/.test(ua)) return "Windows Hello";
  if (/Android/.test(ua)) return "biometrics";
  return "device security";
}

export async function createPasskey(optionsJson: string) {
  type RegistrationOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
  return startRegistration({ optionsJSON: JSON.parse(optionsJson) as RegistrationOptions });
}

export async function authenticateWithPasskey(optionsJson: string) {
  type AuthenticationOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];
  return startAuthentication({ optionsJSON: JSON.parse(optionsJson) as AuthenticationOptions });
}

export function passkeyWasCancelled(error: unknown) {
  return error instanceof DOMException && error.name === "NotAllowedError";
}

// ---------------------------------------------------------------------------
// Local "this device previously enrolled" hint — UX only, never an
// authentication boundary. The server-side WebAuthn assertion (verified
// against the stored credential's public key) is the only thing that ever
// actually authenticates anyone; this hint just decides which *screen* to
// show first. Deliberately just a flag + a non-secret display name for the
// "Welcome back" greeting — never a session token, credential, or anything
// that could itself grant access if read by another script on the device.
// ---------------------------------------------------------------------------

const BIOMETRIC_HINT_KEY = "mk_biometric_hint";

interface BiometricHint {
  userId: string;
  displayName: string;
  avatarVersion: string | null;
}

function isBiometricHint(value: unknown): value is BiometricHint {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).userId === "string" &&
    typeof (value as Record<string, unknown>).displayName === "string" &&
    ((value as Record<string, unknown>).avatarVersion === null ||
      typeof (value as Record<string, unknown>).avatarVersion === "string")
  );
}

export function getBiometricHint(): BiometricHint | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(BIOMETRIC_HINT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isBiometricHint(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function setBiometricHint(hint: BiometricHint): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(BIOMETRIC_HINT_KEY, JSON.stringify(hint));
}

export function clearBiometricHint(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(BIOMETRIC_HINT_KEY);
}

// ---------------------------------------------------------------------------
// Which specific server-side passkey row (if any) was enrolled *from this
// device* — separate from the identity hint above (login doesn't need to
// know this; only the Security page's "Face ID is enabled on this device /
// [Disable]" toggle does, so it revokes precisely the credential this
// device created rather than guessing among however many the account has).
// Still just a UX pointer, not a secret — the id alone can't authenticate
// anyone.
// ---------------------------------------------------------------------------

const ENROLLED_PASSKEY_ID_KEY = "mk_biometric_passkey_id";

export function getEnrolledPasskeyId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ENROLLED_PASSKEY_ID_KEY);
}

export function setEnrolledPasskeyId(passkeyId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ENROLLED_PASSKEY_ID_KEY, passkeyId);
}

export function clearEnrolledPasskeyId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ENROLLED_PASSKEY_ID_KEY);
}
