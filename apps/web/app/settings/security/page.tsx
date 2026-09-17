"use client";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "@mykhaya/api-client";
import QRCode from "qrcode";
import type { Passkey } from "@mykhaya/shared-types";
import { SettingsPage } from "@/components/settings-page";
import {
  biometricLabel,
  biometricSignInAvailable,
  clearBiometricHint,
  clearEnrolledPasskeyId,
  createPasskey,
  getEnrolledPasskeyId,
  passkeyWasCancelled,
  setBiometricHint,
  setEnrolledPasskeyId,
} from "@/components/passkey-client";
import { isNativeShell } from "@/components/native-runtime";
import { QuickSignIn } from "@/components/quick-sign-in";

type Device = {
  id: string;
  device_name: string;
  platform: string;
  user_agent: string;
  last_used_at: string;
  current: boolean;
};

type MfaStatus = {
  required: boolean;
  allowed_methods: ("totp" | "email")[];
  email_available: boolean;
  totp_enabled: boolean;
  can_disable_totp: boolean;
};

type TotpSetup = { provisioning_uri: string; manual_key: string };

export default function Security() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [biometricBusy, setBiometricBusy] = useState(false);
  // Undecided while the async platform check runs — deliberately not "no",
  // so the Enable button doesn't flash in and immediately vanish on a
  // device that does have Face ID/Touch ID/Windows Hello.
  const [biometricAvailable, setBiometricAvailable] = useState<boolean | null>(null);
  const [labelText, setLabelText] = useState("biometrics");
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [totpSetup, setTotpSetup] = useState<TotpSetup | null>(null);
  const [totpQr, setTotpQr] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [mfaBusy, setMfaBusy] = useState(false);

  const native = isNativeShell();

  useEffect(() => {
    api.devices().then(setDevices).catch(() => setError("Could not load your signed-in devices."));
    api.passkeys().then(setPasskeys).catch(() => setError("Could not load your biometric sign-in status."));
    // Browser WebAuthn feature-detection only — the native shell renders
    // QuickSignIn (native Face ID/Touch ID, no WebAuthn involved) instead
    // of this passkey card below, and must never invoke
    // navigator.credentials/PublicKeyCredential at all: that API has been
    // observed to hang inside the Capacitor WKWebView, which is exactly
    // the "Quick Sign-In freezes the app" defect this guard fixes.
    if (native) return;
    api.mfaStatus().then(setMfaStatus).catch(() => setError("Could not load your browser MFA status."));
    biometricSignInAvailable().then(setBiometricAvailable);
    setLabelText(biometricLabel());
  }, [native]);

  async function setupAuthenticator() {
    setMfaBusy(true);
    setError("");
    try {
      const setup = await api.totpSetup();
      setTotpSetup(setup);
      setTotpQr(await QRCode.toDataURL(setup.provisioning_uri, { margin: 1, width: 220 }));
    } catch {
      setError("Could not start authenticator setup. Please try again.");
    } finally {
      setMfaBusy(false);
    }
  }

  async function confirmAuthenticator(event: FormEvent) {
    event.preventDefault();
    setMfaBusy(true);
    setError("");
    try {
      setMfaStatus(await api.totpVerify(totpCode));
      setTotpSetup(null);
      setTotpQr(null);
      setTotpCode("");
      setMessage("Authenticator app is now set up.");
    } catch {
      setError("That authenticator code isn't correct. Please try again.");
    } finally {
      setMfaBusy(false);
    }
  }

  async function disableAuthenticator() {
    if (!window.confirm("Turn off your authenticator app?")) return;
    setMfaBusy(true);
    setError("");
    try {
      await api.removeTotp();
      setMfaStatus((value) => value && { ...value, totp_enabled: false, can_disable_totp: false });
      setMessage("Authenticator app has been turned off.");
    } catch {
      setError("Could not turn off authenticator app. Please try again.");
    } finally {
      setMfaBusy(false);
    }
  }

  // "Enabled on this device" — precisely the credential this browser
  // created (see getEnrolledPasskeyId), not just "the account has some
  // passkey somewhere". A credential id from a different device never
  // counts here, even though the account-level list below still shows it.
  const enrolledId = getEnrolledPasskeyId();
  const thisDevicePasskey = passkeys.find((row) => row.id === enrolledId) ?? null;

  async function enableBiometricSignIn() {
    setBiometricBusy(true);
    setError("");
    try {
      const options = await api.passkeyRegistrationOptions();
      const credential = await createPasskey(options.options_json);
      const created = await api.passkeyRegistrationVerify(JSON.stringify(credential));
      setPasskeys((value) => [...value, created]);
      setEnrolledPasskeyId(created.id);
      const me = await api.me();
      setBiometricHint({
        userId: me.id,
        displayName: me.display_name,
        avatarVersion: me.avatar_version,
      });
      setMessage(`${labelText} is ready — you can use it next time you sign in.`);
    } catch (cause) {
      setError(
        passkeyWasCancelled(cause)
          ? "Biometric sign-in setup was cancelled."
          : cause instanceof ApiError
            ? cause.message
            : "Could not set up biometric sign-in.",
      );
    } finally {
      setBiometricBusy(false);
    }
  }

  async function disableBiometricSignIn() {
    if (!thisDevicePasskey) return;
    if (
      !window.confirm(
        `Turn off biometric sign-in on this device? You can still sign in with your password.`,
      )
    )
      return;
    setBiometricBusy(true);
    setError("");
    try {
      await api.revokePasskey(thisDevicePasskey.id);
      setPasskeys((value) => value.filter((item) => item.id !== thisDevicePasskey.id));
      clearEnrolledPasskeyId();
      clearBiometricHint();
      setMessage("Biometric sign-in has been turned off on this device.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not turn off biometric sign-in.");
    } finally {
      setBiometricBusy(false);
    }
  }

  async function renamePasskey(passkey: Passkey) {
    const label = window.prompt("Name this device", passkey.label)?.trim();
    if (!label || label === passkey.label) return;
    try {
      const updated = await api.renamePasskey(passkey.id, label);
      setPasskeys((value) => value.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not rename this device.");
    }
  }

  async function revokeOtherPasskey(passkey: Passkey) {
    if (
      !window.confirm(`Remove biometric sign-in for "${passkey.label}"? That device will need your password again.`)
    )
      return;
    try {
      await api.revokePasskey(passkey.id);
      setPasskeys((value) => value.filter((item) => item.id !== passkey.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove that device.");
    }
  }

  async function revoke(id: string) {
    setError("");
    try {
      await api.revokeDevice(id);
      setDevices((value) => value.filter((device) => device.id !== id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not sign out that device.");
    }
  }
  async function revokeOthers() {
    setError("");
    try {
      await api.revokeOtherDevices();
      setDevices((value) => value.filter((device) => device.current));
      setMessage("Other devices have been signed out.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not sign out other devices.");
    }
  }

  const otherPasskeys = passkeys.filter((row) => row.id !== enrolledId);
  // The browser/PWA "Biometric sign-in" card below is a WebAuthn passkey
  // feature — meaningless (and, per the native auth architecture, out of
  // scope) inside the Capacitor shell, which gets its own native Face
  // ID/Touch ID card (QuickSignIn) instead. Neither the passkey card's code
  // nor its behaviour changes for an actual browser/PWA user — isNativeShell()
  // is always false there.

  return (
    <SettingsPage title="Security">
      {!native && mfaStatus && (
        <section className="card details" aria-labelledby="browser-mfa-heading">
          <h2 id="browser-mfa-heading">Multi-factor authentication</h2>
          <p className="muted">
            Browser sign-in {mfaStatus.required ? "requires" : "can use"} an additional verification step.
          </p>
          <div className="security-mfa-status">
            <div>
              <strong>Authenticator app</strong>
              <span>{mfaStatus.totp_enabled ? "Set up" : "Not set up"}</span>
            </div>
            {!totpSetup && (mfaStatus.totp_enabled ? (
              mfaStatus.can_disable_totp && <button className="secondary" disabled={mfaBusy} onClick={() => void disableAuthenticator()}>Disable</button>
            ) : (
              <button className="secondary" disabled={mfaBusy} onClick={() => void setupAuthenticator()}>Set up authenticator</button>
            ))}
          </div>
          {mfaStatus.totp_enabled && !mfaStatus.can_disable_totp && (
            <p className="muted">This authenticator app is required by your sign-in policy.</p>
          )}
          {totpSetup && (
            <form onSubmit={(event) => void confirmAuthenticator(event)} className="mfa-method">
              <p>Scan this QR code with your authenticator app, or enter the setup key manually.</p>
              {totpQr && <img src={totpQr} alt="Scan with your authenticator app" className="auth-mfa-qr" />}
              <p>Setup key: <code>{totpSetup.manual_key}</code></p>
              <label htmlFor="security-totp-code">Confirmation code</label>
              <input id="security-totp-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required />
              <button disabled={mfaBusy || totpCode.length !== 6}>{mfaBusy ? "Checking…" : "Confirm setup"}</button>
            </form>
          )}
          <div className="security-mfa-status">
            <div><strong>Email verification</strong><span>{mfaStatus.email_available ? "Available for verification codes" : "Not available"}</span></div>
          </div>
        </section>
      )}
      {native && <QuickSignIn />}
      {!native && (
      <section className="card details">
        <h2>Biometric sign-in</h2>
        {thisDevicePasskey ? (
          <>
            <p className="muted">{labelText} is enabled on this device.</p>
            <button
              className="secondary"
              disabled={biometricBusy}
              onClick={() => void disableBiometricSignIn()}
            >
              {biometricBusy ? "Turning off…" : "Disable"}
            </button>
          </>
        ) : (
          <>
            <p className="muted">
              Use Face ID, Touch ID or your device security to quickly sign in to MyKhaya on this
              device.
            </p>
            {biometricAvailable === false && (
              <p className="muted">
                Biometric sign-in isn't available on this device or browser — your password still
                works as usual.
              </p>
            )}
            {biometricAvailable && (
              <button
                className="secondary"
                disabled={biometricBusy}
                onClick={() => void enableBiometricSignIn()}
              >
                {biometricBusy ? "Setting up…" : `Enable ${labelText}`}
              </button>
            )}
          </>
        )}
        {otherPasskeys.length > 0 && (
          <details>
            <summary>
              {otherPasskeys.length === 1
                ? "1 other device with biometric sign-in"
                : `${otherPasskeys.length} other devices with biometric sign-in`}
            </summary>
            {otherPasskeys.map((passkey) => (
              <div className="session" key={passkey.id}>
                <div>
                  <strong>{passkey.label}</strong>
                  <small>
                    Added {new Date(passkey.created_at).toLocaleDateString()}
                    {passkey.last_used_at &&
                      ` · Last used ${new Date(passkey.last_used_at).toLocaleDateString()}`}
                  </small>
                </div>
                <span className="settings-inline-actions">
                  <button className="tertiary" onClick={() => void renamePasskey(passkey)}>
                    Rename
                  </button>
                  <button className="secondary" onClick={() => void revokeOtherPasskey(passkey)}>
                    Remove
                  </button>
                </span>
              </div>
            ))}
          </details>
        )}
      </section>
      )}
      <section className="card details" id="devices">
        <h2>Signed-in devices</h2>
        {devices.map((device) => (
          <div className="session" key={device.id}>
            <div>
              <strong>{device.device_name}</strong>
              <small>
                {device.current ? "This device · " : ""}
                {device.platform} · Last active {new Date(device.last_used_at).toLocaleDateString()}
              </small>
            </div>
            {!device.current && (
              <button className="secondary" onClick={() => revoke(device.id)}>
                Sign out
              </button>
            )}
          </div>
        ))}
        {devices.some((device) => !device.current) && (
          <button className="tertiary" onClick={revokeOthers}>
            Sign out all other devices
          </button>
        )}
        {message && <p className="notice" role="status">{message}</p>}
        {error && <p className="notice error" role="alert">{error}</p>}
      </section>
    </SettingsPage>
  );
}
