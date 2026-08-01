"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";

type Job = { id: string; job_type: string; state: string; created_at: string; completed_at: string | null; retry_count: number; safe_failure_message: string | null };
type JobsResponse = { summary: Record<string, number | string | null>; items: Job[]; total: number };

export default function JobsPage() {
  const [data, setData] = useState<JobsResponse | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");
  const load = useCallback(async () => {
    setError("");
    try { setData(await platformApi.get<JobsResponse>("/jobs?page_size=50")); }
    catch (cause) { setError((cause as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function retry(job: Job) {
    if (!window.confirm(`Retry ${job.job_type}?`)) return;
    setError(""); setMessage("");
    try {
      await platformApi.post(`/jobs/${job.id}/retry`, { reason, confirmed: true });
      setMessage("The job was returned to the queue and the action was audited.");
      await load();
    } catch (cause) { setError((cause as Error).message); }
  }
  const summary = data?.summary;
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Background processing</p><h1>Jobs & scheduler</h1></div><button className="secondary" onClick={load}>Refresh</button></div>
    {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {!data ? <p role="status">Loading queue and worker state…</p> : <>
      <section className="primary-metrics compact-metrics">
        {["queued", "running", "failed", "completed", "scheduled"].map((key) => <article key={key}><strong>{summary?.[key] ?? (key === "queued" ? "Unavailable" : 0)}</strong><span>{titleCase(key)}</span></article>)}
      </section>
      <section className="overview-panel job-runtime"><h2>Runtime</h2><dl><div><dt>Worker heartbeat</dt><dd>{relativeTime(typeof summary?.worker_heartbeat === "string" ? summary.worker_heartbeat : null)}</dd></div><div><dt>Last successful execution</dt><dd>{relativeTime(typeof summary?.last_successful_execution === "string" ? summary.last_successful_execution : null)}</dd></div></dl></section>
      {data.items.some((job) => job.state === "failed") && <section className="action-panel"><h2>Retry failed jobs</h2><label>Reason for retry<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={500} /></label><small>Retries require recent authentication, confirmation and are recorded in the administrative audit.</small></section>}
      <section><h2>Recent executions</h2>{data.items.length === 0 ? <p className="quiet-state">No jobs have executed yet.</p> : <div className="table-scroll" tabIndex={0}><table><thead><tr><th>Job</th><th>State</th><th>Created</th><th>Attempts</th><th>Failure</th><th>Action</th></tr></thead><tbody>{data.items.map((job) => <tr key={job.id}><td>{titleCase(job.job_type)}</td><td><span className={`state-label state-${job.state}`}>{titleCase(job.state)}</span></td><td>{readableDate(job.created_at)}</td><td>{job.retry_count}</td><td>{job.safe_failure_message ?? "—"}</td><td>{job.state === "failed" ? <button disabled={reason.trim().length < 10} onClick={() => retry(job)}>Retry</button> : "—"}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </main></PlatformShell>;
}
