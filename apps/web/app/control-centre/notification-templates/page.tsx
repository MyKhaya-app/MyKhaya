"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime, titleCase } from "@/components/platform-format";

type Template = {
  template_type: string;
  channel: string;
  description: string;
  allowed_variables: string[];
  default_subject: string;
  default_body: string;
  subject: string;
  body: string;
  is_override: boolean;
  enabled: boolean;
  is_stale: boolean;
  updated_at: string | null;
};

export default function NotificationTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [testRecipient, setTestRecipient] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setTemplates(await platformApi.get<Template[]>("/notification-templates"));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    platformApi
      .get<{ email: string }>("/auth/me")
      .then((actor) => setTestRecipient(actor.email))
      .catch(() => {});
  }, []);

  function openTemplate(template: Template) {
    setSelected(template.template_type);
    setSubject(template.subject);
    setBody(template.body);
    setEnabled(template.enabled);
    setPreview(null);
    setMessage("");
    setError("");
  }

  const active = templates.find((row) => row.template_type === selected) ?? null;

  async function previewDraft() {
    if (!selected) return;
    setError("");
    try {
      setPreview(
        await platformApi.post<{ subject: string; body: string }>(
          `/notification-templates/${selected}/preview`,
          { subject, body },
        ),
      );
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      await platformApi.put(`/notification-templates/${selected}`, {
        subject,
        body,
        enabled,
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage("Template saved.");
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function resetToDefault() {
    if (!selected || !active) return;
    if (!window.confirm(`Reset "${selected}" to the built-in default wording?`)) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await platformApi.delete(`/notification-templates/${selected}`);
      setMessage("Reset to the built-in default.");
      await load();
      openTemplate({ ...active, is_override: false, subject: active.default_subject, body: active.default_body, enabled: true });
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.post<{ message: string }>(
        `/notification-templates/${selected}/test`,
        {
          recipient: form.get("recipient"),
          reason: form.get("test_reason"),
          confirmed: true,
        },
      );
      setMessage(result.message);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Delivery operations</p>
            <h1>Notification Templates</h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        <p>
          The built-in wording is always the authoritative default. Saving here creates an
          override for just this template — it never copies the default into the database,
          so a future MyKhaya update to the built-in wording won't be silently lost.
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

        <div className="settings-list">
          {templates.map((template) => (
            <button
              key={template.template_type}
              className="card"
              onClick={() => openTemplate(template)}
              style={{ textAlign: "left", cursor: "pointer" }}
            >
              <div>
                <h2>{titleCase(template.template_type)}</h2>
                <p>{template.description}</p>
                <small>
                  {template.is_override ? "Customised" : "Using built-in default"}
                  {!template.enabled && " · Disabled"}
                  {template.is_stale && " · Built-in wording has changed since this was saved"}
                </small>
              </div>
              <span>›</span>
            </button>
          ))}
        </div>

        {active && (
          <section className="action-panel">
            <h2>{titleCase(active.template_type)}</h2>
            <p>
              <small>
                Allowed variables:{" "}
                {active.allowed_variables.map((name) => `{{${name}}}`).join(", ")}
              </small>
            </p>

            <form onSubmit={save}>
              <label>
                Subject
                <input
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  maxLength={200}
                  required
                />
              </label>
              <label>
                Body
                <textarea
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  rows={8}
                  maxLength={4000}
                  required
                />
              </label>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => setEnabled(event.target.checked)}
                />{" "}
                Enabled (unchecked falls back to the built-in default for every send)
              </label>
              <label>
                Reason for change
                <input name="reason" minLength={10} maxLength={500} required />
              </label>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button disabled={busy}>{busy ? "Saving…" : "Save override"}</button>
                <button type="button" className="secondary" onClick={previewDraft}>
                  Preview
                </button>
                {active.is_override && (
                  <button type="button" className="secondary" onClick={resetToDefault} disabled={busy}>
                    Reset to default
                  </button>
                )}
              </div>
            </form>
            {active.updated_at && <small>Last updated {relativeTime(active.updated_at)}.</small>}

            {preview && (
              <div className="card details" style={{ marginTop: "1rem" }}>
                <h3>Preview (sample data)</h3>
                <p>
                  <strong>Subject:</strong> {preview.subject}
                </p>
                <p style={{ whiteSpace: "pre-wrap" }}>{preview.body}</p>
              </div>
            )}

            <form className="test-email-form" onSubmit={sendTest} style={{ marginTop: "1rem" }}>
              <h3>Send a test email</h3>
              <label>
                Recipient
                <input
                  name="recipient"
                  type="email"
                  required
                  value={testRecipient}
                  onChange={(event) => setTestRecipient(event.target.value)}
                />
              </label>
              <label>
                Reason for test
                <input name="test_reason" minLength={10} maxLength={500} required />
              </label>
              <button disabled={busy}>{busy ? "Sending…" : "Send test email"}</button>
              <small>
                Sends the currently saved version (not this unsaved draft) using sample data.
              </small>
            </form>
          </section>
        )}
      </main>
    </PlatformShell>
  );
}
