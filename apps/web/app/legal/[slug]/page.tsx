"use client";

import { useEffect, useState, use } from "react";
import { ApiError, api, type PublicLegalDocumentContent } from "@mykhaya/api-client";
import { PublicHeader } from "@/components/marketing/public-header";
import { PublicFooter } from "@/components/marketing/public-footer";
import { LegalMarkdown } from "@/components/legal-markdown";

// Stable, memorable public URLs (§2 of the Phase 3 brief) mapped to the
// backend's actual document keys — "children" reads better in a URL than
// "children_privacy", but the backend key is the source of truth for
// which document that is, not this route.
const SLUG_TO_KEY: Record<string, string> = {
  terms: "terms",
  privacy: "privacy",
  children: "children_privacy",
  cookies: "cookies",
  // Already linked from registration and Beta enrolment; previously unmapped,
  // so the link rendered "Document not found".
  "founding-beta-terms": "founding_beta_terms",
};

function readableDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(date);
}

export default function PublicLegalDocumentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const key = SLUG_TO_KEY[slug];
  const [document, setDocument] = useState<PublicLegalDocumentContent | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!key) return;
    setDocument(null);
    setError("");
    api
      .publicLegalDocument(key)
      .then(setDocument)
      .catch((cause: unknown) =>
        setError(
          cause instanceof ApiError && cause.status === 404
            ? "not_published"
            : "This document could not be loaded right now. Please try again shortly.",
        ),
      );
  }, [key]);

  return (
    <>
      <PublicHeader />
      <main className="standard-page legal-document-page">
        {!key && (
          <div className="page-heading">
            <h1>Document not found</h1>
            <p className="muted">That legal document doesn&rsquo;t exist.</p>
          </div>
        )}
        {key && !document && !error && (
          <p role="status" className="muted">
            Loading…
          </p>
        )}
        {key && error === "not_published" && (
          <div className="page-heading">
            <h1>Not yet available</h1>
            <p className="muted">
              This document hasn&rsquo;t been published yet. Please check back shortly, or{" "}
              <a href="/help-support">contact support</a> if you need it urgently.
            </p>
          </div>
        )}
        {key && error && error !== "not_published" && (
          <div className="page-heading">
            <h1>Something went wrong</h1>
            <p className="muted">{error}</p>
          </div>
        )}
        {document && (
          <>
            <div className="page-heading">
              <h1>{document.display_name}</h1>
              <p className="legal-meta">
                Version {document.version}
                {readableDate(document.effective_date) &&
                  ` · Effective ${readableDate(document.effective_date)}`}
                {readableDate(document.published_at) &&
                  ` · Last updated ${readableDate(document.published_at)}`}
              </p>
            </div>
            <LegalMarkdown content={document.content_markdown} className="legal-prose" />
          </>
        )}
      </main>
      <PublicFooter />
    </>
  );
}
