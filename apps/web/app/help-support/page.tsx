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
import { collectSupportDiagnostics } from "@/components/support-diagnostics";

type StatusSummary = { overall: ServiceState; overall_message: string };

type PublicConfigPayload = {
  service_status_url?: string | null;
  status_overall?: ServiceState;
  status_overall_message?: string;
};

// Both the "View current platform status" link target and the compact
// status summary below come from the one unauthenticated, non-host-gated
// GET /api/v1/config/public — never mykhaya.routers.status's GET /status,
// which is deliberately host-gated to the dedicated status subdomain
// (enforce_status_host) and unreachable from this app's own origin. The
// summary is the exact same overall-severity computation as the full
// Status page (mykhaya.status_aggregation.overall_public_state), just
// surfaced from somewhere this page can actually call — never internal
// health (DB/SMTP/Stripe/worker), never the full service/incident list.
function useServiceStatus(): {
  serviceStatusUrl: string | null;
  summary: StatusSummary | null;
  failed: boolean;
} {
  const [serviceStatusUrl, setServiceStatusUrl] = useState<string | null>(null);
  const [summary, setSummary] = useState<StatusSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("config unavailable");
        return response.json() as Promise<PublicConfigPayload>;
      })
      .then((payload) => {
        setServiceStatusUrl(payload.service_status_url ?? null);
        if (payload.status_overall && payload.status_overall_message) {
          setSummary({
            overall: payload.status_overall,
            overall_message: payload.status_overall_message,
          });
        } else {
          // status_public_enabled is off, or the backend genuinely didn't
          // send a status — never fabricate "All systems operational".
          setFailed(true);
        }
      })
      .catch(() => setFailed(true));
  }, []);

  return { serviceStatusUrl, summary, failed };
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

function ServiceStatusBanner() {
  const { serviceStatusUrl, summary, failed } = useServiceStatus();

  return (
    <section className="card details help-status-card" aria-live="polite">
      <h2>Service status</h2>
      {failed ? (
        // Never "All systems operational" here — an unreachable/disabled
        // status source is a genuinely unknown state, not a good one.
        <p className="quiet-state">Status information is temporarily unavailable.</p>
      ) : summary ? (
        <p className={`help-status-line help-status-${summary.overall}`}>
          <span className="help-status-dot" aria-hidden="true" />
          {hubStatusMessage(summary.overall, summary.overall_message)}
        </p>
      ) : (
        <p className="quiet-state">Checking…</p>
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
  const snapshot = collectSupportDiagnostics({
    appVersion,
    buildNumber: nativeInfo?.build ?? build?.build_time ?? null,
    platform: nativePlatform(),
    runtime: isNativeShell() ? "native" : "web",
    notificationPermission,
    online,
  });

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
          <dd>{snapshot.app_version ?? "Unavailable"}</dd>
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
          <dd>{connectivityLabel(snapshot.network_state === "online" ? true : snapshot.network_state === "offline" ? false : null)}</dd>
        </div>
      </dl>
    </section>
  );
}

export default function HelpSupport() {
  const [supportEnabled, setSupportEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { support_enabled?: boolean } | null) => setSupportEnabled(payload?.support_enabled === true))
      .catch(() => setSupportEnabled(false));
  }, []);

  const reportBugAction = supportEnabled ? (
    <Link className="quick-action" href="/help-support/report-bug">
      <Bug size={20} aria-hidden="true" />
      Report a bug
    </Link>
  ) : (
    <span className="quick-action quick-action-disabled" aria-disabled="true">
      <Bug size={20} aria-hidden="true" />
      Report a bug unavailable
    </span>
  );

  return (
    <SettingsPage
      title="Help & Support"
      description="Get help, report issues, and check your app health."
    >
      <div className="quick-actions help-quick-actions">
        <div className="quick-actions-row quick-actions-row-3">
          {reportBugAction}
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
        <ServiceStatusBanner />

        {supportEnabled ? (
          <Link className="card" href="/help-support/report-bug">
            <div>
              <h2>Report a bug</h2>
              <p>Send us issue details, screenshots and app diagnostics to help us fix problems faster.</p>
            </div>
            <span aria-hidden="true">›</span>
          </Link>
        ) : (
          <section className="card details" aria-live="polite">
            <h2>Report a bug</h2>
            <p className="muted">Bug reporting is temporarily unavailable. Service status is still available below.</p>
          </section>
        )}

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
