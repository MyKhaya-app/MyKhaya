"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import {
  type LegalDocument,
  audienceLabel,
  documentScopeLabel,
  versionStatusLabel,
  versionStatusTone,
} from "@/components/legal-logic";

export default function LegalOverviewPage() {
  const [documents, setDocuments] = useState<LegalDocument[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    platformApi
      .get<LegalDocument[]>("/legal/documents")
      .then(setDocuments)
      .catch((cause: Error) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : "Could not load legal documents.",
        ),
      );
  }, []);

  const total = documents?.length ?? 0;
  const published =
    documents?.filter((doc) => doc.published_version).length ?? 0;
  const drafts = documents?.filter((doc) => doc.draft_version).length ?? 0;
  const reacceptanceRequired =
    documents?.filter(
      (doc) =>
        doc.published_version?.reacceptance_scope === "all_existing_users",
    ).length ?? 0;

  const columns: CcTableColumn<LegalDocument>[] = [
    {
      key: "document",
      header: "Document",
      render: (row) => (
        <Link className="table-link" href={`/legal/documents/${row.id}`}>
          {row.display_name}
        </Link>
      ),
    },
    {
      key: "audience",
      header: "Audience",
      render: (row) => audienceLabel(row.audience),
    },
    {
      key: "scope",
      header: "Scope",
      render: (row) => (
        <CcBadge tone={row.scope === "founding_beta" ? "info" : "neutral"}>
          {documentScopeLabel(row.scope)}
        </CcBadge>
      ),
    },
    {
      key: "current",
      header: "Current version",
      render: (row) => row.published_version?.version ?? "—",
    },
    {
      key: "status",
      header: "Status",
      render: (row) =>
        row.published_version ? (
          <CcBadge tone={versionStatusTone(row.published_version.status)}>
            {versionStatusLabel(row.published_version.status)}
          </CcBadge>
        ) : (
          <CcBadge tone="neutral">Not published</CcBadge>
        ),
    },
    {
      key: "effective",
      header: "Effective",
      render: (row) => row.published_version?.effective_date ?? "—",
    },
    {
      key: "draft",
      header: "Draft",
      render: (row) =>
        row.draft_version ? (
          <CcBadge tone="warning">Draft v{row.draft_version.version}</CcBadge>
        ) : (
          "—"
        ),
    },
    {
      key: "acceptance",
      header: "Acceptance",
      render: (row) => (row.acceptance_required ? "Required" : "Not required"),
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <Link className="table-link" href={`/legal/documents/${row.id}`}>
          {row.draft_version
            ? "Edit draft"
            : row.published_version
              ? "View"
              : "Create version"}
        </Link>
      ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide className="cc-legal-overview">
        <CcPageHeader
          eyebrow="Legal & Compliance"
          title="Overview"
          description="PCC is the source of truth for MyKhaya's legal and privacy documents."
          primaryAction={
            <Link
              href="/legal/documents/new"
              className="cc-action cc-action-primary"
            >
              New document
            </Link>
          }
        />
        <CcLegalSubnav />
        {error && (
          <CcNotice tone="error">
            Unable to load legal documents: {error}
          </CcNotice>
        )}
        <div className="cc-legal-cards">
          <div className="cc-legal-card">
            <strong>{documents ? total : "—"}</strong>
            <span>Legal documents</span>
          </div>
          <div className="cc-legal-card">
            <strong>{documents ? published : "—"}</strong>
            <span>Published</span>
          </div>
          <div className="cc-legal-card">
            <strong>{documents ? drafts : "—"}</strong>
            <span>Drafts in progress</span>
          </div>
          <div className="cc-legal-card">
            <strong>{documents ? reacceptanceRequired : "—"}</strong>
            <span>Re-acceptance required</span>
          </div>
        </div>
        <CcTable
          columns={columns}
          rows={documents}
          rowKey={(row) => row.id}
          emptyMessage="No legal documents have been created yet."
          caption="Legal documents"
        />
      </CcPage>
    </PlatformShell>
  );
}
