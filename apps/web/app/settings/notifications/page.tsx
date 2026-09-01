"use client";

import { FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Bell } from "lucide-react";
import type {
  NotificationPreferences,
  PushSubscriptionSummary,
} from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { isStandalone } from "@/components/install-prompt";
import { diagnosePushEnvironment, subscribeToPush, type SubscribeStage } from "@/components/push-subscribe";
import {
  enableNativePush,
  getNativePushDiagnostic,
  nativePushDiagnosticsText,
  nativePushPermission,
  subscribeNativePushDiagnostics,
  type NativePushStatus,
} from "@/components/native-push";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";

const STAGE_LABELS: Record<SubscribeStage, string> = {
  "checking-support": "Checking browser support…",
  "checking-permission": "Checking notification permission…",
  "requesting-permission": "Waiting for permission…",
  "fetching-public-key": "Contacting server…",
  "waiting-for-service-worker": "Waiting for service worker…",
  "checking-existing-subscription": "Checking existing subscription…",
  "creating-push-subscription": "Creating subscription…",
  "registering-with-api": "Saving to your account…",
  complete: "Done.",
};

const BRIEFING_PRESETS = [
  ["07:30", "Morning"],
  ["12:30", "Afternoon"],
  ["18:00", "Evening"],
] as const;

export default function NotificationSettings() {
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [devices, setDevices] = useState<PushSubscriptionSummary[]>([]);
  const [briefingPreset, setBriefingPreset] = useState<string>("custom");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [subscribing, setSubscribing] = useState(false);
  const [subscribeStage, setSubscribeStage] = useState<SubscribeStage | null>(null);
  const [nativeStatus, setNativeStatus] = useState<NativePushStatus>("prompt");
  const nativeDiagnostic = useSyncExternalStore(
    subscribeNativePushDiagnostics,
    getNativePushDiagnostic,
    () => null,
  );
  const [diagnosticsCopied, setDiagnosticsCopied] = useState(false);

  const load = useCallback(async () => {
    const [preferences, subscriptions] = await Promise.all([
      api.notificationPreferences(),
      api.listPushSubscriptions().catch(() => []),
    ]);
    setPrefs(preferences);
    setDevices(subscriptions);
    const preset = BRIEFING_PRESETS.find(([time]) => time === preferences.briefing_time);
    setBriefingPreset(preset ? preset[0] : "custom");
  }, []);

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [load]);

  useEffect(() => {
    if (!isNativeShell()) return;
    nativePushPermission().then((permission) => {
      if (!permission) return;
      setNativeStatus(permission.receive === "granted" ? "granted" : permission.receive === "denied" ? "denied" : "prompt");
    }).catch(() => setNativeStatus("error"));
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!prefs) return;
    setSaving(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const briefingTime =
      briefingPreset === "custom"
        ? (form.get("briefing_time_custom") as string | null) ?? prefs.briefing_time
        : briefingPreset;
    try {
      const updated = await api.updateNotificationPreferences({
        push_enabled: form.get("push_enabled") === "on",
        in_app_enabled: form.get("in_app_enabled") === "on",
        email_enabled: form.get("email_enabled") === "on",
        event_reminders_enabled: form.get("event_reminders_enabled") === "on",
        event_invitations_enabled: form.get("event_invitations_enabled") === "on",
        event_changes_enabled: form.get("event_changes_enabled") === "on",
        household_reminders_enabled: form.get("household_reminders_enabled") === "on",
        daily_briefing_enabled: form.get("daily_briefing_enabled") === "on",
        briefing_time: briefingTime,
        briefing_days: form.get("briefing_days") === "weekdays" ? "weekdays" : "daily",
        empty_day_briefing_enabled: form.get("empty_day_briefing_enabled") === "on",
        lock_screen_preview_level:
          (form.get("lock_screen_preview_level") as NotificationPreferences["lock_screen_preview_level"]) ??
          "title_only",
        quiet_hours_start: (form.get("quiet_hours_start") as string) || null,
        quiet_hours_end: (form.get("quiet_hours_end") as string) || null,
        quiet_hours_critical_only: form.get("quiet_hours_critical_only") === "on",
      });
      setPrefs(updated);
      setMessage("Preferences saved.");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function enableOnThisDevice() {
    setSubscribing(true);
    setSubscribeStage(null);
    setError("");
    setMessage("");
    try {
      const result = await subscribeToPush(setSubscribeStage);
      if (result.ok) {
        setMessage("Notifications enabled on this device.");
        await load();
      } else if (result.reason === "unsupported") {
        setError("This browser does not support push notifications.");
      } else if (result.reason === "permission-denied") {
        setError(
          "Notification permission was denied. Enable notifications for MyKhaya in your device or browser settings, then try again.",
        );
      } else if (result.reason === "not-configured") {
        setError("Push is not configured on this server yet.");
      } else if (result.reason === "timeout" && result.stage === "waiting-for-service-worker") {
        setError(
          "The service worker did not become ready in time. Try closing and reopening the app; if this keeps happening, please let us know.",
        );
      } else if (result.reason === "timeout") {
        setError(`This took too long (stuck at "${STAGE_LABELS[result.stage!]}"). Please try again.`);
      } else {
        setError("Could not enable notifications on this device. Please try again.");
      }
      if (!result.ok && process.env.NODE_ENV !== "production") {
        console.debug("[push] diagnostics:", await diagnosePushEnvironment());
      }
    } catch (cause) {
      console.error("enableOnThisDevice failed:", cause instanceof Error ? cause.message : cause);
      setError("Could not enable notifications on this device. Please try again.");
    } finally {
      setSubscribing(false);
      setSubscribeStage(null);
    }
  }

  async function enableNativeOnThisDevice() {
    setNativeStatus("registering");
    setError("");
    const result = await enableNativePush();
    if (result.ok) {
      setNativeStatus("registered");
      setMessage("Notifications are enabled on this iPhone.");
    } else {
      setNativeStatus(result.status);
      if (result.status === "denied") setError("Notifications are disabled for MyKhaya in iOS Settings.");
      else if (result.status === "error") setError("We couldn't register this iPhone for notifications.");
    }
  }

  async function copyNativeDiagnostics() {
    await navigator.clipboard.writeText(nativePushDiagnosticsText(nativeDiagnostic));
    setDiagnosticsCopied(true);
  }

  async function removeDevice(id: string) {
    await api.deletePushSubscription(id);
    setDevices((current) => current.filter((device) => device.id !== id));
  }

  if (!prefs) {
    return (
      <SettingsPage title="Notifications">
        <p role="status">Loading…</p>
      </SettingsPage>
    );
  }

  return (
    <SettingsPage title="Notifications">
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}

      <section className="card details">
        <h2>This device</h2>
        {isNativeShell() ? (
          <>
            <p>
              {nativeStatus === "registered"
                ? "Notifications are enabled on this iPhone."
                : nativeStatus === "denied"
                  ? "Notifications are disabled for MyKhaya in iOS Settings."
                  : nativeStatus === "registering"
                    ? "Setting up notifications…"
                    : "Notifications are available on this iPhone."}
            </p>
            {nativeStatus !== "denied" && nativeStatus !== "registered" && (
              <button type="button" className="secondary" onClick={enableNativeOnThisDevice} disabled={nativeStatus === "registering"}>
                <Bell size={16} aria-hidden="true" /> Enable notifications
              </button>
            )}
            {isNativeShell() && nativePlatform() === "ios" && (
              <details style={{ marginTop: "0.75rem", fontSize: "0.8rem" }}>
                <summary>Temporary registration diagnostics</summary>
                <pre style={{ whiteSpace: "pre-wrap", margin: "0.5rem 0" }}>
                  {nativePushDiagnosticsText(nativeDiagnostic)}
                </pre>
                <button type="button" className="secondary" onClick={() => void copyNativeDiagnostics()}>
                  {diagnosticsCopied ? "Diagnostics copied" : "Copy diagnostics"}
                </button>
              </details>
            )}
          </>
        ) : !isStandalone() ? (
          <p>Install MyKhaya to your Home Screen first to enable notifications.</p>
        ) : (
          <button type="button" className="secondary" onClick={enableOnThisDevice} disabled={subscribing}>
            <Bell size={16} aria-hidden="true" />{" "}
            {subscribing
              ? (subscribeStage && STAGE_LABELS[subscribeStage]) || "Enabling…"
              : "Enable notifications on this device"}
          </button>
        )}
        {devices.length > 0 && (
          <div className="settings-list" style={{ marginTop: "1rem" }}>
            {devices.map((device) => (
              <div className="session" key={device.id}>
                <div>
                  <strong>{device.device_label ?? "A device"}</strong>
                  <small>
                    {device.disabled_at
                      ? "No longer receiving notifications"
                      : device.last_seen_at
                        ? `Last active ${new Date(device.last_seen_at).toLocaleDateString()}`
                        : "Registered"}
                  </small>
                </div>
                <button className="secondary" onClick={() => removeDevice(device.id)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <form className="card details" onSubmit={save}>
        <h2>Channels</h2>
        <label className="check-row">
          <input type="checkbox" name="push_enabled" defaultChecked={prefs.push_enabled} /> Push notifications
        </label>
        <label className="check-row">
          <input type="checkbox" name="in_app_enabled" defaultChecked={prefs.in_app_enabled} /> In-app notifications
        </label>
        <label className="check-row">
          <input type="checkbox" name="email_enabled" defaultChecked={prefs.email_enabled} /> Also email me
        </label>

        <h2>What to notify me about</h2>
        <label className="check-row">
          <input
            type="checkbox"
            name="event_reminders_enabled"
            defaultChecked={prefs.event_reminders_enabled}
          />{" "}
          Event reminders
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            name="event_invitations_enabled"
            defaultChecked={prefs.event_invitations_enabled}
          />{" "}
          Event invitations
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            name="event_changes_enabled"
            defaultChecked={prefs.event_changes_enabled}
          />{" "}
          Event updates and cancellations
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            name="household_reminders_enabled"
            defaultChecked={prefs.household_reminders_enabled}
          />{" "}
          Household reminders (bins, routines)
        </label>

        <h2>Daily briefing</h2>
        <label className="check-row">
          <input
            type="checkbox"
            name="daily_briefing_enabled"
            defaultChecked={prefs.daily_briefing_enabled}
          />{" "}
          Send me a morning summary
        </label>
        <label>
          Delivery time
          <select value={briefingPreset} onChange={(event) => setBriefingPreset(event.target.value)}>
            {BRIEFING_PRESETS.map(([time, label]) => (
              <option key={time} value={time}>
                {label} ({time})
              </option>
            ))}
            <option value="custom">Custom time</option>
          </select>
        </label>
        {briefingPreset === "custom" && (
          <label>
            Custom time
            <input type="time" name="briefing_time_custom" defaultValue={prefs.briefing_time} />
          </label>
        )}
        <label>
          Days
          <select name="briefing_days" defaultValue={prefs.briefing_days}>
            <option value="daily">Every day</option>
            <option value="weekdays">Weekdays only</option>
          </select>
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            name="empty_day_briefing_enabled"
            defaultChecked={prefs.empty_day_briefing_enabled}
          />{" "}
          Still send a briefing on days with nothing planned
        </label>

        <h2>Privacy</h2>
        <label>
          Lock-screen preview
          <select name="lock_screen_preview_level" defaultValue={prefs.lock_screen_preview_level}>
            <option value="full">Show full details</option>
            <option value="title_only">Title only</option>
            <option value="hidden">Hide content</option>
          </select>
        </label>

        <h2>Quiet hours</h2>
        <label>
          Start
          <input type="time" name="quiet_hours_start" defaultValue={prefs.quiet_hours_start ?? ""} />
        </label>
        <label>
          End
          <input type="time" name="quiet_hours_end" defaultValue={prefs.quiet_hours_end ?? ""} />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            name="quiet_hours_critical_only"
            defaultChecked={prefs.quiet_hours_critical_only}
          />{" "}
          Still allow critical reminders (e.g. medication) during quiet hours
        </label>

        <button disabled={saving}>{saving ? "Saving…" : "Save preferences"}</button>
      </form>
    </SettingsPage>
  );
}
