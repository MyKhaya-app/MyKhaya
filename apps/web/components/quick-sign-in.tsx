"use client";

import { useEffect, useState } from "react";
import { ScanFace } from "lucide-react";
import {
  authenticateWithBiometrics,
  biometricLabel,
  deviceNoun,
  getBiometricCapability,
  isBiometricCancellation,
  type BiometricCapability,
} from "./native-biometric";
import {
  isBiometricSignInEnabled,
  setBiometricSignInEnabled,
} from "./native-biometric-preference";

// A native Capacitor plugin call whose native implementation isn't actually
// linked into the compiled binary can reject immediately — or, observed on
// a real device, simply never resolve at all. Nothing in this component
// (or the underlying plugin wrappers) can distinguish "slow" from "will
// never come back," so every native call this card makes races against a
// generous fixed timeout and falls back to a safe, inert value rather than
// leaving the UI waiting forever. This never fires for a plugin that's
// actually linked and responding normally.
const NATIVE_CALL_TIMEOUT_MS = 5000;

function withTimeout<T>(promise: Promise<T>, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), NATIVE_CALL_TIMEOUT_MS);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(fallback);
      },
    );
  });
}

// The native Security page's biometric card — deliberately a distinct
// component from the browser/PWA "Biometric sign-in" (WebAuthn passkey)
// card in app/settings/security/page.tsx, which is rendered instead of
// this one outside the native shell. Never mentions "browser"/"Web/PWA":
// this is native biometric sign-in (Face ID/Touch ID on iOS, BiometricPrompt
// on Android — see components/native-biometric.ts), with no WebAuthn
// involved at all.
//
// Phase 5's "Enabling" requirements: an active valid authenticated session
// is already required simply by this component only ever being reachable
// from within the signed-in Security page; the renewable credential is
// already Keychain-protected by construction (see
// components/keychain-native-session-store.ts) the moment the user is
// signed in at all — enabling Quick Sign-In only ever needs to (1) prove
// the person in front of the device can actually use biometrics right now,
// and (2) record that preference. It never creates a second credential
// store.
export function QuickSignIn() {
  const [capability, setCapability] = useState<BiometricCapability | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Defence-in-depth against a native plugin whose implementation isn't
    // actually linked into the compiled binary (see
    // apps/ios-shell/package.json and apps/android-shell/package.json) —
    // such a bridge call can reject, but has also been observed to simply
    // never resolve, which would otherwise leave `capability`/`enabled`
    // stuck pending forever and this card looking frozen. Racing against a
    // short timeout guarantees this effect always settles into a safe
    // state either way; it never affects a call that resolves normally
    // well within the window.
    const timedOutCapability: BiometricCapability = {
      kind: "none",
      label: biometricLabel("none"),
      available: false,
      lockedOut: false,
      notEnrolled: false,
      reason: "Timed out waiting for a response.",
    };
    withTimeout(getBiometricCapability(), timedOutCapability).then((result) => {
      if (!cancelled) setCapability(result);
    });
    withTimeout(isBiometricSignInEnabled(), false).then((result) => {
      if (!cancelled) setEnabled(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function enable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const label = capability?.label ?? biometricLabel("none");
      const result = await withTimeout(authenticateWithBiometrics(`Enable ${label} for MyKhaya`), {
        ok: false,
        code: "unknown",
        message: "Timed out waiting for a response.",
      });
      if (!result.ok) {
        if (!isBiometricCancellation(result)) {
          setError(`Could not confirm ${label}. Please try again.`);
        }
        return;
      }
      await setBiometricSignInEnabled(true);
      setEnabled(true);
      setMessage(`${label} is ready — you can use it next time you open MyKhaya.`);
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await setBiometricSignInEnabled(false);
      setEnabled(false);
      setMessage(`Quick Sign-In has been turned off on ${deviceNoun()}.`);
    } finally {
      setBusy(false);
    }
  }

  const label = capability?.label ?? biometricLabel("none");
  const device = deviceNoun();

  // Presented with the Security page's card/row structure (see the
  // .security-* rules in app/styles.css) so it sits consistently beside
  // the Passkeys card in the native shell.
  return (
    <section className="card security-card" aria-labelledby="quick-sign-in-heading">
      <div className="security-row security-card-row">
        <span className="security-row-icon" aria-hidden="true">
          <ScanFace size={22} strokeWidth={1.75} />
        </span>
        <div className="security-row-copy">
          <h2 id="quick-sign-in-heading">Quick Sign-In</h2>
          {enabled ? (
            <span className="security-row-detail">{label} is enabled on {device}.</span>
          ) : capability?.available ? (
            <span className="security-row-detail">Use {label} to securely access MyKhaya on {device}.</span>
          ) : capability?.notEnrolled ? (
            <span className="security-row-detail">
              {label} isn&rsquo;t set up on {device} yet — add it in {device}&rsquo;s Settings
              app to use Quick Sign-In here.
            </span>
          ) : capability?.lockedOut ? (
            <span className="security-row-detail">{label} is temporarily unavailable on {device}. Try again shortly.</span>
          ) : capability ? (
            <span className="security-row-detail">Quick Sign-In isn&rsquo;t available on {device} — your password still works as usual.</span>
          ) : null}
        </div>
        {(enabled || capability?.available) && (
          <div className="security-row-aside">
            {enabled ? (
              <button className="secondary security-action" disabled={busy} onClick={() => void disable()}>
                {busy ? "Turning off…" : "Disable"}
              </button>
            ) : (
              <button className="secondary security-action" disabled={busy} onClick={() => void enable()}>
                {busy ? "Confirming…" : `Enable ${label}`}
              </button>
            )}
          </div>
        )}
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
    </section>
  );
}
