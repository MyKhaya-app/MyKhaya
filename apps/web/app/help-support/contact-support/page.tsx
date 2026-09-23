"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, ImagePlus, Send } from "lucide-react";
import { api, type SupportTicketResponse } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { useBuildInfo } from "@/components/app-version";
import { useNotificationPermission } from "@/components/use-notification-permission";
import { collectSupportDiagnostics } from "@/components/support-diagnostics";

const CATEGORY_OPTIONS = [
  { value: "account", label: "Account" },
  { value: "home", label: "Family/Home" },
  { value: "calendar", label: "Calendar" },
  { value: "notifications", label: "Notifications" },
  { value: "other", label: "Subscription" },
  { value: "other", label: "Technical problem" },
  { value: "other", label: "Something else" },
] as const;

// Phase 2C ships the Help & Support hub only — the real support-request
// flow (subject/category/message form, POST /api/v1/support/tickets) is
// Phase 2E's work. This is a deliberately inert placeholder, not a mailto:
// link or any other stand-in submission path. See
// apps/web/app/help-support/page.tsx's "Contact support" quick action/card,
// which link here.
export default function ContactSupport() {
  const { activeHomeId } = useActiveHome();
  const build = useBuildInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const [supportEnabled, setSupportEnabled] = useState<boolean | null>(null);
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("account");
  const [message, setMessage] = useState("");
  const [screenshot, setScreenshot] = useState<File | null>(null);
  const [includeDiagnostics, setIncludeDiagnostics] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [success, setSuccess] = useState<SupportTicketResponse | null>(null);
  const platform = nativePlatform();
  const source = useMemo(() => ({
    appVersion: build?.version ?? null,
    buildNumber: build?.build_time ?? null,
    platform,
    runtime: isNativeShell() ? ("native" as const) : ("web" as const),
    notificationPermission,
    online: typeof navigator === "undefined" ? null : navigator.onLine,
  }), [build?.version, build?.build_time, notificationPermission, platform]);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload: { support_enabled?: boolean } | null) => setSupportEnabled(payload?.support_enabled === true))
      .catch(() => setSupportEnabled(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !activeHomeId || supportEnabled !== true) return;
    setError(null);
    setWarning(null);
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setError("You appear to be offline. Reconnect and try again.");
      return;
    }
    if (!subject.trim() || !message.trim()) {
      setError("Add a subject and message before sending.");
      return;
    }
    setBusy(true);
    let diagnostics = null;
    if (includeDiagnostics) {
      try { diagnostics = collectSupportDiagnostics(source); }
      catch { setWarning("Your request will be sent without diagnostics."); }
    }
    try {
      const ticket = await api.createSupportTicket({
        type: "support",
        subject: subject.trim(),
        description: message.trim(),
        source: platform === "ios" || platform === "android" ? platform : "web",
        app_area: category,
        group_id: activeHomeId,
        diagnostics,
      });
      if (screenshot) {
        try { await api.uploadSupportAttachment(ticket.id, screenshot); }
        catch { setWarning("Your request was sent, but the screenshot could not be attached."); }
      }
      setSuccess(ticket);
    } catch (submissionError) {
      const raw = submissionError instanceof Error ? submissionError.message : "";
      setError(/duplicate|constraint|unique key|traceback|sql/i.test(raw) || !raw ? "Couldn’t send your request. Please try again." : raw);
    } finally { setBusy(false); }
  }

  if (supportEnabled === false) return <SettingsPage title="Contact support" description="Get help from the MyKhaya support team."><section className="card details" aria-live="polite"><h2>Support unavailable</h2><p className="muted">Support requests are temporarily unavailable. Please check Service Status and try again later.</p></section></SettingsPage>;
  if (success) return <SettingsPage title="Contact support" description="Get help from the MyKhaya support team."><section className="card details support-success" aria-live="polite"><CheckCircle2 aria-hidden="true" /><h2>We&apos;ve received your request.</h2><p className="support-reference">Reference: <strong>{success.reference}</strong></p>{warning && <p className="field-error">{warning}</p>}<a className="button" href="/help-support">Back to Help &amp; Support</a></section></SettingsPage>;

  return <SettingsPage title="Contact support" description="Get help from the MyKhaya support team."><form className="card details support-form" onSubmit={submit} noValidate>
    {error && <p className="notice error" role="alert"><AlertCircle size={16} aria-hidden="true" />{error}</p>}
    {warning && <p className="notice" role="status">{warning}</p>}
    <label>Subject<input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={200} required /></label>
    <label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}>{CATEGORY_OPTIONS.map((option) => <option key={`${option.label}-${option.value}`} value={option.value}>{option.label}</option>)}</select></label>
    <label>Message<textarea value={message} onChange={(event) => setMessage(event.target.value)} maxLength={4000} rows={7} required /></label>
    <label className="support-file-field"><span><ImagePlus size={16} aria-hidden="true" /> Screenshot (optional)</span><input type="file" accept="image/*" onChange={(event) => setScreenshot(event.target.files?.[0] ?? null)} />{screenshot && <small>{screenshot.name}</small>}</label>
    <small>Your screenshot may include information currently visible on your screen.</small>
    <label className="check-row"><input type="checkbox" checked={includeDiagnostics} onChange={(event) => setIncludeDiagnostics(event.target.checked)} />Include diagnostics</label>
    <button className="button" type="submit" disabled={busy || supportEnabled !== true || !activeHomeId}><Send size={16} aria-hidden="true" /> {busy ? "Sending…" : "Send request"}</button>
  </form></SettingsPage>;
}

export function LegacyContactSupport() {
  return (
    <SettingsPage title="Contact support" description="Get help from the MyKhaya support team.">
      <section className="card details">
        <p className="quiet-state">Coming soon</p>
        <p className="muted">In-app support requests aren&apos;t available yet.</p>
      </section>
    </SettingsPage>
  );
}
