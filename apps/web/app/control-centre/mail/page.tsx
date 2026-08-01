"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";

type MailState = {
  configured: boolean; transport: string | null; sender_identity: string | null;
  queue_depth: number; last_successful_delivery: string | null;
  recent_failures: { id: string; job_type: string; failed_at: string; safe_failure_message: string | null }[];
  managed_by: string;
};

export default function MailPage() {
  const [data, setData] = useState<MailState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const load = useCallback(async () => {
    setError("");
    try { setData(await platformApi.get<MailState>("/mail")); }
    catch (cause) { setError((cause as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function testEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSending(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.post<{ message: string }>("/mail/test", { recipient: form.get("recipient"), reason: form.get("reason"), confirmed: true });
      setMessage(result.message);
      event.currentTarget.reset();
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSending(false); }
  }
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Delivery operations</p><h1>Email</h1></div><button className="secondary" onClick={load}>Refresh</button></div>
    {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {!data ? <p role="status">Loading email delivery state…</p> : <>
      <div className="overview-grid mail-grid"><section className="overview-panel"><div className="diagnostic-heading"><h2>Transport</h2><strong className={`state-label ${data.configured ? "state-healthy" : "state-not-configured"}`}>{data.configured ? "Configured" : "Not configured"}</strong></div><dl><div><dt>Transport type</dt><dd>{data.transport ?? "Not configured"}</dd></div>{data.sender_identity && <div><dt>Sender identity</dt><dd>{data.sender_identity}</dd></div>}<div><dt>Managed by</dt><dd>{titleCase(data.managed_by)}</dd></div></dl></section><section className="overview-panel"><h2>Delivery</h2><dl><div><dt>Queue depth</dt><dd>{data.queue_depth}</dd></div><div><dt>Last successful delivery</dt><dd>{data.last_successful_delivery ? relativeTime(data.last_successful_delivery) : "No successful delivery recorded"}</dd></div><div><dt>Recent failures</dt><dd>{data.recent_failures.length}</dd></div></dl></section></div>
      {data.configured && <section className="action-panel"><h2>Send a test email</h2><form className="test-email-form" onSubmit={testEmail}><label>Recipient<input name="recipient" type="email" required /></label><label>Reason for test<input name="reason" minLength={10} maxLength={500} required /></label><button disabled={sending}>{sending ? "Sending…" : "Send test email"}</button></form><small>The recipient address is not written to the audit log; the action and recipient domain are audited.</small></section>}
      <section><h2>Recent delivery failures</h2>{data.recent_failures.length === 0 ? <p className="quiet-state">No recent email delivery failures.</p> : <div className="table-scroll"><table><thead><tr><th>Type</th><th>Failed</th><th>Safe failure</th></tr></thead><tbody>{data.recent_failures.map((failure) => <tr key={failure.id}><td>{titleCase(failure.job_type)}</td><td>{readableDate(failure.failed_at)}</td><td>{failure.safe_failure_message ?? "Unavailable"}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </main></PlatformShell>;
}
