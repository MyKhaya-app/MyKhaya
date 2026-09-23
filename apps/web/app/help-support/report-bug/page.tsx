"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, ImagePlus, Send } from "lucide-react";
import { api, type SupportTicketResponse } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { useBuildInfo } from "@/components/app-version";
import { useNotificationPermission } from "@/components/use-notification-permission";
import { APP_AREA_OPTIONS } from "@/components/support-logic";
import { SEVERITY_OPTIONS, SEVERITY_TO_PRIORITY, type SeverityValue, buildBugReportDiagnostics } from "../help-support-logic";

// Phase 2C ships the Help & Support hub only — the real submission flow
// (form, screenshot attachment, diagnostics toggle, POST /api/v1/support/tickets)
// is Phase 2D's work. This is a deliberately inert placeholder: no form
// fields, no fake request, nothing that looks functional. See
// apps/web/app/help-support/page.tsx's "Report a bug" quick action/card,
// which link here.
const MAX_SUBJECT = 120;

export default function ReportBug() {
  const { activeHomeId } = useActiveHome();
  const build = useBuildInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const [supportEnabled, setSupportEnabled] = useState<boolean | null>(null);
  const [subject, setSubject] = useState("");
  const [area, setArea] = useState("home");
  const [severity, setSeverity] = useState<SeverityValue>("minor");
  const [description, setDescription] = useState("");
  const [screenshot, setScreenshot] = useState<File | null>(null);
  const [includeDiagnostics, setIncludeDiagnostics] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attachmentWarning, setAttachmentWarning] = useState<string | null>(null);
  const [success, setSuccess] = useState<SupportTicketResponse | null>(null);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { support_enabled?: boolean } | null) => setSupportEnabled(payload?.support_enabled === true))
      .catch(() => setSupportEnabled(false));
  }, []);

  const platform = nativePlatform();
  const ticketSource = platform === "ios" || platform === "android" ? platform : "web";
  const diagnostics = useMemo(() => includeDiagnostics ? buildBugReportDiagnostics({
    appVersion: build?.version ?? null,
    buildNumber: build?.build_time ?? null,
    platform,
    runtime: isNativeShell() ? "native" : "web",
    notificationPermission,
    online: typeof navigator === "undefined" ? null : navigator.onLine,
  }) : null, [build?.version, build?.build_time, includeDiagnostics, notificationPermission, platform]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !activeHomeId || supportEnabled !== true) return;
    setError(null);
    setAttachmentWarning(null);
    if (!subject.trim() || !description.trim()) {
      setError("Add a short summary and tell us what happened.");
      return;
    }
    setBusy(true);
    try {
      const ticket = await api.createSupportTicket({ type: "bug", subject: subject.trim(), description: description.trim(), source: ticketSource, app_area: area, priority: SEVERITY_TO_PRIORITY[severity], group_id: activeHomeId, diagnostics });
      if (screenshot) {
        try { await api.uploadSupportAttachment(ticket.id, screenshot); }
        catch { setAttachmentWarning("Your report was sent, but the screenshot could not be attached."); }
      }
      setSuccess(ticket);
    } catch (submissionError) {
      const raw = submissionError instanceof Error ? submissionError.message : "";
      const unsafe = /duplicate|constraint|unique key|traceback|sql/i.test(raw);
      setError(!unsafe && raw ? raw : "Couldn’t submit your report. Please try again.");
    } finally { setBusy(false); }
  }

  if (supportEnabled === false) return <SettingsPage title="Report a bug" description="Help us fix issues faster by sharing what happened."><section className="card details" aria-live="polite"><h2>Bug reporting unavailable</h2><p className="muted">This service is not available right now. Please check Service Status and try again later.</p></section></SettingsPage>;
  if (success) return <SettingsPage title="Report a bug" description="Thanks for helping us improve MyKhaya."><section className="card details support-success" aria-live="polite"><CheckCircle2 aria-hidden="true" /><h2>Report sent</h2><p>We&apos;ve received your report and will review it.</p><p className="support-reference" aria-label={`Support reference ${success.reference}`}>Reference: <strong>{success.reference}</strong></p>{attachmentWarning && <p className="field-error">{attachmentWarning}</p>}<a className="button" href="/help-support">Back to Help &amp; Support</a></section></SettingsPage>;

  return <SettingsPage title="Report a bug" description="Help us fix issues faster by sharing what happened."><form className="card details support-form" onSubmit={submit} noValidate>
    {error && <p className="notice error" role="alert"><AlertCircle size={16} aria-hidden="true" />{error}</p>}
    <label>What went wrong?<input value={subject} maxLength={MAX_SUBJECT} onChange={(event) => setSubject(event.target.value)} required aria-describedby="subject-help" /><small id="subject-help">{subject.length}/{MAX_SUBJECT}</small></label>
    <label>App area<select value={area} onChange={(event) => setArea(event.target.value)}>{APP_AREA_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
    <fieldset><legend>How serious is it?</legend><div className="support-choice-list">{SEVERITY_OPTIONS.map((option) => <label className={`support-choice${severity === option.value ? " selected" : ""}`} key={option.value}><input type="radio" name="severity" value={option.value} checked={severity === option.value} onChange={() => setSeverity(option.value)} /><span><strong>{option.label}</strong><small>{option.description}</small></span></label>)}</div></fieldset>
    <label>What happened?<textarea value={description} maxLength={4000} onChange={(event) => setDescription(event.target.value)} required rows={6} /></label>
    <label className="support-file-field"><span><ImagePlus size={16} aria-hidden="true" /> Screenshot (optional)</span><input type="file" accept="image/*" onChange={(event) => setScreenshot(event.target.files?.[0] ?? null)} />{screenshot && <small>{screenshot.name}</small>}</label>
    <label className="check-row"><input type="checkbox" checked={includeDiagnostics} onChange={(event) => setIncludeDiagnostics(event.target.checked)} />Include helpful diagnostics</label>
    <button className="button" type="submit" disabled={busy || supportEnabled !== true || !activeHomeId}><Send size={16} aria-hidden="true" /> {busy ? "Sending…" : "Send report"}</button>
  </form></SettingsPage>;
}
