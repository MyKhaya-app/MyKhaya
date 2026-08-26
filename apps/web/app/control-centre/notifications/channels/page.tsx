"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";

type ServiceStatus = { configured: boolean; status: string };

type Health = {
  overall: "healthy" | "degraded" | "unhealthy";
  smtp: ServiceStatus;
  push: ServiceStatus;
  deliveries_today: number;
  failures_today: number;
};

function statusBadge(configured: boolean) {
  return (
    <span className={configured ? "badge badge-success" : "badge badge-neutral"}>
      {configured ? "Configured" : "Not configured"}
    </span>
  );
}

/** Channel status only — this reads the same GET /communications/health
 *  endpoint as the existing /communications page rather than duplicating
 *  provider config lookups, and never renders secrets/keys/tokens. Actual
 *  SMTP/push provider configuration stays where it already lives (Email /
 *  Push pages) — this screen links out to those rather than re-implementing
 *  them. */
export default function NotificationChannelsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setHealth(await platformApi.get<Health>("/communications/health"));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Notifications</p>
            <h1>Channels</h1>
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
        {!health ? (
          <p role="status">Loading…</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>Configuration</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Email</td>
                  <td>{statusBadge(health.smtp.configured)}</td>
                  <td>
                    {health.smtp.status} — see <Link href="/control-centre/mail">Email</Link>
                  </td>
                </tr>
                <tr>
                  <td>Push</td>
                  <td>{statusBadge(health.push.configured)}</td>
                  <td>
                    {health.push.status} — see <Link href="/control-centre/push">Push</Link>
                  </td>
                </tr>
                <tr>
                  <td>In-app</td>
                  <td>
                    <span className="badge badge-success">Configured</span>
                  </td>
                  <td>Always available — delivered directly into the household app.</td>
                </tr>
                <tr>
                  <td>Daily briefing</td>
                  <td>
                    <span className="badge badge-success">Configured</span>
                  </td>
                  <td>
                    Wording managed on the <Link href="/control-centre/notifications/briefing">Daily Briefing</Link>{" "}
                    screen; delivered via the channels above.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        <section className="action-panel">
          <h2>Today</h2>
          <div className="metric-grid">
            <article>
              <strong>{health?.deliveries_today ?? "—"}</strong>
              <span>Deliveries today</span>
            </article>
            <article>
              <strong>{health?.failures_today ?? "—"}</strong>
              <span>Failures today</span>
            </article>
          </div>
          {health && health.failures_today > 0 && (
            <p className="notice error">
              See <Link href="/control-centre/notifications/delivery-logs">delivery logs</Link> for
              failure detail.
            </p>
          )}
        </section>
      </main>
    </PlatformShell>
  );
}
