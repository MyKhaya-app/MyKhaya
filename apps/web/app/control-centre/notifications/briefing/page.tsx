"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { relativeTime } from "@/components/platform-format";

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

  const load = useCallback(async () => {
    setError("");
    try {
      const rows = await platformApi.get<Template[]>("/notification-templates");
      const briefing = rows.filter((row) => BRIEFING_KEYS.includes(row.template_type));
      setTemplates(briefing);
      setDrafts(Object.fromEntries(briefing.map((row) => [row.template_type, row.body])));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(template: Template, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(template.template_type);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
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
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function reset(template: Template) {
    if (!window.confirm(`Reset "${template.template_type}" to the built-in default wording?`)) return;
    setBusy(template.template_type);
    setError("");
    setMessage("");
    try {
      await platformApi.delete(`/notification-templates/${template.template_type}`);
      setMessage(`Reset "${template.template_type}" to its default.`);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Notifications</p>
            <h1>Daily Briefing</h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        <NotificationsSubNav />
        <p>
          These two fragments are the only editable wording in the daily briefing. Which events,
          meals and routines appear, their ordering, and the empty-day messages are determined by
          existing product rules and are not changed here.
        </p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}
        {templates.map((template) => (
          <section className="action-panel" key={template.template_type}>
            <h2>{template.template_type === "briefing.title" ? "Heading" : "Intro line"}</h2>
            <p>{template.description}</p>
            <details>
              <summary>Built-in default</summary>
              <p style={{ whiteSpace: "pre-wrap" }}>{template.default_body}</p>
            </details>
            <form onSubmit={(event) => save(template, event)}>
              <label>
                Wording
                <textarea
                  value={drafts[template.template_type] ?? ""}
                  onChange={(event) =>
                    setDrafts((current) => ({ ...current, [template.template_type]: event.target.value }))
                  }
                  rows={3}
                  maxLength={4000}
                  required
                />
              </label>
              {template.allowed_variables.length > 0 && (
                <p>
                  <small>
                    Allowed variables:{" "}
                    {template.allowed_variables.map((name) => `{{${name}}}`).join(", ")}
                  </small>
                </p>
              )}
              <label>
                Reason for change
                <input name="reason" minLength={10} maxLength={500} required />
              </label>
              <div className="sheet-actions">
                <button disabled={busy === template.template_type}>
                  {busy === template.template_type ? "Saving…" : "Save"}
                </button>
                {template.is_override && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => reset(template)}
                    disabled={busy === template.template_type}
                  >
                    Reset to default
                  </button>
                )}
              </div>
            </form>
            {template.updated_at && (
              <small>
                Last updated {relativeTime(template.updated_at)}
                {template.updated_by ? ` by ${template.updated_by}` : ""}.
              </small>
            )}
          </section>
        ))}
      </main>
    </PlatformShell>
  );
}
