"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";

type SmtpSettings = {
  enabled: boolean; host: string; port: number;
  connection_security: "none" | "starttls" | "tls";
  auth_enabled: boolean; username: string | null; password_configured: boolean;
  sender_name: string; sender_email: string; reply_to: string | null;
  timeout_seconds: number; updated_at: string | null; editable: boolean;
};

type MailState = {
  configured: boolean; transport: string | null; sender_identity: string | null;
  queue_depth: number; last_successful_delivery: string | null;
  recent_failures: { id: string; job_type: string; failed_at: string; safe_failure_message: string | null }[];
  managed_by: "environment" | "platform_admin" | "unconfigured";
  smtp_settings: SmtpSettings;
};

export default function MailPage() {
  const [data, setData] = useState<MailState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [clearingPassword, setClearingPassword] = useState(false);
  const [recipient, setRecipient] = useState("");

  const load = useCallback(async () => {
    setError("");
    try { setData(await platformApi.get<MailState>("/mail")); }
    catch (cause) { setError((cause as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    platformApi.get<{ email: string }>("/auth/me").then((actor) => setRecipient(actor.email)).catch(() => {});
  }, []);

  async function testEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSending(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.post<{ message: string }>("/mail/test", { recipient: form.get("recipient"), reason: form.get("reason"), confirmed: true });
      setMessage(result.message);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSending(false); }
  }

  async function saveSmtpSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    const connectionSecurity = (form.get("connection_security") as string | null) ?? "starttls";
    const authEnabled = form.get("auth_enabled") === "on";
    const password = (form.get("password") as string | null) ?? "";
    try {
      const result = await platformApi.put<{ message: string }>("/mail/smtp-settings", {
        enabled: form.get("enabled") === "on",
        host: form.get("host"),
        port: Number(form.get("port")),
        connection_security: connectionSecurity,
        auth_enabled: authEnabled,
        username: authEnabled ? form.get("username") : null,
        password: password ? password : null,
        sender_name: form.get("sender_name"),
        sender_email: form.get("sender_email"),
        reply_to: form.get("reply_to") || null,
        timeout_seconds: Number(form.get("timeout_seconds")),
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage(result.message);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSaving(false); }
  }

  async function clearPassword() {
    const reason = window.prompt("Reason for clearing the stored SMTP password (at least 10 characters):");
    if (!reason || reason.trim().length < 10) return;
    setClearingPassword(true); setError(""); setMessage("");
    try {
      const result = await platformApi.post<{ message: string }>("/mail/smtp-settings/clear-password", { reason, confirmed: true });
      setMessage(result.message);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setClearingPassword(false); }
  }

  const settings = data?.smtp_settings;

  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Delivery operations</p><h1>Email</h1></div><button className="secondary" onClick={load}>Refresh</button></div>
    {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {!data ? <p role="status">Loading email delivery state…</p> : <>
      <div className="overview-grid mail-grid"><section className="overview-panel"><div className="diagnostic-heading"><h2>Transport</h2><strong className={`state-label ${data.configured ? "state-healthy" : "state-not-configured"}`}>{data.configured ? "Configured" : "Not configured"}</strong></div><dl><div><dt>Transport type</dt><dd>{data.transport ?? "Not configured"}</dd></div>{data.sender_identity && <div><dt>Sender identity</dt><dd>{data.sender_identity}</dd></div>}<div><dt>Managed by</dt><dd>{titleCase(data.managed_by)}</dd></div></dl></section><section className="overview-panel"><h2>Delivery</h2><dl><div><dt>Queue depth</dt><dd>{data.queue_depth}</dd></div><div><dt>Last successful delivery</dt><dd>{data.last_successful_delivery ? relativeTime(data.last_successful_delivery) : "No successful delivery recorded"}</dd></div><div><dt>Recent failures</dt><dd>{data.recent_failures.length}</dd></div></dl></section></div>

      <section className="action-panel"><h2>SMTP configuration</h2>
        {!settings?.editable && <p className="notice">Managed by the deployment environment (MYKHAYA_SMTP_HOST). These fields cannot be changed here — edit the server's .env and redeploy.</p>}
        <form className="smtp-settings-form" onSubmit={saveSmtpSettings}>
          <fieldset disabled={!settings?.editable}>
          <label className="check-row"><input type="checkbox" name="enabled" defaultChecked={settings?.enabled} /> Enabled</label>
          <label>Host<input name="host" defaultValue={settings?.host} maxLength={255} /></label>
          <label>Port<input name="port" type="number" min={1} max={65535} defaultValue={settings?.port ?? 587} /></label>
          <label>Connection security
            <select name="connection_security" defaultValue={settings?.connection_security ?? "starttls"}>
              <option value="starttls">STARTTLS</option>
              <option value="tls">Implicit TLS</option>
              <option value="none">None (development only)</option>
            </select>
          </label>
          <label className="check-row"><input type="checkbox" name="auth_enabled" defaultChecked={settings?.auth_enabled} /> Authentication enabled</label>
          <label>Username<input name="username" defaultValue={settings?.username ?? ""} maxLength={320} /></label>
          <label>Password
            <input name="password" type="password" autoComplete="new-password" placeholder={settings?.password_configured ? "Leave blank to keep the stored password" : "Enter a password"} maxLength={1000} />
          </label>
          {settings?.password_configured && (
            <p><small>A password is currently stored.</small> <button type="button" className="secondary" onClick={clearPassword} disabled={clearingPassword}>{clearingPassword ? "Clearing…" : "Clear stored password"}</button></p>
          )}
          <label>Sender name<input name="sender_name" defaultValue={settings?.sender_name ?? "MyKhaya"} maxLength={100} /></label>
          <label>Sender email<input name="sender_email" type="email" defaultValue={settings?.sender_email} maxLength={320} /></label>
          <label>Reply-to (optional)<input name="reply_to" type="email" defaultValue={settings?.reply_to ?? ""} maxLength={320} /></label>
          <label>Connection timeout (seconds)<input name="timeout_seconds" type="number" min={1} max={60} defaultValue={settings?.timeout_seconds ?? 10} /></label>
          <label>Reason for change<input name="reason" minLength={10} maxLength={500} required /></label>
          <button disabled={saving}>{saving ? "Saving…" : "Save SMTP settings"}</button>
          </fieldset>
        </form>
        {settings?.updated_at && <small>Last updated {relativeTime(settings.updated_at)}.</small>}
      </section>

      {data.configured && <section className="action-panel"><h2>Send a test email</h2><form className="test-email-form" onSubmit={testEmail}><label>Recipient<input name="recipient" type="email" required value={recipient} onChange={(event) => setRecipient(event.target.value)} /></label><label>Reason for test<input name="reason" minLength={10} maxLength={500} required /></label><button disabled={sending}>{sending ? "Sending…" : "Send test email"}</button></form><small>The recipient address is not written to the audit log; the action and recipient domain are audited. Defaults to your own address — a successful result means the SMTP server accepted the message, not that it reached the recipient's inbox.</small></section>}
      <section><h2>Recent delivery failures</h2>{data.recent_failures.length === 0 ? <p className="quiet-state">No recent email delivery failures.</p> : <div className="table-scroll"><table><thead><tr><th>Type</th><th>Failed</th><th>Safe failure</th></tr></thead><tbody>{data.recent_failures.map((failure) => <tr key={failure.id}><td>{titleCase(failure.job_type)}</td><td>{readableDate(failure.failed_at)}</td><td>{failure.safe_failure_message ?? "Unavailable"}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </main></PlatformShell>;
}
