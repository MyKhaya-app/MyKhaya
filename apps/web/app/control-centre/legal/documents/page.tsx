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
  actionVerbLabel,
  audienceLabel,
  versionStatusLabel,
  versionStatusTone,
} from "@/components/legal-logic";

export default function LegalDocumentsPage() {
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
    { key: "key", header: "Key", render: (row) => <code>{row.key}</code> },
    {
      key: "audience",
      header: "Audience",
      render: (row) => audienceLabel(row.audience),
    },
    {
      key: "verb",
      header: "Action",
      render: (row) => actionVerbLabel(row.action_verb),
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
      key: "acceptance",
      header: "Acceptance",
      render: (row) => (row.acceptance_required ? "Required" : "Not required"),
    },
    {
      key: "draft",
      header: "Draft",
      render: (row) =>
        row.draft_version ? `v${row.draft_version.version}` : "—",
    },
    {
      key: "archived",
      header: "State",
      render: (row) =>
        row.archived_at ? <CcBadge tone="neutral">Archived</CcBadge> : "Active",
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
      <CcPage wide className="cc-legal-documents">
        <CcPageHeader
          eyebrow="Legal & Compliance"
          title="Documents"
          description="Terms, privacy policies and other legal document types managed through PCC."
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
        <CcTable
          columns={columns}
          rows={documents}
          rowKey={(row) => row.id}
          emptyMessage="No legal documents have been created yet."
          caption="Legal documents table"
        />
      </CcPage>
    </PlatformShell>
  );
}
