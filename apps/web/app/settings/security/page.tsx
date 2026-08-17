"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { createPasskey, passkeyWasCancelled, passkeysSupported } from "@/components/passkey-client";
type Device = {
  id: string;
  device_name: string;
  platform: string;
  user_agent: string;
  last_used_at: string;
  current: boolean;
};
type Passkey = {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
};
export default function Security() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  const [passkeyAvailable, setPasskeyAvailable] = useState(false);
  useEffect(() => {
    api.devices().then(setDevices).catch(() => setError("Could not load your signed-in devices."));
    api.passkeys().then(setPasskeys).catch(() => setError("Could not load your passkeys."));
    setPasskeyAvailable(passkeysSupported());
  }, []);
  async function addPasskey() {
    setPasskeyBusy(true);
    setError("");
    try {
      const options = await api.passkeyRegistrationOptions();
      const credential = await createPasskey(options.options_json);
      const created = await api.passkeyRegistrationVerify(JSON.stringify(credential));
      setPasskeys((value) => [...value, created]);
      setMessage("Faster sign-in is ready on this account.");
    } catch (cause) {
      setError(
        passkeyWasCancelled(cause)
          ? "Passkey setup was cancelled."
          : cause instanceof ApiError
            ? cause.message
            : "Could not set up faster sign-in.",
      );
    } finally {
      setPasskeyBusy(false);
    }
  }
  async function renamePasskey(passkey: Passkey) {
    const label = window.prompt("Name this passkey", passkey.label)?.trim();
    if (!label || label === passkey.label) return;
    try {
      const updated = await api.renamePasskey(passkey.id, label);
      setPasskeys((value) => value.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not rename this passkey.");
    }
  }
  async function revokePasskey(passkey: Passkey) {
    if (!window.confirm(`Remove ${passkey.label}? You can still sign in with your password.`)) return;
    try {
      await api.revokePasskey(passkey.id);
      setPasskeys((value) => value.filter((item) => item.id !== passkey.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove this passkey.");
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
  return (
    <SettingsPage title="Security">
      <section className="card details">
        <h2>Faster sign-in</h2>
        <p className="muted">
          Use Face ID, Touch ID, Windows Hello or your device security to sign in without typing your password.
        </p>
        {passkeyAvailable && (
          <button className="secondary" disabled={passkeyBusy} onClick={() => void addPasskey()}>
            {passkeyBusy ? "Setting up..." : "Set up faster sign-in"}
          </button>
        )}
        {passkeys.map((passkey) => (
          <div className="session" key={passkey.id}>
            <div>
              <strong>{passkey.label}</strong>
              <small>
                Added {new Date(passkey.created_at).toLocaleDateString()}
                {passkey.last_used_at && ` · Last used ${new Date(passkey.last_used_at).toLocaleDateString()}`}
              </small>
            </div>
            <span className="settings-inline-actions">
              <button className="tertiary" onClick={() => void renamePasskey(passkey)}>Rename</button>
              <button className="secondary" onClick={() => void revokePasskey(passkey)}>Remove</button>
            </span>
          </div>
        ))}
      </section>
      <section className="card details">
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
