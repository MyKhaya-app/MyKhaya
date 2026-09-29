"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, use } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import {
  CcSection,
  CcCard,
  CcColumns,
} from "@/components/control-centre/section";
import {
  CcMetadataGrid,
  CcMetadataItem,
} from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import {
  CcNotice,
  CcEmptyState,
  CcLoadingState,
} from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { CcDangerZone } from "@/components/control-centre/danger-zone";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { LegalMarkdown } from "@/components/legal-markdown";

const LegalMarkdownEditor = dynamic(
  () => import("@/components/legal-markdown-editor").then((mod) => mod.LegalMarkdownEditor),
  { ssr: false, loading: () => <div className="cc-legal-editor-loading">Loading editorâ€¦</div> },
);
import {
  type LegalDocument,
  type LegalDocumentVersionDetail,
  type LegalReacceptanceScope,
  REACCEPTANCE_SCOPE_OPTIONS,
  actionVerbLabel,
  audienceLabel,
  reacceptanceScopeDescription,
  reacceptanceScopeLabel,
  versionStatusLabel,
  versionStatusTone,
} from "@/components/legal-logic";

type AdministratorOption = { id: string; display_name: string };
type Tab = "current" | "draft" | "history";
type DraftView = "edit" | "preview";

function fieldValue(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function suggestNextVersion(current: string | undefined | null): string {
  if (!current) return "1.0";
  const match = current.match(/^(\d+)\.(\d+)$/);
  if (!match) return current;
  return `${match[1]}.${Number(match[2]) + 1}`;
}

export default function LegalDocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [doc, setDoc] = useState<LegalDocument | null>(null);
  const [versions, setVersions] = useState<LegalDocumentVersionDetail[] | null>(
    null,
  );
  const [administrators, setAdministrators] = useState<AdministratorOption[]>(
    [],
  );
  const [tab, setTab] = useState<Tab>("current");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [draftContent, setDraftContent] = useState("");
  const [draftVersionLabel, setDraftVersionLabel] = useState("");
  const [draftEffectiveDate, setDraftEffectiveDate] = useState("");
  const [draftChangeSummary, setDraftChangeSummary] = useState("");
  const [draftView, setDraftView] = useState<DraftView>("edit");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creatingVersion, setCreatingVersion] = useState(false);

  const [publishOpen, setPublishOpen] = useState(false);
  const [publishScope, setPublishScope] =
    useState<LegalReacceptanceScope>("new_users_only");
  const [publishAsTest, setPublishAsTest] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const { guarded, modal: reauthModal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      const [document, versionRows] = await Promise.all([
        platformApi.get<LegalDocument>(`/legal/documents/${id}`),
        platformApi.get<LegalDocumentVersionDetail[]>(
          `/legal/documents/${id}/versions`,
        ),
      ]);
      setDoc(document);
      setVersions(versionRows);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not load this document.",
      );
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Owner-only endpoint — degrades to raw ids in the history table for a
    // non-owner viewer, matching the support-ticket detail page's precedent.
    platformApi
      .get<AdministratorOption[]>("/administrators")
      .then(setAdministrators)
      .catch(() => setAdministrators([]));
  }, []);

  const draftSummary = doc?.draft_version ?? null;
  const draftFull = versions?.find((v) => v.id === draftSummary?.id) ?? null;
  const publishedSummary = doc?.published_version ?? null;
  const publishedFull =
    versions?.find((v) => v.id === publishedSummary?.id) ?? null;

  const syncedDraftId = useRef<string | null>(null);
  useEffect(() => {
    if (draftFull && syncedDraftId.current !== draftFull.id) {
      setDraftContent(draftFull.content_markdown);
      setDraftVersionLabel(draftFull.version);
      setDraftEffectiveDate(draftFull.effective_date ?? "");
      setDraftChangeSummary(draftFull.change_summary ?? "");
      setDirty(false);
      syncedDraftId.current = draftFull.id;
    }
    if (!draftFull) syncedDraftId.current = null;
  }, [draftFull]);

  // Standard browser tab-close/reload warning (not a custom confirm()) so a
  // long policy edit isn't lost to an accidental navigation — see §10 of
  // the Phase 2 brief.
  useEffect(() => {
    if (!dirty) return;
    function handler(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  function administratorName(adminId: string | null): string {
    if (!adminId) return "—";
    return (
      administrators.find((admin) => admin.id === adminId)?.display_name ??
      "Administrator"
    );
  }

  async function createVersion() {
    if (!doc) return;
    setCreatingVersion(true);
    setError("");
    try {
      await platformApi.post(`/legal/documents/${id}/versions`, {
        content_markdown:
          publishedFull?.content_markdown ??
          `# ${doc.display_name}\n\nDraft content.`,
        version: suggestNextVersion(publishedSummary?.version),
      });
      setMessage("Draft created.");
      setTab("draft");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not create a new version.",
      );
    } finally {
      setCreatingVersion(false);
    }
  }

  async function saveDraft() {
    if (!draftFull) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await platformApi.patch(
        `/legal/documents/${id}/versions/${draftFull.id}`,
        {
          content_markdown: draftContent,
          version: draftVersionLabel,
          change_summary: draftChangeSummary.trim() || null,
          effective_date: draftEffectiveDate || null,
        },
      );
      setMessage("Draft saved.");
      setDirty(false);
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not save this draft.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function discardDraft() {
    if (!draftFull) return;
    setError("");
    try {
      await platformApi.delete(
        `/legal/documents/${id}/versions/${draftFull.id}`,
      );
      setDiscardOpen(false);
      setMessage("Draft discarded. The published version was not affected.");
      setDirty(false);
      setTab("current");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not discard this draft.",
      );
      setDiscardOpen(false);
    }
  }

  const publishAction = guarded(
    async (scope: LegalReacceptanceScope, reason: string, isTest: boolean) => {
      if (!draftFull) return;
      await platformApi.post(
        `/legal/documents/${id}/versions/${draftFull.id}/publish`,
        {
          reacceptance_scope: scope,
          reason,
          ...(isTest ? { is_test: true } : {}),
        },
      );
      setPublishOpen(false);
      setPublishAsTest(false);
      setMessage("Version published.");
      setDirty(false);
      setTab("current");
      await load();
    },
  );

  async function submitPublish(formData: FormData) {
    setError("");
    const scope = (fieldValue(formData, "reacceptance_scope") ||
      "new_users_only") as LegalReacceptanceScope;
    const reason = fieldValue(formData, "audit_reason");
    const isTest = formData.get("is_test") === "on";
    try {
      await publishAction(scope, reason, isTest);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not publish this version.",
      );
    }
  }

  const archiveAction = guarded(async (reason: string) => {
    await platformApi.post(`/legal/documents/${id}/archive`, { reason });
    setArchiveOpen(false);
    setMessage("Document archived.");
    await load();
  });

  async function submitArchive(formData: FormData) {
    setError("");
    const reason = fieldValue(formData, "audit_reason");
    try {
      await archiveAction(reason);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not archive this document.",
      );
    }
  }

  const historyColumns: CcTableColumn<LegalDocumentVersionDetail>[] = [
    {
      key: "version",
      header: "Version",
      render: (row) => (
        <Link
          className="table-link"
          href={`/legal/documents/${id}/versions/${row.id}`}
        >
          v{row.version}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <CcBadge tone={versionStatusTone(row.status)}>
          {versionStatusLabel(row.status)}
        </CcBadge>
      ),
    },
    {
      key: "effective",
      header: "Effective",
      render: (row) => row.effective_date ?? "—",
    },
    {
      key: "published",
      header: "Published",
      render: (row) => readableDate(row.published_at),
    },
    {
      key: "published_by",
      header: "Published by",
      render: (row) => administratorName(row.published_by_administrator_id),
    },
    {
      key: "acceptance",
      header: "Acceptance",
      render: (row) => row.acceptance_count,
    },
    {
      key: "summary",
      header: "Change summary",
      render: (row) => (
        <span
          className="cc-table-truncate"
          title={row.change_summary ?? undefined}
        >
          {row.change_summary ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide className="cc-legal-document-detail">
        <CcPageHeader
          eyebrow="Legal & Compliance"
          title={doc ? doc.display_name : "Legal document"}
          description={
            doc
              ? `${audienceLabel(doc.audience)} · ${actionVerbLabel(doc.action_verb)}${doc.archived_at ? " · Archived" : ""}`
              : undefined
          }
          secondaryActions={
            <>
              <Link href="/legal/documents" className="secondary">
                Back to Documents
              </Link>
              <button className="secondary" onClick={() => void load()}>
                Refresh
              </button>
            </>
          }
        />
        <CcLegalSubnav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}
        {!doc && !error && <CcLoadingState />}
        {reauthModal}

        {doc && (
          <>
            <nav className="cc-legal-tabs" aria-label="Document sections">
              <button
                type="button"
                className={`cc-legal-tab ${tab === "current" ? "cc-legal-tab-active" : ""}`}
                onClick={() => setTab("current")}
              >
                Current
              </button>
              <button
                type="button"
                className={`cc-legal-tab ${tab === "draft" ? "cc-legal-tab-active" : ""}`}
                onClick={() => setTab("draft")}
              >
                Draft{draftSummary ? ` (v${draftSummary.version})` : ""}
              </button>
              <button
                type="button"
                className={`cc-legal-tab ${tab === "history" ? "cc-legal-tab-active" : ""}`}
                onClick={() => setTab("history")}
              >
                Version History
              </button>
            </nav>

            {tab === "current" && (
              <CcColumns ratio="2-1">
                <div>
                  <CcSection title="Current published content">
                    <CcCard>
                      {publishedFull ? (
                        <LegalMarkdown
                          content={publishedFull.content_markdown}
                          className="cc-legal-prose"
                        />
                      ) : (
                        <CcEmptyState>
                          This document has never been published.
                        </CcEmptyState>
                      )}
                    </CcCard>
                  </CcSection>
                </div>
                <div>
                  <CcSection title="Status">
                    <CcCard>
                      <CcMetadataGrid dense>
                        <CcMetadataItem label="Version">
                          {publishedSummary
                            ? `v${publishedSummary.version}`
                            : "—"}
                        </CcMetadataItem>
                        <CcMetadataItem label="Status">
                          {publishedSummary ? (
                            <CcBadge
                              tone={versionStatusTone(publishedSummary.status)}
                            >
                              {versionStatusLabel(publishedSummary.status)}
                            </CcBadge>
                          ) : (
                            <CcBadge tone="neutral">Not published</CcBadge>
                          )}
                        </CcMetadataItem>
                        <CcMetadataItem label="Effective date">
                          {publishedSummary?.effective_date ?? "—"}
                        </CcMetadataItem>
                        <CcMetadataItem label="Published">
                          {readableDate(publishedSummary?.published_at)}
                        </CcMetadataItem>
                        <CcMetadataItem label="Acceptance">
                          {doc.acceptance_required
                            ? "Required"
                            : "Not required"}
                        </CcMetadataItem>
                        <CcMetadataItem label="Re-acceptance scope">
                          {publishedSummary
                            ? reacceptanceScopeLabel(
                                publishedSummary.reacceptance_scope,
                              )
                            : "—"}
                        </CcMetadataItem>
                        <CcMetadataItem label="Recorded acceptances">
                          {publishedSummary?.acceptance_count ?? 0}
                        </CcMetadataItem>
                        {publishedSummary?.change_summary && (
                          <CcMetadataItem label="Change summary" span>
                            {publishedSummary.change_summary}
                          </CcMetadataItem>
                        )}
                      </CcMetadataGrid>
                      <div className="cc-legal-document-form-actions">
                        {draftSummary ? (
                          <button
                            type="button"
                            className="cc-action cc-action-primary"
                            onClick={() => setTab("draft")}
                          >
                            Continue editing draft v{draftSummary.version}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="cc-action cc-action-primary"
                            onClick={() => void createVersion()}
                            disabled={creatingVersion}
                          >
                            {creatingVersion
                              ? "Creating…"
                              : publishedSummary
                                ? "Create new version"
                                : "Create first version"}
                          </button>
                        )}
                      </div>
                    </CcCard>
                  </CcSection>

                  {!doc.archived_at && (
                    <CcDangerZone
                      title="Archive"
                      description="Archiving hides this document from new signup/consent flows. Historical versions and acceptance records are kept."
                    >
                      <button
                        type="button"
                        className="danger"
                        onClick={() => setArchiveOpen(true)}
                      >
                        Archive document
                      </button>
                    </CcDangerZone>
                  )}
                </div>
              </CcColumns>
            )}

            {tab === "draft" &&
              (draftFull ? (
                <>
                  {publishedSummary && (
                    <div className="cc-legal-draft-banner" role="status">
                      <span>
                        Editing draft v{draftFull.version}. The published
                        version (v
                        {publishedSummary.version}) is untouched until you
                        publish.
                      </span>
                      {dirty && <strong>Unsaved changes</strong>}
                    </div>
                  )}
                  <CcSection
                    title={`Draft v${draftFull.version}`}
                    description={`Last edited ${readableDate(draftFull.updated_at)}`}
                    actions={
                      <>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => setDiscardOpen(true)}
                        >
                          Discard draft
                        </button>
                        <button
                          type="button"
                          className="cc-action cc-action-primary"
                          onClick={() => void saveDraft()}
                          disabled={saving}
                        >
                          {saving ? "Saving…" : "Save draft"}
                        </button>
                        <button
                          type="button"
                          className="cc-action"
                          onClick={() => {
                            setPublishScope("new_users_only");
                            setPublishAsTest(false);
                            setPublishOpen(true);
                          }}
                        >
                          Publish version
                        </button>
                      </>
                    }
                  >
                    <div className="cc-legal-editor-fields">
                      <label>
                        Version label
                        <input
                          value={draftVersionLabel}
                          onChange={(event) => {
                            setDraftVersionLabel(event.target.value);
                            setDirty(true);
                          }}
                          maxLength={20}
                        />
                      </label>
                      <label>
                        Effective date
                        <input
                          type="date"
                          value={draftEffectiveDate}
                          onChange={(event) => {
                            setDraftEffectiveDate(event.target.value);
                            setDirty(true);
                          }}
                        />
                      </label>
                      <label>
                        Change summary
                        <input
                          value={draftChangeSummary}
                          onChange={(event) => {
                            setDraftChangeSummary(event.target.value);
                            setDirty(true);
                          }}
                          maxLength={2000}
                          placeholder="Optional — what changed in this version"
                        />
                      </label>
                    </div>
                    <div className="cc-legal-editor-mode-tabs" role="tablist" aria-label="Draft content view">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={draftView === "edit"}
                        className={draftView === "edit" ? "active" : ""}
                        onClick={() => setDraftView("edit")}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={draftView === "preview"}
                        className={draftView === "preview" ? "active" : ""}
                        onClick={() => setDraftView("preview")}
                      >
                        Preview
                      </button>
                    </div>
                    {draftView === "edit" ? (
                      <div className="cc-legal-content-field">
                        <label htmlFor="legal-draft-content">Document content</label>
                        <LegalMarkdownEditor
                          key={draftFull.id}
                          markdown={draftContent}
                          onChange={(value) => {
                            setDraftContent(value);
                            setDirty(true);
                          }}
                        />
                      </div>
                    ) : (
                      <div className="cc-legal-preview-frame cc-legal-editor-preview">
                        <p className="cc-legal-preview-label">Consumer preview</p>
                        <LegalMarkdown content={draftContent} className="cc-legal-prose" />
                      </div>
                    )}
                  </CcSection>
                </>
              ) : (
                <CcEmptyState>
                  No draft is open.{" "}
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => void createVersion()}
                  >
                    Create a new version
                  </button>{" "}
                  to start one.
                </CcEmptyState>
              ))}

            {tab === "history" && (
              <CcSection
                title="Version history"
                description="Published and superseded versions are read-only."
              >
                <CcTable
                  columns={historyColumns}
                  rows={versions}
                  rowKey={(row) => row.id}
                  emptyMessage="No versions yet."
                  caption="Version history"
                />
              </CcSection>
            )}
          </>
        )}

        <CcConfirmDialog
          open={publishOpen}
          onClose={() => setPublishOpen(false)}
          title={
            doc
              ? `${publishAsTest ? "Publish TEST version of" : "Publish"} ${doc.display_name} v${draftVersionLabel}`
              : "Publish version"
          }
          description={
            doc && draftFull ? (
              <>
                Effective date:{" "}
                <strong>{draftEffectiveDate || "Immediately"}</strong>. Once
                published, this exact content and version become immutable —
                further edits create a new draft.
              </>
            ) : undefined
          }
          confirmLabel={publishAsTest ? "Publish TEST version" : "Publish version"}
          reasonLabel="Reason for publishing (at least 10 characters)"
          reasonHint="This reason is retained in the administrative audit trail."
          extraFields={
            <fieldset className="cc-legal-scope-fieldset">
              <legend>Re-acceptance scope</legend>
              {REACCEPTANCE_SCOPE_OPTIONS.map((scope) => (
                <label key={scope} className="cc-legal-scope-option">
                  <input
                    type="radio"
                    name="reacceptance_scope"
                    value={scope}
                    checked={publishScope === scope}
                    onChange={() => setPublishScope(scope)}
                  />
                  <span>
                    <strong>{reacceptanceScopeLabel(scope)}</strong>
                    <span>{reacceptanceScopeDescription(scope)}</span>
                  </span>
                </label>
              ))}
              {publishScope === "all_existing_users" && (
                <CcNotice tone="warning">
                  This version requires existing applicable users to complete
                  the required legal action. Enforcement in the consumer app is
                  delivered in a later phase.
                </CcNotice>
              )}
                <label className="cc-legal-test-option">
                  <input
                    type="checkbox"
                    name="is_test"
                    checked={publishAsTest}
                    onChange={(event) => setPublishAsTest(event.target.checked)}
                  />
                <span>
                  <strong>Publish as TEST VERSION</strong>
                    <span>Not legally active. Available only to designated Legal Test Mode users and excluded from public policy pages.</span>
                </span>
              </label>
            </fieldset>
          }
          onConfirm={submitPublish}
        />

        <CcConfirmDialog
          open={archiveOpen}
          onClose={() => setArchiveOpen(false)}
          title={doc ? `Archive ${doc.display_name}` : "Archive document"}
          description="This hides the document from new signup/consent flows. Historical versions and every acceptance record are kept."
          confirmLabel="Archive document"
          variant="destructive"
          onConfirm={submitArchive}
        />

        <CcConfirmDialogSimple
          open={discardOpen}
          onClose={() => setDiscardOpen(false)}
          title={
            draftFull ? `Discard draft v${draftFull.version}` : "Discard draft"
          }
          description="This removes the unpublished draft. The currently published version will not be affected."
          confirmLabel="Discard draft"
          onConfirm={() => void discardDraft()}
        />
      </CcPage>
    </PlatformShell>
  );
}

/**
 * A confirmation dialog without the mandatory audit-reason field — discard
 * isn't a recent-auth-gated action (unlike publish/archive) and doesn't
 * change any published or historical record, so the heavier
 * `CcConfirmDialog` reason requirement would just be friction here.
 */
function CcConfirmDialogSimple({
  open,
  onClose,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="platform-modal-backdrop cc-dialog-backdrop"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="platform-modal cc-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="cc-dialog-header">
          <h2>{title}</h2>
        </div>
        <div className="cc-dialog-scroll">
          <p>{description}</p>
        </div>
        <div className="platform-modal-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
