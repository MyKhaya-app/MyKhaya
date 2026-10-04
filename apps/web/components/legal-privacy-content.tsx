"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Cookie, FileText, Info, Shield, Users } from "lucide-react";
import { api, type LegalDocumentStatus, type LegalStatusResponse, type PublicLegalDocumentSummary } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { LEGAL_DOCUMENT_DESCRIPTION, presentAdultLegalStatus, presentGuardianLegalStatus } from "@/components/legal-status-presentation";

const ICONS: Record<string, typeof FileText> = { terms: FileText, privacy: Shield, children_privacy: Users, cookies: Cookie };

function dateLabel(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function rowsFor(documents: PublicLegalDocumentSummary[], status: LegalStatusResponse, user: User | null) {
  if (user?.principal_type === "managed_child") {
    const document = documents.find((item) => item.key === "children_privacy");
    if (!document) return [];
    const entry = status.child_self?.child_acknowledgement;
    return [{ document, entry, presentation: entry ? presentAdultLegalStatus(entry) : { label: "No version recorded", dateLabel: null, tone: "neutral" as const }, isTest: Boolean(entry?.is_test) }];
  }
  return documents.map((document) => {
    if (document.audience === "adult") {
      const entry = status.documents.find((item) => item.document_key === document.key);
      return { document, entry, presentation: entry ? presentAdultLegalStatus(entry) : { label: "No version recorded", dateLabel: null, tone: "neutral" as const }, isTest: Boolean(entry?.is_test) };
    }
    const entries = status.children.filter((child) => child.document_key === document.key && child.guardian_authorisation).map((child) => child.guardian_authorisation as LegalDocumentStatus);
    return { document, entry: undefined, presentation: presentGuardianLegalStatus(entries), isTest: entries.some((entry) => Boolean(entry.is_test)) };
  });
}

export function LegalPrivacyContent() {
  const [user, setUser] = useState<User | null>(null);
  const [documents, setDocuments] = useState<PublicLegalDocumentSummary[] | null>(null);
  const [status, setStatus] = useState<LegalStatusResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
    Promise.all([api.publicLegalDocuments(), api.legalStatus()]).then(([published, current]) => {
      setDocuments(published);
      setStatus(current);
    }).catch(() => setError("Legal information could not be loaded right now."));
  }, []);

  const rows = documents && status ? rowsFor(documents, status, user) : [];
  return <section className="card legal-privacy-card">
    <div className="section-heading legal-compliance-heading">
      <span className="more-icon-tile sage" aria-hidden="true"><FileText size={20} strokeWidth={1.75} /></span>
      <div><h2>Legal &amp; Privacy</h2><p className="muted">View the legal documents that apply to your account.</p></div>
    </div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!error && (!documents || !status) && <p role="status" className="muted">Loading…</p>}
    {!error && documents && status && rows.length === 0 && <div className="legal-empty-state"><span className="more-icon-tile cream" aria-hidden="true"><FileText size={18} strokeWidth={1.75} /></span><div><h3>No legal documents published yet</h3><p className="muted">Your current legal documents will appear here when they become available.</p></div></div>}
    {rows.length > 0 && <div className="legal-document-rows">{rows.map(({ document, presentation, isTest }) => { const Icon = ICONS[document.key] ?? FileText; return <Link className="legal-document-row" href={`/settings/legal?document=${encodeURIComponent(document.key)}`} key={document.key}>
      <span className="more-icon-tile sage" aria-hidden="true"><Icon size={20} strokeWidth={1.75} /></span>
      <span className="legal-document-row-copy"><strong>{document.display_name}</strong><span>{LEGAL_DOCUMENT_DESCRIPTION[document.key] ?? ""}</span><small>Version {document.current_version ?? "Not published"}{dateLabel(document.effective_date) ? ` · Effective ${dateLabel(document.effective_date)}` : ""}</small></span>
      <span className="legal-document-row-status">{isTest && <span className="legal-status-pill test">TEST</span>}<span className={`legal-status-pill ${presentation.tone}`}>{presentation.label}</span>{presentation.dateLabel && <small>{presentation.dateLabel}</small>}</span>
      <ChevronRight size={19} aria-hidden="true" />
    </Link>; })}</div>}
    <div className="legal-info-panel"><Info size={18} aria-hidden="true" /><div><h3>Keeping you informed</h3><p>We may update these documents from time to time. If an update requires your attention, we&rsquo;ll ask you to review it when you next sign in.</p></div></div>
  </section>;
}
