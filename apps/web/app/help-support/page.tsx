"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Bell, Bug, MessageCircle, Smartphone, Wifi } from "lucide-react";
import { App } from "@capacitor/app";
import { SettingsPage } from "@/components/settings-page";
import { openExternalUrl } from "@/components/open-external-url";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { useBuildInfo } from "@/components/app-version";
import { useNotificationPermission } from "@/components/use-notification-permission";
import type { ServiceState } from "@/components/platform-types";
import {
  connectivityLabel,
  hubStatusMessage,
  notificationPermissionLabel,
  platformLabel,
} from "./help-support-logic";

// The service status URL is a canonical, PCC-managed operational setting
// (mykhaya.platform_settings.SETTINGS_SCHEMA's service_status_url) — never
// hardcoded here. Only the consumer-safe allow-listed endpoint is used,
// never the privileged /platform/settings surface.
function useServiceStatusUrl(): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) =>
        response.ok ? (response.json() as Promise<{ service_status_url: string | null }>) : null,
      )
      .then((payload) => setUrl(payload?.service_status_url ?? null))
      .catch(() => setUrl(null));
  }, []);

  return url;
}

type StatusSummary = { overall: ServiceState; overall_message: string };

// Compact summary only — the full service list and incident history stay on
// the dedicated Service Status experience (linked below), not duplicated
// here. Same public, curated /status endpoint that page already uses; never
// internal health (DB/SMTP/Stripe/worker), never infrastructure detail.
function useStatusSummary(): { summary: StatusSummary | null; failed: boolean } {
  const [summary, setSummary] = useState<StatusSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch("/api/v1/status", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("status unavailable");
        return response.json() as Promise<StatusSummary>;
      })
      .then(setSummary)
      .catch(() => setFailed(true));
  }, []);

  return { summary, failed };
}

type NativeAppInfo = { version: string; build: string };

// Mirrors app/about/page.tsx's identical hook — kept local rather than
// shared, same reasoning as help-support-logic.ts's notification-permission
// label map (five lines isn't worth a shared module yet, and this phase
// deliberately touches nothing in About). Never a fake value while loading
// or unavailable.
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

function useOnlineStatus(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    if (typeof navigator === "undefined" || !("onLine" in navigator)) return;
    setOnline(navigator.onLine);
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  return online;
}

function ServiceStatusBanner({ serviceStatusUrl }: { serviceStatusUrl: string | null }) {
  const { summary, failed } = useStatusSummary();

  return (
    <section className="card details help-status-card">
      <h2>Service status</h2>
      {failed ? (
        <p className="quiet-state">Status information is temporarily unavailable.</p>
      ) : summary ? (
        <p className={`help-status-line help-status-${summary.overall}`}>
          <span className="help-status-dot" aria-hidden="true" />
          {hubStatusMessage(summary.overall, summary.overall_message)}
        </p>
      ) : (
        <p className="quiet-state" role="status">
          Checking…
        </p>
      )}
      {serviceStatusUrl ? (
        <a
          className="help-status-link"
          href={serviceStatusUrl}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => {
            event.preventDefault();
            void openExternalUrl(serviceStatusUrl);
          }}
        >
          View current platform status ›
        </a>
      ) : (
        <span className="help-status-link help-status-link-disabled">
          Platform status page not available right now
        </span>
      )}
    </section>
  );
}

function DiagnosticsSummary() {
  const build = useBuildInfo();
  const nativeInfo = useNativeAppInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const online = useOnlineStatus();

  const appVersion = isNativeShell()
    ? nativeInfo
      ? `${nativeInfo.version} (Build ${nativeInfo.build})`
      : null
    : build
      ? build.version
      : null;

  return (
    <section className="card details help-diagnostics-card">
      <h2>Helpful diagnostics</h2>
      <p className="muted">A quick look at your app and connection — useful if you contact us.</p>
      <dl className="help-diagnostics-list">
        <div>
          <dt>
            <Bug size={14} aria-hidden="true" />
            App version
          </dt>
          <dd>{appVersion ?? "Unavailable"}</dd>
        </div>
        <div>
          <dt>
            <Smartphone size={14} aria-hidden="true" />
            Platform
          </dt>
          <dd>{platformLabel(nativePlatform())}</dd>
        </div>
        <div>
          <dt>
            <Bell size={14} aria-hidden="true" />
            Notifications
          </dt>
          <dd>{notificationPermissionLabel(notificationPermission)}</dd>
        </div>
        <div>
          <dt>
            <Wifi size={14} aria-hidden="true" />
            Connectivity
          </dt>
          <dd>{connectivityLabel(online)}</dd>
        </div>
      </dl>
    </section>
  );
}

export default function HelpSupport() {
  const serviceStatusUrl = useServiceStatusUrl();

  return (
    <SettingsPage
      title="Help & Support"
      description="Get help, report issues, and check your app health."
    >
      <div className="quick-actions help-quick-actions">
        <div className="quick-actions-row quick-actions-row-3">
          <Link className="quick-action" href="/help-support/report-bug">
            <Bug size={20} aria-hidden="true" />
            Report a bug
          </Link>
          <Link className="quick-action" href="/help-support/contact-support">
            <MessageCircle size={20} aria-hidden="true" />
            Contact support
          </Link>
          <Link className="quick-action" href="/help-support/diagnostics">
            <Activity size={20} aria-hidden="true" />
            Run diagnostics
          </Link>
        </div>
      </div>

      <div className="card-stack">
        <ServiceStatusBanner serviceStatusUrl={serviceStatusUrl} />

        <Link className="card" href="/help-support/report-bug">
          <div>
            <h2>Report a bug</h2>
            <p>Send us issue details, screenshots and app diagnostics to help us fix problems faster.</p>
          </div>
          <span aria-hidden="true">›</span>
        </Link>

        <Link className="card" href="/help-support/contact-support">
          <div>
            <h2>Contact support</h2>
            <p>Get help from the MyKhaya support team.</p>
          </div>
          <span aria-hidden="true">›</span>
        </Link>

        <section className="card details">
          <h2>Knowledge base</h2>
          <p className="muted">Find answers and guidance for using MyKhaya.</p>
          <p className="quiet-state">Coming soon</p>
        </section>

        <DiagnosticsSummary />
      </div>
    </SettingsPage>
  );
}
