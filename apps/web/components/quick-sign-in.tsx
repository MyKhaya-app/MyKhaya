"use client";

import { useEffect, useState } from "react";
import {
  authenticateWithBiometrics,
  getBiometricCapability,
  isBiometricCancellation,
  type BiometricCapability,
} from "./native-biometric";
import {
  isBiometricSignInEnabled,
  setBiometricSignInEnabled,
} from "./native-biometric-preference";

// The native iOS Security page's biometric card — deliberately a distinct
// component from the browser/PWA "Biometric sign-in" (WebAuthn passkey)
// card in app/settings/security/page.tsx, which is rendered instead of
// this one outside the native shell. Never mentions "browser"/"Web/PWA":
// this is Face ID/Touch ID via native LocalAuthentication (see
// components/native-biometric.ts), with no WebAuthn involved at all.
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
    getBiometricCapability().then(setCapability).catch(() => setCapability(null));
    isBiometricSignInEnabled().then(setEnabled);
  }, []);

  async function enable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const label = capability?.label ?? "Face ID";
      const result = await authenticateWithBiometrics(`Enable ${label} for MyKhaya`);
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
      setMessage("Quick Sign-In has been turned off on this iPhone.");
    } finally {
      setBusy(false);
    }
  }

  const label = capability?.label ?? "Face ID";

  return (
    <section className="card details">
      <h2>Quick Sign-In</h2>
      {enabled ? (
        <>
          <p className="muted">{label} is enabled on this iPhone.</p>
          <button className="secondary" disabled={busy} onClick={() => void disable()}>
            {busy ? "Turning off…" : "Disable"}
          </button>
        </>
      ) : capability?.available ? (
        <>
          <p className="muted">Use {label} to securely access MyKhaya on this iPhone.</p>
          <button className="secondary" disabled={busy} onClick={() => void enable()}>
            {busy ? "Confirming…" : `Enable ${label}`}
          </button>
        </>
      ) : capability?.notEnrolled ? (
        <p className="muted">
          {label} isn&rsquo;t set up on this iPhone yet — add it in your iPhone&rsquo;s Settings
          app to use Quick Sign-In here.
        </p>
      ) : capability?.lockedOut ? (
        <p className="muted">{label} is temporarily unavailable on this iPhone. Try again shortly.</p>
      ) : capability ? (
        <p className="muted">Quick Sign-In isn&rsquo;t available on this iPhone — your password still works as usual.</p>
      ) : null}
      {message && <p className="notice" role="status">{message}</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
    </section>
  );
}
