"use client";

import { useEffect, useState, use } from "react";
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
  CcLoadingState,
} from "@/components/control-centre/status-message";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import { LegalMarkdown } from "@/components/legal-markdown";
import {
  type LegalDocument,
  type LegalDocumentVersionDetail,
  reacceptanceScopeLabel,
  versionStatusLabel,
  versionStatusTone,
} from "@/components/legal-logic";

export default function LegalVersionDetailPage({
  params,
}: {
  params: Promise<{ id: string; versionId: string }>;
}) {
  const { id, versionId } = use(params);
  const [doc, setDoc] = useState<LegalDocument | null>(null);
  const [version, setVersion] = useState<LegalDocumentVersionDetail | null>(
    null,
  );
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    Promise.all([
      platformApi.get<LegalDocument>(`/legal/documents/${id}`),
      platformApi.get<LegalDocumentVersionDetail[]>(
        `/legal/documents/${id}/versions`,
      ),
    ])
      .then(([document, versions]) => {
        setDoc(document);
        const found = versions.find((row) => row.id === versionId);
        if (!found) {
          setError("That version could not be found.");
          return;
        }
        setVersion(found);
      })
      .catch((cause: Error) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : "Could not load this version.",
        ),
      );
  }, [id, versionId]);

  return (
    <PlatformShell>
      <CcPage wide className="cc-legal-version-detail">
        <CcPageHeader
          eyebrow="Legal & Compliance"
          title={
            doc
              ? `${doc.display_name} — v${version?.version ?? ""}`
              : "Historical version"
          }
          description="Historical version — read only. This exact content is what was in force during the dates shown."
          secondaryActions={
            <Link href={`/legal/documents/${id}`} className="secondary">
              Back to document
            </Link>
          }
        />
        <CcLegalSubnav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {!doc && !error && <CcLoadingState />}

        {doc && version && (
          <CcColumns ratio="2-1">
            <div>
              <CcSection title="Content">
                <CcCard>
                  <LegalMarkdown content={version.content_markdown} className="cc-legal-prose" />
                </CcCard>
              </CcSection>
            </div>
            <div>
              <CcSection title="Metadata">
                <CcCard>
                  <CcMetadataGrid dense>
                    <CcMetadataItem label="Version">
                      v{version.version}
                    </CcMetadataItem>
                    <CcMetadataItem label="Status">
                      <CcBadge tone={versionStatusTone(version.status)}>
                        {versionStatusLabel(version.status)}
                      </CcBadge>
                      {version.is_test && <CcBadge tone="warning">TEST VERSION · Not legally active</CcBadge>}
                    </CcMetadataItem>
                    <CcMetadataItem label="Effective date">
                      {version.effective_date ?? "—"}
                    </CcMetadataItem>
                    <CcMetadataItem label="Published">
                      {readableDate(version.published_at)}
                    </CcMetadataItem>
                    {version.superseded_at && (
                      <CcMetadataItem label="Superseded">
                        {readableDate(version.superseded_at)}
                      </CcMetadataItem>
                    )}
                    <CcMetadataItem label="Re-acceptance scope">
                      {reacceptanceScopeLabel(version.reacceptance_scope)}
                    </CcMetadataItem>
                    <CcMetadataItem label="Recorded acceptances">
                      {version.acceptance_count}
                    </CcMetadataItem>
                    {version.change_summary && (
                      <CcMetadataItem label="Change summary" span>
                        {version.change_summary}
                      </CcMetadataItem>
                    )}
                  </CcMetadataGrid>
                </CcCard>
              </CcSection>
            </div>
          </CcColumns>
        )}
      </CcPage>
    </PlatformShell>
  );
}
