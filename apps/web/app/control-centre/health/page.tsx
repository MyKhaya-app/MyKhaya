"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime } from "@/components/platform-format";

type HealthCheck = {
  service: string; state: string; explanation: string; last_checked: string;
  last_success: string | null; last_failure: string | null; recommended_action: string | null;
};
type HealthResponse = { overall: string; checked_at: string; services: HealthCheck[] };

export default function HealthPage() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await platformApi.get<HealthResponse>("/health")); }
    catch (cause) { setError((cause as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Live diagnostics</p><h1>Health</h1></div><button className="secondary" onClick={load} disabled={loading}>Run checks</button></div>
    {error && <p className="notice error" role="alert">Health checks are unavailable: {error}</p>}
    {!data ? <p role="status">Running platform checks…</p> : <>
      <section className={`overall-status state-${data.overall.toLowerCase()}`}><div><span className="status-dot" aria-hidden="true" /><div><small>Overall health</small><strong>{data.overall}</strong></div></div><small>Checked {relativeTime(data.checked_at)}</small></section>
      <section className="diagnostic-list" aria-label="Platform health checks">
        {data.services.map((check) => <article key={check.service}>
          <div className="diagnostic-heading"><div><span className={`health-mark state-${check.state.toLowerCase().replace(" ", "-")}`} aria-hidden="true" /><h2>{check.service}</h2></div><strong className={`state-label state-${check.state.toLowerCase().replace(" ", "-")}`}>{check.state}</strong></div>
          <p>{check.explanation}</p>
          <dl>{check.last_success && <div><dt>Last successful check</dt><dd>{relativeTime(check.last_success)}</dd></div>}{check.last_failure && <div><dt>Last failure</dt><dd>{relativeTime(check.last_failure)}</dd></div>}</dl>
          {check.recommended_action && <p className="operator-action"><strong>Operator action:</strong> {check.recommended_action}</p>}
        </article>)}
      </section>
    </>}
  </main></PlatformShell>;
}
