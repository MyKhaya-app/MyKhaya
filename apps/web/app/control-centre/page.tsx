"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";

type Overview = {
  users: { total: number; verified: number; unverified: number; active: number; suspended: number };
  homes: { total: number; active: number; suspended: number };
  metrics: { users: number; homes: number; active_sessions: number; failed_jobs: number };
  security: {
    failed_logins_24h: number;
    locked_accounts: number;
    active_administrator_sessions: number;
    administrators_with_mfa: number;
    active_administrators: number;
  };
  operations: { queue_depth: number | null };
  status: { state: string; checked_at: string };
  health: { service: string; state: string }[];
  actions: { severity: string; title: string; detail: string; href: string }[];
  recent_activity: { id: string; action: string; target_type: string | null; created_at: string }[];
  deployment: Record<string, string>;
};

export default function PlatformOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await platformApi.get<Overview>("/overview"));
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { void load(); }, 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <PlatformShell>
      <main className="platform-page platform-overview">
        <div className="platform-heading">
          <div><p>Live operations</p><h1>Overview</h1></div>
          <button className="secondary" onClick={load} disabled={loading}>Refresh</button>
        </div>
        {error && <p className="notice error" role="alert">Live platform state is unavailable: {error}</p>}
        {!data ? <p role="status">Loading platform state…</p> : <>
          <section className={`overall-status state-${data.status.state.toLowerCase().replace(" ", "-")}`}>
            <div><span className="status-dot" aria-hidden="true" /><div><small>Overall system state</small><strong>{data.status.state}</strong></div></div>
            <small>Updated {relativeTime(data.status.checked_at)}</small>
          </section>

          <section className="primary-metrics" aria-label="Core platform metrics">
            {[
              ["Users", data.metrics.users, "/users"],
              ["Homes", data.metrics.homes, "/homes"],
              ["Active sessions", data.metrics.active_sessions, "/security"],
              ["Failed jobs", data.metrics.failed_jobs, "/jobs"],
            ].map(([label, value, href]) => <Link href={String(href)} key={String(label)}><strong>{value}</strong><span>{label}</span></Link>)}
          </section>

          {data.actions.length > 0 && <section className="attention-panel">
            <h2>Action required</h2>
            <div className="attention-list">{data.actions.map((item) => <Link href={item.href} key={item.title} className={`attention-${item.severity}`}><div><strong>{item.title}</strong><p>{item.detail}</p></div><span aria-hidden="true">→</span></Link>)}</div>
          </section>}

          <div className="overview-grid">
            <section className="overview-panel">
              <div className="section-heading"><h2>Platform summary</h2></div>
              <div className="summary-groups">
                <div><h3>Users</h3><dl><div><dt>Active</dt><dd>{data.users.active}</dd></div><div><dt>Suspended</dt><dd>{data.users.suspended}</dd></div><div><dt>Verified</dt><dd>{data.users.verified}</dd></div><div><dt>Unverified</dt><dd>{data.users.unverified}</dd></div></dl></div>
                <div><h3>Homes</h3><dl><div><dt>Active</dt><dd>{data.homes.active}</dd></div><div><dt>Suspended</dt><dd>{data.homes.suspended}</dd></div><div><dt>Queue depth</dt><dd>{data.operations.queue_depth ?? "Unavailable"}</dd></div></dl></div>
              </div>
            </section>

            <section className="overview-panel">
              <div className="section-heading"><h2>Platform health</h2><Link href="/health">Diagnostics</Link></div>
              <div className="health-summary">{data.health.map((item) => <div key={item.service}><span className={`health-mark state-${item.state.toLowerCase().replace(" ", "-")}`} aria-hidden="true" /><span>{item.service}</span><strong>{item.state}</strong></div>)}</div>
            </section>

            <section className="overview-panel">
              <div className="section-heading"><h2>Security</h2><Link href="/security">Security events</Link></div>
              <dl><div><dt>Failed logins, 24 hours</dt><dd>{data.security.failed_logins_24h}</dd></div><div><dt>Locked accounts</dt><dd>{data.security.locked_accounts}</dd></div><div><dt>Active administrator sessions</dt><dd>{data.security.active_administrator_sessions}</dd></div><div><dt>Administrator MFA coverage</dt><dd>{data.security.administrators_with_mfa} of {data.security.active_administrators}</dd></div></dl>
            </section>

            <section className="overview-panel recent-activity">
              <div className="section-heading"><h2>Recent activity</h2><Link href="/audit">Full audit log</Link></div>
              {data.recent_activity.length ? <ol>{data.recent_activity.map((item) => <li key={item.id}><span className="activity-icon" aria-hidden="true">•</span><div><strong>{titleCase(item.action)}</strong><small>{relativeTime(item.created_at)}</small></div></li>)}</ol> : <p className="quiet-state">No significant recent activity.</p>}
            </section>
          </div>

          {Object.keys(data.deployment).length > 0 && <section className="deployment-strip"><h2>Deployment</h2><dl>{Object.entries(data.deployment).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{key === "commit" ? value.slice(0, 12) : key === "build_time" ? readableDate(value) : value}</dd></div>)}</dl></section>}
        </>}
      </main>
    </PlatformShell>
  );
}
