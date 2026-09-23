"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CheckCircle2, CircleAlert, HelpCircle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useBuildInfo } from "@/components/app-version";
import { useNotificationPermission } from "@/components/use-notification-permission";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { collectSupportDiagnostics, runSupportDiagnosticChecks, type DiagnosticCheck } from "@/components/support-diagnostics";

// Phase 2C ships the Help & Support hub's compact "Helpful diagnostics"
// summary only (see apps/web/app/help-support/page.tsx) — the full
// multi-check "Run diagnostics" screen (Service connection, Internet
// connection, Notifications, App version, Device permissions, Background
// refresh, Account sync, "Share diagnostics with support") is Phase 2F's
// work. This is a deliberately inert placeholder.
function relativeTime(value: Date | null): string {
  if (!value) return "Not checked yet";
  return `Last checked ${Math.max(0, Math.round((Date.now() - value.getTime()) / 1000))} seconds ago`;
}

export default function RunDiagnostics() {
  const build = useBuildInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const [checks, setChecks] = useState<DiagnosticCheck[]>([]);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [running, setRunning] = useState(false);
  const [supportEnabled, setSupportEnabled] = useState<boolean | null>(null);
  const platform = nativePlatform();
  const source = useMemo(() => ({
    appVersion: build?.version ?? null,
    buildNumber: build?.build_time ?? null,
    platform,
    runtime: isNativeShell() ? ("native" as const) : ("web" as const),
    notificationPermission,
    online: typeof navigator === "undefined" ? null : navigator.onLine,
  }), [build?.version, build?.build_time, notificationPermission, platform]);
  const run = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setChecks([]);
    const result = await runSupportDiagnosticChecks({
      source,
      checkService: async () => (await fetch("/api/v1/health/live", { cache: "no-store" })).ok,
      checkAccount: async () => { await api.me(); return true; },
    });
    setChecks(result);
    setLastChecked(new Date());
    setRunning(false);
  }, [running, source]);
  useEffect(() => { void run(); }, [run]);
  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload: { support_enabled?: boolean } | null) => setSupportEnabled(payload?.support_enabled === true))
      .catch(() => setSupportEnabled(false));
  }, []);
  const diagnosticsReady = collectSupportDiagnostics(source);
  return <SettingsPage title="Run diagnostics" description="Check your device and app settings for common issues." backLink={{ href: "/help-support", label: "Help & Support" }}>
    <div className="diagnostics-page">
      <div className="diagnostics-toolbar"><p className="muted" aria-live="polite">{running ? "Checking your app and connection…" : relativeTime(lastChecked)}</p><button className="secondary" type="button" onClick={() => void run()} disabled={running}><RefreshCw size={16} aria-hidden="true" /> Run again</button></div>
      <section className="card details diagnostics-list" aria-label="Diagnostic checks">
        {running && checks.length === 0 ? <p role="status">Checking…</p> : checks.map((check) => <div className="diagnostic-row" key={check.id}><span className="diagnostic-icon" aria-hidden="true">{check.status === "passed" || check.status === "good" || check.status === "enabled" ? <CheckCircle2 /> : check.status === "deferred" || check.status === "unavailable" ? <HelpCircle /> : <CircleAlert />}</span><span><strong>{check.label}</strong><small>{check.detail}</small></span><b>{check.status === "passed" ? "Passed" : check.status === "good" ? "Good" : check.status === "enabled" ? "Enabled" : check.status === "deferred" ? "Deferred" : check.status === "unavailable" ? "Unavailable" : check.status === "offline" ? "Offline" : check.status === "problem" ? "Problem detected" : "Unknown"}</b></div>)}
      </section>
      <section className="card details diagnostics-share"><Activity size={20} aria-hidden="true" /><div><h2>Share diagnostics with support</h2><p className="muted">Only share these technical checks when you choose to report an issue.</p>{supportEnabled ? <Link className="button" href="/help-support/report-bug?diagnostics=1">Report a bug with diagnostics</Link> : <p className="muted">Support sharing is unavailable right now.</p>}</div></section>
      <p className="visually-hidden">{Object.keys(diagnosticsReady).length} safe diagnostic values collected locally.</p>
    </div>
  </SettingsPage>;
}
