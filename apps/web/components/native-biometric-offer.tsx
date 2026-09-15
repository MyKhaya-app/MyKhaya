"use client";

import { useEffect, useState } from "react";
import {
  authenticateWithBiometrics,
  getBiometricCapability,
  isBiometricCancellation,
  type BiometricCapability,
} from "./native-biometric";
import {
  declineBiometricSignIn,
  getBiometricPreference,
  setBiometricSignInEnabled,
} from "./native-biometric-preference";
import { consumeBiometricOfferAfterLogin } from "./native-auth";
import { isNativeShell } from "./native-runtime";

/** One-shot offer shown after a successful native password login. It is
 * intentionally separate from the Settings control: a declined offer is
 * remembered, while Settings remains the durable way to enable it later.
 *
 * `onSettled` is an optional completion signal — called exactly once, either
 * immediately when this offer determines it has nothing to show, or once
 * the user has acted (enabled or declined) — used by AppShell to sequence
 * this ahead of NotificationPermissionPrompt so the two one-shot native
 * onboarding overlays never compete for the screen at once. Defaults to a
 * no-op so every other/existing usage is unaffected. */
export function NativeBiometricOffer({ onSettled }: { onSettled?: () => void } = {}) {
  const [capability, setCapability] = useState<BiometricCapability | null>(null);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isNativeShell() || !consumeBiometricOfferAfterLogin()) {
      onSettled?.();
      return;
    }
    let cancelled = false;
    void Promise.all([getBiometricCapability(), getBiometricPreference()]).then(([result, preference]) => {
      console.info("[BIOMETRIC DEBUG]", "offer_preference_result", {
        available: result.available,
        type: result.kind,
        preference,
      });
      if (cancelled) return;
      if (result.available && preference === "undecided") {
        setCapability(result);
        setVisible(true);
      } else {
        onSettled?.();
      }
    });
    return () => { cancelled = true; };
  }, []);

  async function enable() {
    if (!capability) return;
    setBusy(true);
    setError("");
    const result = await authenticateWithBiometrics(`Enable ${capability.label} for MyKhaya`);
    if (!result.ok) {
      if (!isBiometricCancellation(result)) setError(`Could not confirm ${capability.label}. Please try again.`);
      setBusy(false);
      return;
    }
    await setBiometricSignInEnabled(true);
    setVisible(false);
    setBusy(false);
    onSettled?.();
  }

  async function notNow() {
    setBusy(true);
    await declineBiometricSignIn();
    setVisible(false);
    setBusy(false);
    onSettled?.();
  }

  if (!visible || !capability) return null;
  return (
    <section className="card details" role="dialog" aria-labelledby="native-biometric-offer-title">
      <h2 id="native-biometric-offer-title">Enable {capability.label} for MyKhaya?</h2>
      <p className="muted">Use {capability.label} to securely unlock your saved MyKhaya session.</p>
      {error && <p className="notice error" role="alert">{error}</p>}
      <span className="settings-inline-actions">
        <button disabled={busy} onClick={() => void enable()}>Enable {capability.label}</button>
        <button className="tertiary" disabled={busy} onClick={() => void notNow()}>Not now</button>
      </span>
    </section>
  );
}
