"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge } from "@/components/control-centre/badge";
import { CcCard } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { CcLoadingState, CcNotice } from "@/components/control-centre/status-message";

type LastRun = {
  status: "succeeded" | "failed";
  trigger: string;
  finished_at: string;
  created?: number;
  updated?: number;
  skipped?: number;
  error?: string | null;
};

type Overview = {
  environment: string;
  branch: string;
  url: string | null;
  token_id: string | null;
  has_token_secret: boolean;
  repository_url: string | null;
  include_paths: string[];
  shelf_id: number | null;
  shelf_name: string | null;
  auto_enabled: boolean;
  configured: boolean;
  connection: { ok: boolean; message: string; checked_at: string } | null;
  last_success_at: string | null;
  last_run: LastRun | null;
  sync_requested: boolean;
  changes_pending: boolean;
  source: { available: boolean; documents?: number; error?: string };
};

type Shelf = { id: number; name: string };
type Pending = { title: string; confirm: string; run: (reason: string) => Promise<string> };

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

/**
 * Documentation Sync: publishes the repository docs bundled in this build
 * to managed books within a BookStack shelf. Owner/Administrator only (enforced by the API). The
 * token secret is write-only: the page only ever learns whether one is set.
 */
export default function DocsSyncPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [shelves, setShelves] = useState<Shelf[] | null>(null);
  const [form, setForm] = useState({ url: "", token_id: "", token_secret: "", repository_url: "", include_paths: "" });
  const [shelfId, setShelfId] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await platformApi.get<Overview>("/docs-sync");
      setData(next);
      setForm((current) => ({
        url: next.url ?? "",
        token_id: next.token_id ?? "",
        token_secret: current.token_secret,
        repository_url: next.repository_url ?? "",
        include_paths: next.include_paths.join(", "),
      }));
      setShelfId(next.shelf_id ? String(next.shelf_id) : "");
    } catch (cause) {
      setError(safeError(cause, "Documentation sync is unavailable."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshShelves() {
    setError("");
    try {
      setShelves((await platformApi.get<{ shelves: Shelf[] }>("/docs-sync/shelves")).shelves);
    } catch (cause) {
      setError(safeError(cause, "Could not load BookStack shelves."));
    }
  }

  function confirm(title: string, confirmLabel: string, run: (reason: string) => Promise<string>) {
    setPending({ title, confirm: confirmLabel, run });
  }

  async function submit(formData: FormData) {
    if (!pending) return;
    const value = formData.get("audit_reason");
    const reason = typeof value === "string" ? value.trim() : "";
    setError("");
    try {
      setNotice(await pending.run(reason));
      setPending(null);
      setForm((current) => ({ ...current, token_secret: "" }));
      await load();
    } catch (cause) {
      setError(safeError(cause, "The action could not be completed."));
    }
  }

  if (!data) {
    return (
      <PlatformShell>
        <CcPage>
          <CcPageHeader eyebrow="Platform" title="Documentation Sync" />
          {error ? <CcNotice tone="error">{error}</CcNotice> : <CcLoadingState />}
        </CcPage>
      </PlatformShell>
    );
  }

  const last = data.last_run;
  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Platform"
          title="Documentation Sync"
          description={`Publishes this build's repository documentation (${data.branch} branch, ${data.environment}) to managed books in a private BookStack shelf. One-way; content is never deleted.`}
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {notice && <CcNotice tone="success">{notice}</CcNotice>}

        <CcCard
          title="Connection"
          actions={
            data.connection && (
              <CcBadge tone={data.connection.ok ? "success" : "danger"}>
                {data.connection.ok ? "Connected" : "Connection failed"}
              </CcBadge>
            )
          }
        >
          <form
            className="cc-monitor-form"
            onSubmit={(event) => {
              event.preventDefault();
              confirm("Save BookStack connection", "Save", async (reason) => {
                const result = await platformApi.put<{ shelf_cleared: boolean }>("/docs-sync/connection", {
                  url: form.url,
                  token_id: form.token_id,
                  token_secret: form.token_secret || null,
                  repository_url: form.repository_url || null,
                  include_paths: form.include_paths.split(",").map((item) => item.trim()).filter(Boolean),
                  reason,
                  confirmed: true,
                });
                return result.shelf_cleared ? "Saved. Select a destination shelf for this instance." : "Connection saved.";
              });
            }}
          >
            <label>
              BookStack URL (public HTTPS)
              <input type="url" required value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://" />
            </label>
            <label>
              API token ID
              <input required value={form.token_id} onChange={(e) => setForm({ ...form, token_id: e.target.value })} autoComplete="off" />
            </label>
            <label>
              API token secret
              <input
                type="password"
                value={form.token_secret}
                onChange={(e) => setForm({ ...form, token_secret: e.target.value })}
                autoComplete="new-password"
                placeholder={data.has_token_secret ? "Stored. Leave blank to keep (required if the URL changes)" : ""}
              />
            </label>
            <label>
              GitHub repository URL (optional, for source links)
              <input type="url" value={form.repository_url} onChange={(e) => setForm({ ...form, repository_url: e.target.value })} placeholder="https://github.com/…" />
            </label>
            <label>
              Limit to folders under docs/ (optional, comma separated)
              <input value={form.include_paths} onChange={(e) => setForm({ ...form, include_paths: e.target.value })} placeholder="architecture, operations" />
            </label>
            <div className="cc-monitor-actions">
              <button type="submit">Save connection</button>
              <button
                type="button"
                className="secondary"
                disabled={!data.url || !data.has_token_secret}
                onClick={() =>
                  confirm("Test BookStack connection", "Test", async (reason) => {
                    const result = await platformApi.post<{ ok: boolean; message: string }>("/docs-sync/test", { reason, confirmed: true });
                    if (!result.ok) throw new ApiError(502, result.message);
                    return result.message;
                  })
                }
              >
                Test connection
              </button>
            </div>
          </form>
          {data.connection && !data.connection.ok && <p className="cc-service-action">{data.connection.message}</p>}
        </CcCard>

        <CcCard title="Destination shelf" description="Shelves visible to the API token. Each docs/ folder becomes a managed book within the selected shelf; changing shelf never alters earlier content.">
          <div className="cc-monitor-form">
            <label>
              Shelf
              <select value={shelfId} onChange={(e) => setShelfId(e.target.value)} aria-label="Destination shelf">
                <option value="">{shelves ? "Select a shelf" : data.shelf_name ?? "Refresh to load shelves"}</option>
                {(shelves ?? []).map((shelf) => (
                  <option key={shelf.id} value={shelf.id}>
                    {shelf.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="cc-monitor-actions">
              <button type="button" className="secondary" disabled={!data.has_token_secret} onClick={() => void refreshShelves()}>
                Refresh shelves
              </button>
              <button
                type="button"
                disabled={!shelves || !shelfId || Number(shelfId) === data.shelf_id}
                onClick={() =>
                  confirm("Set destination shelf", "Save", async (reason) => {
                    const result = await platformApi.put<{ shelf_name: string }>("/docs-sync/shelf", {
                      shelf_id: Number(shelfId),
                      reason,
                      confirmed: true,
                    });
                    return `Destination set to ${result.shelf_name}.`;
                  })
                }
              >
                Use this shelf
              </button>
            </div>
          </div>
        </CcCard>

        <CcCard
          title="Synchronisation"
          actions={<CcBadge tone={data.auto_enabled ? "success" : "neutral"}>{data.auto_enabled ? "Automatic" : "Manual only"}</CcBadge>}
        >
          <CcMetadataGrid dense>
            <CcMetadataItem label="Destination shelf">{data.shelf_name ?? "Not selected"}</CcMetadataItem>
            <CcMetadataItem label="Documents in this build">
              {data.source.available ? data.source.documents : data.source.error}
            </CcMetadataItem>
            <CcMetadataItem label="Last successful sync">
              {data.last_success_at ? relativeTime(data.last_success_at) : "Never"}
            </CcMetadataItem>
            <CcMetadataItem label="Last run">
              {last ? `${last.status} (${last.trigger}) ${relativeTime(last.finished_at)}` : "Never"}
            </CcMetadataItem>
            <CcMetadataItem label="Created / updated / skipped">
              {last && last.status === "succeeded" ? `${last.created} / ${last.updated} / ${last.skipped}` : "—"}
            </CcMetadataItem>
            <CcMetadataItem label="Pending">
              {data.sync_requested ? "Sync queued" : data.changes_pending ? "Changes not yet published" : "Up to date"}
            </CcMetadataItem>
          </CcMetadataGrid>
          {last?.status === "failed" && last.error && <CcNotice tone="error">{last.error}</CcNotice>}
          <div className="cc-monitor-actions">
            <button
              type="button"
              className="secondary"
              disabled={!data.configured}
              onClick={() =>
                confirm(data.auto_enabled ? "Disable automatic sync" : "Enable automatic sync", "Save", async (reason) => {
                  await platformApi.put("/docs-sync/auto", { enabled: !data.auto_enabled, reason, confirmed: true });
                  return data.auto_enabled ? "Automatic sync disabled." : "Automatic sync enabled.";
                })
              }
            >
              {data.auto_enabled ? "Disable automatic sync" : "Enable automatic sync"}
            </button>
            <button
              type="button"
              disabled={!data.configured || data.sync_requested}
              onClick={() =>
                confirm("Sync documentation now", "Sync now", async (reason) => {
                  await platformApi.post("/docs-sync/sync", { reason, confirmed: true });
                  return "Sync queued; it runs in the background within about 30 seconds.";
                })
              }
            >
              Sync now
            </button>
            <button type="button" className="secondary" onClick={() => void load()}>
              Refresh status
            </button>
          </div>
        </CcCard>

        <CcConfirmDialog
          open={pending !== null}
          onClose={() => setPending(null)}
          title={pending?.title ?? ""}
          confirmLabel={pending?.confirm ?? "Confirm"}
          onConfirm={submit}
        />
      </CcPage>
    </PlatformShell>
  );
}
