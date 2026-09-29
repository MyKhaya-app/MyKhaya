"use client";

import { SettingsPage } from "@/components/settings-page";
import { LegalPrivacyContent } from "@/components/legal-privacy-content";
import { LegalPrivacyDocument } from "@/components/legal-privacy-document";
import { useSearchParams } from "next/navigation";

export default function LegalPrivacyPage() {
  const documentKey = useSearchParams().get("document");
  return (
    <SettingsPage
      title={documentKey ? "Legal document" : "Legal & Privacy"}
      description={documentKey ? undefined : "Review MyKhaya's current legal notices and the versions recorded for your account."}
      backLink={{ href: documentKey ? "/settings/legal" : "/settings", label: documentKey ? "Back to Legal & Privacy" : "Back to More" }}
    >
      {documentKey ? <LegalPrivacyDocument documentKey={documentKey} /> : <LegalPrivacyContent />}
    </SettingsPage>
  );
  /*
  const [documents, setDocuments] = useState<PublicLegalDocumentSummary[]>([]);
  const [status, setStatus] = useState<LegalStatusResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.publicLegalDocuments(), api.legalStatus()])
      .then(([published, current]) => {
        setDocuments(published);
        setStatus(current);
      })
      .catch(() => setError("Legal information could not be loaded right now."));
  }, []);

  const childDocument = status?.child_self?.child_acknowledgement;
  return (
    <SettingsPage
      title="Legal & Privacy"
      description="Review MyKhaya's current legal notices and the versions recorded for your account."
      backLink={{ href: "/settings", label: "Back to More" }}
    >
      {error && <p className="notice error" role="alert">{error}</p>}
      <section className="card legal-settings-card">
        <h2>Current documents</h2>
        <div className="settings-list">
          {documents.map((document) => (
            <div className="settings-row" key={document.key}>
              <div>
                <h3>{document.display_name}</h3>
                <p className="muted">
                  Version {document.current_version ?? "not published"} · effective {readableDate(document.effective_date)}
                </p>
              </div>
              <a href={links[document.key] ?? `/legal/${document.key}`}>Read</a>
            </div>
          ))}
        </div>
      </section>
      {status && status.documents.length > 0 && (
        <section className="card legal-settings-card">
          <h2>Your recorded versions</h2>
          <div className="settings-list">
            {status.documents.map((document) => (
              <div className="settings-row" key={document.document_key}>
                <div>
                  <h3>{document.display_name}</h3>
                  <p className="muted">
                    {document.satisfied ? "Current" : "Action required"} · last recorded version {document.last_version_label ?? "none"}
                  </p>
                </div>
                {document.last_version_id && (
                  <a href={`/api/v1/legal/versions/${encodeURIComponent(document.last_version_id)}`}>
                    View recorded version
                  </a>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
      {childDocument && (
        <section className="card legal-settings-card">
          <h2>Child privacy</h2>
          <p className="muted">
            This child sign-in sees the child-friendly privacy notice only. Adult Terms and contract documents are not applied to managed-child accounts.
          </p>
          <a href="/legal/children">Read the Family & Children&apos;s Privacy Notice</a>
        </section>
      )}
    </SettingsPage>
  );
  */
}
