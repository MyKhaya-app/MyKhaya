"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { relativeTime } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection } from "@/components/control-centre/section";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";

type Template = {
  template_type: string;
  description: string;
  allowed_variables: string[];
  default_subject: string;
  default_body: string;
  subject: string;
  body: string;
  is_override: boolean;
  updated_at: string | null;
  updated_by: string | null;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

const BRIEFING_KEYS = ["briefing.title", "briefing.intro"];

/** Only the two wording fragments (title/intro) are exposed here — the
 *  algorithmic content of the briefing (which events/meals/routines appear,
 *  ordering, empty-day rotation, "+N more" overflow) lives in
 *  notifications/briefing.py and is intentionally NOT editable from PCC. */
export default function DailyBriefingPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<Template | null>(null);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      const rows = await platformApi.get<Template[]>("/notification-templates");
      const briefing = rows.filter((row) => BRIEFING_KEYS.includes(row.template_type));
      setTemplates(briefing);
      setDrafts(Object.fromEntries(briefing.map((row) => [row.template_type, row.body])));
    } catch (cause) {
      setError(safeError(cause, "Could not load the daily briefing wording."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // PUT/DELETE /notification-templates/{type} are guarded server-side with
  // require_recent_auth() (apps/api/mykhaya/routers/platform.py) — a 403
  // transparently opens PlatformReauthModal and retries the same submit
  // once verified.
  // FormData is read synchronously from the event here, before guarded()
  // is entered — a reauth retry replays the wrapped callback after the
  // operator re-authenticates, by which point React has already detached
  // event.currentTarget from the original submit event, so reading the
  // form inside the guarded callback would crash on retry.
  const save = useCallback(
    (template: Template, event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setBusy(template.template_type);
        setError("");
        setMessage("");
        try {
          await platformApi.put(`/notification-templates/${template.template_type}`, {
            subject: drafts[template.template_type],
            body: drafts[template.template_type],
            enabled: true,
            reason: form.get("reason"),
            confirmed: true,
          });
          setMessage(`Saved "${template.template_type}".`);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The wording could not be saved."));
        } finally {
          setBusy(null);
        }
      })();
    },
    [drafts, load, guarded],
  );

  const reset = useCallback(
    (template: Template) =>
      guarded(async () => {
        setResetTarget(null);
        setBusy(template.template_type);
        setError("");
        setMessage("");
        try {
          await platformApi.delete(`/notification-templates/${template.template_type}`);
          setMessage(`Reset "${template.template_type}" to its default.`);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The wording could not be reset."));
        } finally {
          setBusy(null);
        }
      })(),
    [load, guarded],
  );

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Notifications"
          title="Daily Briefing"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        <NotificationsSubNav />
        <p>
          These two fragments are the only editable wording in the daily briefing. Which events,
          meals and routines appear, their ordering, and the empty-day messages are determined by
          existing product rules and are not changed here.
        </p>
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}
        {templates.map((template) => (
          <CcSection title={template.template_type === "briefing.title" ? "Heading" : "Intro line"} key={template.template_type}>
            <p>{template.description}</p>
            <details>
              <summary>Built-in default</summary>
              <p style={{ whiteSpace: "pre-wrap" }}>{template.default_body}</p>
            </details>
            <form onSubmit={(event) => save(template, event)}>
              <CcField label="Wording">
                <textarea
                  value={drafts[template.template_type] ?? ""}
                  onChange={(event) =>
                    setDrafts((current) => ({ ...current, [template.template_type]: event.target.value }))
                  }
                  rows={3}
                  maxLength={4000}
                  required
                />
              </CcField>
              {template.allowed_variables.length > 0 && (
                <p className="cc-technical-value">
                  Allowed variables: {template.allowed_variables.map((name) => `{{${name}}}`).join(", ")}
                </p>
              )}
              <CcField label="Reason for change">
                <input name="reason" minLength={10} maxLength={500} required />
              </CcField>
              <CcActionBar
                actions={[
                  { key: "save", label: busy === template.template_type ? "Saving…" : "Save", variant: "primary", type: "submit", disabled: busy === template.template_type },
                  ...(template.is_override
                    ? [{ key: "reset", label: "Reset to default", disabled: busy === template.template_type, onClick: () => setResetTarget(template) }]
                    : []),
                ]}
              />
            </form>
            {template.updated_at && (
              <p className="cc-technical-value">
                Last updated {relativeTime(template.updated_at)}
                {template.updated_by ? ` by ${template.updated_by}` : ""}.
              </p>
            )}
          </CcSection>
        ))}
      </CcPage>

      {resetTarget && (
        <CcDialog open onClose={() => setResetTarget(null)} title="Reset to default wording">
          <div className="cc-dialog-scroll">
            <p>Reset &ldquo;{resetTarget.template_type}&rdquo; to the built-in default wording?</p>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setResetTarget(null)}>
              Cancel
            </button>
            <button type="button" onClick={() => void reset(resetTarget)}>
              Reset to default
            </button>
          </CcDialogActions>
        </CcDialog>
      )}
      {modal}
    </PlatformShell>
  );
}
