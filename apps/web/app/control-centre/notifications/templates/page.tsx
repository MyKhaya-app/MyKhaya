"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { relativeTime, titleCase } from "@/components/platform-format";

type Template = {
  template_type: string;
  module: string;
  channel: string;
  description: string;
  allowed_variables: string[];
  required_variables: string[];
  default_subject: string;
  default_body: string;
  subject: string;
  body: string;
  is_override: boolean;
  enabled: boolean;
  disableable: boolean;
  security_critical: boolean;
  is_stale: boolean;
  updated_at: string | null;
  updated_by: string | null;
};

function usedVariables(text: string): Set<string> {
  const names: string[] = [];
  for (const match of text.matchAll(/\{\{(\w+)\}\}/g)) {
    if (match[1]) names.push(match[1]);
  }
  return new Set(names);
}

function missingRequiredVariables(subject: string, body: string, required: string[]): string[] {
  const present = new Set([...usedVariables(subject), ...usedVariables(body)]);
  return required.filter((name) => !present.has(name));
}

function StatusBadges({ template }: { template: Template }) {
  return (
    <>
      <span className={template.is_override ? "badge badge-info" : "badge badge-neutral"}>
        {template.is_override ? "Customised" : "Default"}
      </span>
      <span className={template.enabled ? "badge badge-success" : "badge badge-danger"}>
        {template.enabled ? "Enabled" : "Disabled"}
      </span>
      {!template.disableable && <span className="badge badge-warning">Required</span>}
      {template.is_stale && <span className="badge badge-warning">Built-in wording changed</span>}
    </>
  );
}

export default function NotificationTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  // Filters — applied client-side; the registry is small (a couple of dozen
  // entries at most) so there's no need for server-side filtering/paging.
  const [search, setSearch] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "enabled" | "disabled">("");
  const [originFilter, setOriginFilter] = useState<"" | "customised" | "default">("");
  const [criticalOnly, setCriticalOnly] = useState(false);

  const [resetAllOpen, setResetAllOpen] = useState(false);
  const [resetAllReason, setResetAllReason] = useState("");

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

  const modules = useMemo(
    () => Array.from(new Set(templates.map((row) => row.module))).sort(),
    [templates],
  );
  const channels = useMemo(
    () => Array.from(new Set(templates.map((row) => row.channel))).sort(),
    [templates],
  );

  const filtered = templates.filter((row) => {
    if (moduleFilter && row.module !== moduleFilter) return false;
    if (channelFilter && row.channel !== channelFilter) return false;
    if (statusFilter === "enabled" && !row.enabled) return false;
    if (statusFilter === "disabled" && row.enabled) return false;
    if (originFilter === "customised" && !row.is_override) return false;
    if (originFilter === "default" && row.is_override) return false;
    if (criticalOnly && !row.security_critical) return false;
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return (
      row.template_type.toLowerCase().includes(needle) ||
      row.module.toLowerCase().includes(needle) ||
      row.description.toLowerCase().includes(needle) ||
      row.subject.toLowerCase().includes(needle) ||
      row.body.toLowerCase().includes(needle)
    );
  });

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
    if (!selected || !active) return;
    setError("");
    setMessage("");

    // Usability only — the backend re-validates this and is authoritative.
    // Checking here just avoids a round trip for the common slip of editing
    // out a required placeholder, without discarding the admin's draft.
    const missing = missingRequiredVariables(subject, body, active.required_variables);
    if (missing.length > 0) {
      setError(
        `Template must include required placeholder(s): ${missing
          .map((name) => `{{${name}}}`)
          .join(", ")}.`,
      );
      return;
    }

    setBusy(true);
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
      await load();
      setSubject(active.default_subject);
      setBody(active.default_body);
      setEnabled(true);
      setPreview(null);
      setMessage("Reset to the built-in default.");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function resetAll(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !window.confirm(
        "Restore every notification template to its built-in default? Every customisation will be lost.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await platformApi.post("/notification-templates/reset-all", {
        reason: resetAllReason,
        confirmed: true,
      });
      setMessage("All notification templates restored to their built-in defaults.");
      setResetAllOpen(false);
      setResetAllReason("");
      setSelected(null);
      await load();
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
            <p>Notifications</p>
            <h1>Templates</h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        <NotificationsSubNav />
        <p>
          The built-in wording is always the authoritative default. Saving here creates an
          override for just this template — it never copies the default into the database,
          so a future MyKhaya update to the built-in wording won&rsquo;t be silently lost.
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

        <form className="action-panel" onSubmit={(event) => event.preventDefault()}>
          <label>
            Search
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, key, module or wording"
            />
          </label>
          <label>
            Module
            <select value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}>
              <option value="">Any</option>
              {modules.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Channel
            <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
              <option value="">Any</option>
              {channels.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
            >
              <option value="">Any</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <label>
            Origin
            <select
              value={originFilter}
              onChange={(event) => setOriginFilter(event.target.value as typeof originFilter)}
            >
              <option value="">Any</option>
              <option value="customised">Customised</option>
              <option value="default">Using default</option>
            </select>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={criticalOnly}
              onChange={(event) => setCriticalOnly(event.target.checked)}
            />{" "}
            Security/system-critical only
          </label>
        </form>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Module</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Last modified</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((template) => (
                <tr
                  key={template.template_type}
                  onClick={() => openTemplate(template)}
                  style={{ cursor: "pointer" }}
                  className={selected === template.template_type ? "active" : undefined}
                >
                  <td>
                    <strong>{titleCase(template.template_type.replaceAll(".", " "))}</strong>
                    <br />
                    <small>{template.template_type}</small>
                  </td>
                  <td>{titleCase(template.module)}</td>
                  <td>{titleCase(template.channel)}</td>
                  <td>
                    <StatusBadges template={template} />
                  </td>
                  <td>{template.updated_at ? relativeTime(template.updated_at) : "—"}</td>
                  <td>{template.updated_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && <p className="quiet-state">No templates match those filters.</p>}
        </div>

        {active && (
          <section className="action-panel">
            <h2>{titleCase(active.template_type.replaceAll(".", " "))}</h2>
            <p>
              <small>{active.template_type}</small>
            </p>
            <p>{active.description}</p>
            <p>
              <small>
                Allowed variables:{" "}
                {active.allowed_variables.length > 0
                  ? active.allowed_variables
                      .map((name) =>
                        active.required_variables.includes(name)
                          ? `{{${name}}} — Required`
                          : `{{${name}}}`,
                      )
                      .join(", ")
                  : "none"}
              </small>
            </p>

            <details>
              <summary>Built-in default wording</summary>
              <p>
                <strong>Subject:</strong> {active.default_subject}
              </p>
              <p style={{ whiteSpace: "pre-wrap" }}>{active.default_body}</p>
            </details>

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
              {active.allowed_variables.length > 0 && (
                <div className="sheet-actions">
                  {active.allowed_variables.map((name) => {
                    const isRequired = active.required_variables.includes(name);
                    return (
                      <button
                        key={name}
                        type="button"
                        className="secondary"
                        onClick={() => setBody((current) => `${current}{{${name}}}`)}
                      >
                        Insert {`{{${name}}}`}
                        {isRequired && <span className="badge badge-warning">Required</span>}
                      </button>
                    );
                  })}
                </div>
              )}
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={enabled}
                  disabled={!active.disableable}
                  onChange={(event) => setEnabled(event.target.checked)}
                />{" "}
                Enabled
                {!active.disableable &&
                  " (required — this notification cannot be disabled from Control Centre)"}
              </label>
              <label>
                Reason for change
                <input name="reason" minLength={10} maxLength={500} required />
              </label>
              <div className="sheet-actions">
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
            {active.updated_at && (
              <small>
                Last updated {relativeTime(active.updated_at)}
                {active.updated_by ? ` by ${active.updated_by}` : ""}.
              </small>
            )}

            {preview && (
              <div className="card details">
                <h3>Effective content (sample data)</h3>
                <p>
                  <strong>Subject:</strong> {preview.subject}
                </p>
                <p style={{ whiteSpace: "pre-wrap" }}>{preview.body}</p>
              </div>
            )}
          </section>
        )}

        <section className="action-panel">
          <h2>Restore all defaults</h2>
          <p className="quiet-state">
            Deletes every notification template override — every notification goes back to
            using its built-in wording. This cannot be undone.
          </p>
          {!resetAllOpen ? (
            <button type="button" className="danger" onClick={() => setResetAllOpen(true)}>
              Restore all templates to defaults
            </button>
          ) : (
            <form onSubmit={resetAll}>
              <label>
                Reason
                <input
                  value={resetAllReason}
                  onChange={(event) => setResetAllReason(event.target.value)}
                  minLength={10}
                  maxLength={500}
                  required
                />
              </label>
              <div className="sheet-actions">
                <button type="submit" className="danger" disabled={busy}>
                  {busy ? "Restoring…" : "Confirm — restore all defaults"}
                </button>
                <button type="button" className="secondary" onClick={() => setResetAllOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </section>
      </main>
    </PlatformShell>
  );
}
