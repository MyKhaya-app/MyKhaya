"use client";

import { useEffect, useState, use } from "react";
import { ApiError, api, type PublicLegalDocumentContent } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { SettingsPage } from "@/components/settings-page";
import { LegalMarkdown } from "@/components/legal-markdown";
import {
  type LegalRowPresentation,
  legalReadableDate,
  presentAdultLegalStatus,
  presentGuardianLegalStatus,
} from "@/components/legal-status-presentation";

/**
 * Read-only reader for a single legal document, opened from About MyKhaya's
 * Legal & Compliance card. Reuses the same sanitised Markdown renderer as
 * every other legal surface (PCC, public /legal pages, the legal gate) —
 * see components/legal-markdown.tsx — and shows this account's own
 * recorded status alongside the content, never letting the user alter it.
 */
export default function AboutLegalDocumentPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  const [user, setUser] = useState<User | null>(null);
  const [content, setContent] = useState<PublicLegalDocumentContent | null>(null);
  const [error, setError] = useState("");
  const [presentation, setPresentation] = useState<LegalRowPresentation | null>(null);

  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
    setContent(null);
    setError("");
    setPresentation(null);
    api
      .publicLegalDocument(key)
      .then(setContent)
      .catch((cause: unknown) =>
        setError(
          cause instanceof ApiError && cause.status === 404
            ? "This document has not been published yet."
            : "This document could not be loaded right now.",
        ),
      );
    api
      .legalStatus()
      .then((status) => {
        const isChild = user?.principal_type === "managed_child";
        if (isChild) {
          const ack = status.child_self?.child_acknowledgement;
          if (ack && ack.document_key === key) setPresentation(presentAdultLegalStatus(ack));
          return;
        }
        const adultEntry = status.documents.find((entry) => entry.document_key === key);
        if (adultEntry) {
          setPresentation(presentAdultLegalStatus(adultEntry));
          return;
        }
        const guardianEntries = status.children
          .filter((child) => child.document_key === key && child.guardian_authorisation)
          .map((child) => child.guardian_authorisation!);
        if (guardianEntries.length > 0) {
          setPresentation(presentGuardianLegalStatus(guardianEntries));
        }
      })
      .catch(() => undefined);
  }, [key, user?.principal_type]);

  return (
    <SettingsPage
      title={content?.display_name ?? "Legal document"}
      backLink={{ href: "/about", label: "Back to About MyKhaya" }}
    >
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {!content && !error && (
        <p role="status" className="muted">
          Loading…
        </p>
      )}
      {content && (
        <section className="card">
          <p className="legal-meta">
            Version {content.version}
            {legalReadableDate(content.effective_date) &&
              ` · Effective ${legalReadableDate(content.effective_date)}`}
          </p>
          <div className="legal-reader-status">
            <span className={`legal-status-pill ${presentation?.tone ?? "neutral"}`}>
              {presentation?.tone === "satisfied" && "✓ "}
              {presentation?.label ?? "Current version"}
            </span>
            {presentation?.dateLabel && (
              <span className="legal-status-date">{presentation.dateLabel}</span>
            )}
          </div>
          <LegalMarkdown content={content.content_markdown} className="legal-prose" />
        </section>
      )}
    </SettingsPage>
  );
}
