"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { App } from "@capacitor/app";
import { SettingsPage } from "@/components/settings-page";
import { useBuildInfo } from "@/components/app-version";
import { isNativeShell } from "@/components/native-runtime";

type NativeAppInfo = {
  version: string;
  build: string;
};

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
