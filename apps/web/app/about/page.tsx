"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { App } from "@capacitor/app";
import { SettingsPage } from "@/components/settings-page";
import { useBuildInfo } from "@/components/app-version";
import { isNativeShell } from "@/components/native-runtime";
import { useNotificationPermission } from "@/components/use-notification-permission";
import { nativePushDiagnostics } from "@/components/native-push";

type NativeAppInfo = {
  version: string;
  build: string;
};

type PushDiagnostics = {
  tokenPresent: boolean;
  registered: boolean;
  lastRegisteredAt: string | null;
};

const PERMISSION_LABELS: Record<string, string> = {
  granted: "Granted",
  denied: "Off",
  not_requested: "Not requested",
  restricted: "Restricted",
  unsupported: "Unsupported",
};

// Only populated inside the native shell, from this session's in-memory
// registration state (populated by reconcileNativePush()/enableNativePush())
// plus a best-effort localStorage timestamp — never a fake/placeholder
// value while unknown, matching useNativeAppInfo()'s own convention above.
function useNativePushDiagnostics(): PushDiagnostics | null {
  const [diagnostics, setDiagnostics] = useState<PushDiagnostics | null>(null);

  useEffect(() => {
    if (!isNativeShell()) return;
    const { tokenPresent, registered } = nativePushDiagnostics();
    let lastRegisteredAt: string | null = null;
    try {
      lastRegisteredAt = window.localStorage.getItem("mykhaya.native.push.last-registered-at");
    } catch {
      lastRegisteredAt = null;
    }
    setDiagnostics({ tokenPresent, registered, lastRegisteredAt });
  }, []);

  return diagnostics;
}

// Only populated inside the Capacitor iOS shell, and only once App.getInfo()
// resolves — omitted entirely (never a fake value) while loading or on
// failure. See docs/architecture/adr/0012-capacitor-ios-shell.md.
function useNativeAppInfo(): NativeAppInfo | null {
  const [info, setInfo] = useState<NativeAppInfo | null>(null);

  useEffect(() => {
    if (!isNativeShell()) return;
    App.getInfo()
      .then((result) => setInfo({ version: result.version, build: result.build }))
      .catch(() => setInfo(null));
  }, []);

  return info;
}

export default function About() {
  const build = useBuildInfo();
  const nativeInfo = useNativeAppInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const pushDiagnostics = useNativePushDiagnostics();

  return (
    <SettingsPage title="About MyKhaya">
      <section className="card details">
        <h2>Version information</h2>
        {isNativeShell() && nativeInfo && (
          <p>
            <strong>iOS app</strong>
            <br />
            {nativeInfo.version} (Build {nativeInfo.build})
          </p>
        )}
        {build && (
          <p>
            <strong>Web</strong>
            <br />
            {build.version}
          </p>
        )}
        {build?.channel === "development" && (
          <p>
            <strong>Environment</strong>
            <br />
            Development
          </p>
        )}
      </section>
      {isNativeShell() && (
        <section className="card details">
          <h2>Notifications</h2>
          <p>
            <strong>Notification permission</strong>
            <br />
            {PERMISSION_LABELS[notificationPermission] ?? "Unknown"}
          </p>
          {pushDiagnostics && (
            <>
              <p>
                <strong>Push registration</strong>
                <br />
                {pushDiagnostics.registered ? "Registered" : "Not registered"}
              </p>
              <p>
                <strong>Push provider</strong>
                <br />
                APNs
              </p>
              <p>
                <strong>Device token</strong>
                <br />
                {pushDiagnostics.tokenPresent ? "Present" : "Not present"}
              </p>
              {pushDiagnostics.lastRegisteredAt && (
                <p>
                  <strong>Last registration</strong>
                  <br />
                  {new Date(Number(pushDiagnostics.lastRegisteredAt)).toLocaleString()}
                </p>
              )}
            </>
          )}
        </section>
      )}
      <div className="settings-list">
        <Link className="card" href="/service-status">
          <div>
            <h2>Service Status</h2>
            <p>Check whether MyKhaya is running normally</p>
          </div>
          <span>›</span>
        </Link>
      </div>
    </SettingsPage>
  );
}
