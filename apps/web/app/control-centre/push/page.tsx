"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";

type PushSettings = {
  enabled: boolean; subject: string | null; vapid_public_key: string | null;
  private_key_configured: boolean; updated_at: string | null; editable: boolean;
};

type PushState = {
  configured: boolean; managed_by: "environment" | "platform_admin" | "unconfigured";
  public_key: string | null; active_subscriptions: number;
  recent_failures: { id: string; notification_type: string; failed_at: string; safe_failure_message: string | null }[];
  push_settings: PushSettings;
};

export default function PushPage() {
  const [data, setData] = useState<PushState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [recipient, setRecipient] = useState("");

  const load = useCallback(async () => {
    setError("");
    try { setData(await platformApi.get<PushState>("/push")); }
    catch (cause) { setError((cause as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    platformApi.get<{ email: string }>("/auth/me").then((actor) => setRecipient(actor.email)).catch(() => {});
  }, []);

  async function generateKeys(rotate: boolean) {
    if (rotate && !window.confirm(
      "Rotating VAPID keys immediately invalidates every device currently registered for push. " +
      "Everyone will need to re-enable notifications after this. Continue?"
    )) return;
    const reason = window.prompt(
      rotate
        ? "Reason for rotating the VAPID key pair (at least 10 characters):"
        : "Reason for generating the VAPID key pair (at least 10 characters):"
    );
    if (!reason || reason.trim().length < 10) return;
    setGenerating(true); setError(""); setMessage("");
    try {
      const result = await platformApi.post<{ message: string; public_key: string }>(
        "/push/vapid-settings/generate-keys",
        { rotate, reason, confirmed: true },
      );
      setMessage(result.message);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setGenerating(false); }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.put<{ message: string }>("/push/vapid-settings", {
        enabled: form.get("enabled") === "on",
        subject: form.get("subject") || null,
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage(result.message);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSaving(false); }
  }

  async function testPush(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSending(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.post<{ results: { device_label: string | null; result: string }[] }>(
        "/push/test",
        { recipient: form.get("recipient"), reason: form.get("reason"), confirmed: true },
      );
      const accepted = result.results.filter((r) => r.result === "accepted").length;
      setMessage(`${accepted} of ${result.results.length} device(s) accepted the test push.`);
      await load();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSending(false); }
  }

  const settings = data?.push_settings;

  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Delivery operations</p><h1>Push</h1></div><button className="secondary" onClick={load}>Refresh</button></div>
    {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {!data ? <p role="status">Loading push delivery state…</p> : <>
      <div className="overview-grid mail-grid">
        <section className="overview-panel"><div className="diagnostic-heading"><h2>Transport</h2><strong className={`state-label ${data.configured ? "state-healthy" : "state-not-configured"}`}>{data.configured ? "Configured" : "Not configured"}</strong></div><dl><div><dt>Managed by</dt><dd>{titleCase(data.managed_by)}</dd></div><div><dt>VAPID public key</dt><dd>{data.public_key ? <code>{data.public_key}</code> : "Not generated"}</dd></div></dl></section>
        <section className="overview-panel"><h2>Delivery</h2><dl><div><dt>Active registered devices</dt><dd>{data.active_subscriptions}</dd></div><div><dt>Recent failures</dt><dd>{data.recent_failures.length}</dd></div></dl></section>
      </div>

      <section className="action-panel"><h2>VAPID key pair</h2>
        {!settings?.editable && <p className="notice">Managed by the deployment environment (MYKHAYA_VAPID_PUBLIC_KEY). Keys cannot be generated here — edit the server's .env and redeploy.</p>}
        {settings?.editable && (
          <p>
            {settings?.vapid_public_key
              ? <button type="button" className="secondary" onClick={() => generateKeys(true)} disabled={generating}>{generating ? "Rotating…" : "Rotate keys"}</button>
              : <button type="button" onClick={() => generateKeys(false)} disabled={generating}>{generating ? "Generating…" : "Generate VAPID keys"}</button>}
          </p>
        )}
        <small>Rotating replaces the key pair — every device currently registered for push will stop receiving notifications until it re-subscribes.</small>
      </section>

      <section className="action-panel"><h2>Push configuration</h2>
        <form className="smtp-settings-form" onSubmit={saveSettings}>
          <fieldset disabled={!settings?.editable}>
            <label className="check-row"><input type="checkbox" name="enabled" defaultChecked={settings?.enabled} /> Enabled</label>
            <label>Contact address (mailto: or https://)<input name="subject" defaultValue={settings?.subject ?? ""} placeholder="mailto:ops@mykhaya.example" maxLength={320} /></label>
            <label>Reason for change<input name="reason" minLength={10} maxLength={500} required /></label>
            <button disabled={saving}>{saving ? "Saving…" : "Save push settings"}</button>
          </fieldset>
        </form>
        {settings?.updated_at && <small>Last updated {relativeTime(settings.updated_at)}.</small>}
      </section>

      {data.configured && <section className="action-panel"><h2>Send a test push</h2><form className="test-email-form" onSubmit={testPush}><label>Recipient's email (must have a registered device)<input name="recipient" type="email" required value={recipient} onChange={(event) => setRecipient(event.target.value)} /></label><label>Reason for test<input name="reason" minLength={10} maxLength={500} required /></label><button disabled={sending}>{sending ? "Sending…" : "Send test push"}</button></form><small>Sends to every active device registered to that household member. A successful result means the push service accepted the message, not that it was displayed on the device.</small></section>}
      <section><h2>Recent delivery failures</h2>{data.recent_failures.length === 0 ? <p className="quiet-state">No recent push delivery failures.</p> : <div className="table-scroll"><table><thead><tr><th>Type</th><th>Failed</th><th>Safe failure</th></tr></thead><tbody>{data.recent_failures.map((failure) => <tr key={failure.id}><td>{titleCase(failure.notification_type)}</td><td>{readableDate(failure.failed_at)}</td><td>{failure.safe_failure_message ?? "Unavailable"}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </main></PlatformShell>;
}
