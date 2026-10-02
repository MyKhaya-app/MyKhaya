"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { relativeTime, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard, CcSection } from "@/components/control-centre/section";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcEmptyState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcDialog, CcDialogActions, CcConfirmDialog } from "@/components/control-centre/dialog";

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
      <CcBadge tone={template.is_override ? "info" : "neutral"}>{template.is_override ? "Customised" : "Default"}</CcBadge>{" "}
      <CcBadge tone={template.enabled ? "success" : "danger"}>{template.enabled ? "Enabled" : "Disabled"}</CcBadge>{" "}
      {!template.disableable && <CcBadge tone="warning">Required</CcBadge>}{" "}
      {template.is_stale && <CcBadge tone="warning">Built-in wording changed</CcBadge>}
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
  const { guarded, modal } = useReauthGuard();

  // Filters — applied client-side; the registry is small (a couple of dozen
  // entries at most) so there's no need for server-side filtering/paging.
  const [search, setSearch] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "enabled" | "disabled">("");
  const [originFilter, setOriginFilter] = useState<"" | "customised" | "default">("");
  const [criticalOnly, setCriticalOnly] = useState(false);

  const [resetOpen, setResetOpen] = useState(false);
  const [resetAllOpen, setResetAllOpen] = useState(false);

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

  const modules = useMemo(() => Array.from(new Set(templates.map((row) => row.module))).sort(), [templates]);
  const channels = useMemo(() => Array.from(new Set(templates.map((row) => row.channel))).sort(), [templates]);

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
        await platformApi.post<{ subject: string; body: string }>(`/notification-templates/${selected}/preview`, {
          subject,
          body,
        }),
      );
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  // PUT/DELETE /notification-templates/{type} and POST /reset-all are all
  // guarded server-side with require_recent_auth()
  // (apps/api/mykhaya/routers/platform.py) — a 403 transparently opens
  // PlatformReauthModal and retries the same submit once verified.
  // FormData is read synchronously from the event here, before guarded()
  // is entered — a reauth retry replays the wrapped callback after the
  // operator re-authenticates, by which point React has already detached
  // event.currentTarget from the original submit event, so reading the
  // form inside the guarded callback would crash on retry.
  const save = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!selected || !active) return;
      setError("");
      setMessage("");

      // Usability only — the backend re-validates this and is authoritative.
      // Checking here just avoids a round trip for the common slip of editing
      // out a required placeholder, without discarding the admin's draft.
      const missing = missingRequiredVariables(subject, body, active.required_variables);
      if (missing.length > 0) {
        setError(`Template must include required placeholder(s): ${missing.map((name) => `{{${name}}}`).join(", ")}.`);
        return;
      }

      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setBusy(true);
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
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError((cause as Error).message);
        } finally {
          setBusy(false);
        }
      })();
    },
    [selected, active, subject, body, enabled, load, guarded],
  );

  const resetToDefault = useCallback(
    () =>
      guarded(async () => {
        setResetOpen(false);
        if (!selected || !active) return;
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
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError((cause as Error).message);
        } finally {
          setBusy(false);
        }
      })(),
    [selected, active, load, guarded],
  );

  const resetAll = useCallback(
    (formData: FormData) =>
      guarded(async () => {
        const reason = formData.get("audit_reason");
        setBusy(true);
        setError("");
        setMessage("");
        try {
          await platformApi.post("/notification-templates/reset-all", { reason, confirmed: true });
          setMessage("All notification templates restored to their built-in defaults.");
          setResetAllOpen(false);
          setSelected(null);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError((cause as Error).message);
        } finally {
          setBusy(false);
        }
      })(),
    [load, guarded],
  );

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Notifications"
          title="Templates"
          description="The built-in wording is always the authoritative default. Saving here creates an override for just this template — it never copies the default into the database, so a future MyKhaya update to the built-in wording won't be silently lost."
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        <NotificationsSubNav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        <CcCard title="Filter templates">
          <form onSubmit={(event) => event.preventDefault()}>
            <CcField label="Search">
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, key, module or wording" />
            </CcField>
            <CcField label="Module">
              <select value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}>
                <option value="">Any</option>
                {modules.map((value) => (
                  <option key={value} value={value}>
                    {titleCase(value)}
                  </option>
                ))}
              </select>
            </CcField>
            <CcField label="Channel">
              <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
                <option value="">Any</option>
                {channels.map((value) => (
                  <option key={value} value={value}>
                    {titleCase(value)}
                  </option>
                ))}
              </select>
            </CcField>
            <CcField label="Status">
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}>
                <option value="">Any</option>
                <option value="enabled">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </CcField>
            <CcField label="Origin">
              <select value={originFilter} onChange={(event) => setOriginFilter(event.target.value as typeof originFilter)}>
                <option value="">Any</option>
                <option value="customised">Customised</option>
                <option value="default">Using default</option>
              </select>
            </CcField>
            <CcField label="Security/system-critical only">
              <input type="checkbox" checked={criticalOnly} onChange={(event) => setCriticalOnly(event.target.checked)} />
            </CcField>
          </form>
        </CcCard>

        <CcCard title="Registered templates">
          {filtered.length === 0 ? (
            <CcEmptyState>No templates match those filters.</CcEmptyState>
          ) : (
            <div className="table-scroll cc-table-scroll" tabIndex={0}>
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
                      className={selected === template.template_type ? "active cc-table-row" : "cc-table-row"}
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
            </div>
          )}
        </CcCard>

        {active && (
          <CcSection title={titleCase(active.template_type.replaceAll(".", " "))}>
            <p className="cc-technical-value">{active.template_type}</p>
            <p>{active.description}</p>
            <p className="cc-technical-value">
              Allowed variables:{" "}
              {active.allowed_variables.length > 0
                ? active.allowed_variables
                    .map((name) => (active.required_variables.includes(name) ? `{{${name}}} — Required` : `{{${name}}}`))
                    .join(", ")
                : "none"}
            </p>

            <details>
              <summary>Built-in default wording</summary>
              <p>
                <strong>Subject:</strong> {active.default_subject}
              </p>
              <p style={{ whiteSpace: "pre-wrap" }}>{active.default_body}</p>
            </details>

            <form onSubmit={save}>
              <CcField label="Subject">
                <input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={200} required />
              </CcField>
              <CcField label="Body">
                <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={8} maxLength={4000} required />
              </CcField>
              {active.allowed_variables.length > 0 && (
                <CcActionBar
                  actions={active.allowed_variables.map((name) => ({
                    key: name,
                    label: (
                      <>
                        Insert {`{{${name}}}`}
                        {active.required_variables.includes(name) && <CcBadge tone="warning">Required</CcBadge>}
                      </>
                    ),
                    onClick: () => setBody((current) => `${current}{{${name}}}`),
                  }))}
                />
              )}
              <CcField label="Enabled">
                <input
                  type="checkbox"
                  checked={enabled}
                  disabled={!active.disableable}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
              </CcField>
              {!active.disableable && <p className="cc-technical-value">Required — this notification cannot be disabled from Control Centre.</p>}
              <CcField label="Reason for change">
                <input name="reason" minLength={10} maxLength={500} required />
              </CcField>
              <CcActionBar
                actions={[
                  { key: "save", label: busy ? "Saving…" : "Save override", variant: "primary", type: "submit", disabled: busy },
                  { key: "preview", label: "Preview", onClick: () => void previewDraft() },
                  ...(active.is_override
                    ? [{ key: "reset", label: "Reset to default", disabled: busy, onClick: () => setResetOpen(true) }]
                    : []),
                ]}
              />
            </form>
            {active.updated_at && (
              <p className="cc-technical-value">
                Last updated {relativeTime(active.updated_at)}
                {active.updated_by ? ` by ${active.updated_by}` : ""}.
              </p>
            )}

            {preview && (
              <CcCard title="Effective content (sample data)">
                <p>
                  <strong>Subject:</strong> {preview.subject}
                </p>
                <p style={{ whiteSpace: "pre-wrap" }}>{preview.body}</p>
              </CcCard>
            )}
          </CcSection>
        )}

        <CcCard
          title="Restore all defaults"
          description="Deletes every notification template override — every notification goes back to using its built-in wording. This cannot be undone."
        >
          <CcActionBar
            actions={[{ key: "restore-all", label: "Restore all templates to defaults", variant: "destructive", onClick: () => setResetAllOpen(true) }]}
          />
        </CcCard>
      </CcPage>

      {resetOpen && active && (
        <CcDialog open onClose={() => setResetOpen(false)} title="Reset to default wording">
          <div className="cc-dialog-scroll">
            <p>Reset &ldquo;{selected}&rdquo; to the built-in default wording?</p>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setResetOpen(false)}>
              Cancel
            </button>
            <button type="button" onClick={() => void resetToDefault()}>
              Reset to default
            </button>
          </CcDialogActions>
        </CcDialog>
      )}

      <CcConfirmDialog
        open={resetAllOpen}
        onClose={() => setResetAllOpen(false)}
        title="Restore all templates to defaults"
        description="Restore every notification template to its built-in default? Every customisation will be lost."
        confirmLabel="Confirm — restore all defaults"
        variant="destructive"
        onConfirm={resetAll}
      />
      {modal}
    </PlatformShell>
  );
}
