"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";

type Template = {
  template_type: string;
  module: string;
  channel: string;
  is_override: boolean;
  enabled: boolean;
  security_critical: boolean;
};

type Health = {
  overall: "healthy" | "degraded" | "unhealthy";
  smtp: { configured: boolean; status: string };
  push: { configured: boolean; status: string };
  failures_today: number;
  deliveries_today: number;
};

/** The PCC Notifications module's landing page — a summary derived entirely
 *  from data the existing registry/communications endpoints already
 *  provide (see GET /notification-templates and GET /communications/health)
 *  rather than any new statistics endpoint, so there's nothing here that
 *  could ever disagree with the Templates/Channels screens reading the
 *  same source. */
export default function NotificationsOverviewPage() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [templateRows, healthRow] = await Promise.all([
        platformApi.get<Template[]>("/notification-templates"),
        platformApi.get<Health>("/communications/health").catch(() => null),
      ]);
      setTemplates(templateRows);
      setHealth(healthRow);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const customised = templates?.filter((row) => row.is_override).length ?? 0;
  const usingDefaults = templates ? templates.length - customised : 0;
  const enabled = templates?.filter((row) => row.enabled).length ?? 0;
  const disabled = templates ? templates.length - enabled : 0;

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Notifications</p>
            <h1>Overview</h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        <NotificationsSubNav />
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {!templates ? (
          <p role="status">Loading…</p>
        ) : (
          <>
            <section>
              <h2>Templates</h2>
              <div className="metric-grid">
                <article>
                  <strong>{templates.length}</strong>
                  <span>Registered types</span>
                </article>
                <article>
                  <strong>{customised}</strong>
                  <span>Customised</span>
                </article>
                <article>
                  <strong>{usingDefaults}</strong>
                  <span>Using built-in default</span>
                </article>
                <article>
                  <strong>{enabled}</strong>
                  <span>Enabled</span>
                </article>
                <article>
                  <strong>{disabled}</strong>
                  <span>Disabled</span>
                </article>
              </div>
            </section>

            {health && (
              <section>
                <h2>Channel health</h2>
                <div className="metric-grid">
                  <article>
                    <strong>{health.smtp.configured ? "🟢" : "⚪"}</strong>
                    <span>Email {health.smtp.configured ? "configured" : "not configured"}</span>
                  </article>
                  <article>
                    <strong>{health.push.configured ? "🟢" : "⚪"}</strong>
                    <span>Push {health.push.configured ? "configured" : "not configured"}</span>
                  </article>
                  <article>
                    <strong>{health.deliveries_today}</strong>
                    <span>Deliveries today</span>
                  </article>
                  <article>
                    <strong>{health.failures_today}</strong>
                    <span>Failures today</span>
                  </article>
                </div>
                {health.failures_today > 0 && (
                  <p className="notice error">
                    {health.failures_today} delivery failure{health.failures_today === 1 ? "" : "s"}{" "}
                    today —{" "}
                    <Link href="/control-centre/notifications/delivery-logs">
                      view delivery logs
                    </Link>
                    .
                  </p>
                )}
              </section>
            )}

            <section>
              <h2>Shortcuts</h2>
              <div className="sheet-actions">
                <Link className="button secondary" href="/control-centre/notifications/templates">
                  Browse templates
                </Link>
                <Link className="button secondary" href="/control-centre/notifications/test-centre">
                  Send a test notification
                </Link>
                <Link className="button secondary" href="/control-centre/notifications/delivery-logs">
                  View delivery failures
                </Link>
              </div>
            </section>
          </>
        )}
      </main>
    </PlatformShell>
  );
}
