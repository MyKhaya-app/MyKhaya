"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
type Device = {
  id: string;
  device_name: string;
  platform: string;
  user_agent: string;
  last_used_at: string;
  current: boolean;
};
export default function Security() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    api.devices().then(setDevices).catch(() => setError("Could not load your signed-in devices."));
  }, []);
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
