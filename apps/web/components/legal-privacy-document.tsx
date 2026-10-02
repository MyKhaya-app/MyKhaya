"use client";

import { useEffect, useState } from "react";
import { ApiError, api, type PublicLegalDocumentContent } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { LegalMarkdown } from "@/components/legal-markdown";
import { type LegalRowPresentation, legalReadableDate, presentAdultLegalStatus, presentGuardianLegalStatus } from "@/components/legal-status-presentation";

export function LegalPrivacyDocument({ documentKey }: { documentKey: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [content, setContent] = useState<PublicLegalDocumentContent | null>(null);
  const [presentation, setPresentation] = useState<LegalRowPresentation | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
    setContent(null);
    setPresentation(null);
    setError("");
    api.publicLegalDocument(documentKey).then(setContent).catch((cause: unknown) => setError(cause instanceof ApiError && cause.status === 404 ? "This document has not been published yet." : "This document could not be loaded right now."));
    api.legalStatus().then((status) => {
      if (user?.principal_type === "managed_child") {
        const entry = status.child_self?.child_acknowledgement;
        if (entry?.document_key === documentKey) setPresentation(presentAdultLegalStatus(entry));
        return;
      }
      const entry = status.documents.find((item) => item.document_key === documentKey);
      if (entry) {
        setPresentation(presentAdultLegalStatus(entry));
        return;
      }
      const guardianEntries = status.children.filter((child) => child.document_key === documentKey && child.guardian_authorisation).map((child) => child.guardian_authorisation!);
      if (guardianEntries.length) setPresentation(presentGuardianLegalStatus(guardianEntries));
    }).catch(() => undefined);
  }, [documentKey, user?.principal_type]);

  return <>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!content && !error && <p role="status" className="muted">Loading…</p>}
    {content && <section className="card"><p className="legal-meta">Version {content.version}{legalReadableDate(content.effective_date) && ` · Effective ${legalReadableDate(content.effective_date)}`}</p><div className="legal-reader-status"><span className={`legal-status-pill ${presentation?.tone ?? "neutral"}`}>{presentation?.label ?? "Current version"}</span>{presentation?.dateLabel && <span className="legal-status-date">{presentation.dateLabel}</span>}</div><LegalMarkdown content={content.content_markdown} className="legal-prose" /></section>}
  </>;
}
