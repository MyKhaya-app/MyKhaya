"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  type LegalDocumentStatus,
  type PublicLegalDocumentContent,
} from "@mykhaya/api-client";
import { useAuth } from "./auth-provider";
import { LegalMarkdown } from "./legal-markdown";
import { nativeLogout } from "./native-auth";
import { isNativeShell, nativePlatform } from "./native-runtime";
import { Logo } from "./logo";
import { BottomSheet } from "./bottom-sheet";

function platform(): "web" | "ios" | "android" {
  if (!isNativeShell()) return "web";
  const value = nativePlatform();
  return value === "ios" || value === "android" ? value : "web";
}

function readableDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(date);
}

/**
 * One outstanding document within the gate — adult Terms/Privacy
 * (accept/acknowledge) or a child's own Family & Children's Privacy Notice
 * (acknowledge, child-friendly wording). Fetches the exact current
 * published content via the exact-version endpoint. This keeps the content
 * and the version id recorded by the action tied to the same immutable row.
 */
function OutstandingDocument({
  document,
  verbLabel,
  onComplete,
  onSubmit,
  childFriendly = false,
}: {
  document: LegalDocumentStatus;
  verbLabel: string;
  onSubmit: (versionId: string) => Promise<void>;
  onComplete: () => void;
  childFriendly?: boolean;
}) {
  const [content, setContent] = useState<PublicLegalDocumentContent | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!document.current_version_id) return;
    api.legalVersion(document.current_version_id).then(setContent).catch(() => undefined);
  }, [document.current_version_id]);

  async function complete() {
    if (!document.current_version_id) return;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(document.current_version_id);
      onComplete();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "That didn't go through. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="legal-gate-document">
      <div className="legal-gate-document-heading">
        <div>
          <h3>{document.display_name}</h3>
          <p className="legal-gate-version">
            Version: <strong>{content?.version ?? document.current_version_label ?? "—"}</strong>
          </p>
        </div>
        {document.is_test && <span className="legal-test-badge">TEST</span>}
      </div>
      <p className="muted">
        {content?.change_summary
          ? content.change_summary
          : childFriendly
            ? "We've explained what information MyKhaya keeps, who can see it, and what you can do if you have questions."
            : "Please review this document before continuing."}
        {readableDate(document.effective_date) &&
          ` Effective ${readableDate(document.effective_date)}.`}
      </p>
      <button type="button" className="secondary legal-gate-review-button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        {expanded ? "Hide document" : childFriendly ? "Read about my privacy" : "Review document"}
      </button>
      {expanded && (
        <div className="legal-document-reader">
          {content ? (
            <LegalMarkdown content={content.content_markdown} className="legal-prose" />
          ) : (
            <p role="status">Loading…</p>
          )}
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <div className="legal-gate-actions">
        <button type="button" onClick={() => void complete()} disabled={submitting || !content}>
          {submitting ? "Saving…" : verbLabel}
        </button>
      </div>
    </div>
  );
}

/** The full-screen interrupt AppShell renders when useAuth().status is
 * "legal_action_required" — modelled directly on the existing MFA/native-
 * biometric "locked" interrupt (see app-shell.tsx), never a second
 * application shell. Branches entirely on the signed-in identity's own
 * principal_type: an adult never sees a child's acknowledgement flow and a
 * managed child never sees adult Terms/contract wording (§18). */
export function LegalGate() {
  const router = useRouter();
  const { user, legalStatus, refreshLegalStatus, clearSession } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      // Native source of truth: revokes the Keychain-backed bearer session
      // (see components/native-auth.ts), never the browser cookie
      // /auth/logout — matches components/app-header.tsx's own logout().
      if (isNativeShell()) {
        await nativeLogout();
      } else {
        await api.post("/auth/logout", {});
      }
    } catch {
      // Sign-out must still proceed locally even if the network call fails.
    } finally {
      clearSession();
      router.replace("/login");
    }
  }

  if (!user || !legalStatus) {
    return (
      <main className="app-bootstrap-state" role="status">
        Checking your account…
      </main>
    );
  }

  const isChild = user.principal_type === "managed_child";

  if (isChild) {
    const childDoc = legalStatus.child_self?.child_acknowledgement;
    return (
      <main className="legal-gate">
        <div className="card legal-gate-card">
          <div className="legal-gate-brand"><Logo /></div>
          <h1>Your privacy on MyKhaya</h1>
          <p className="muted">
            MyKhaya helps your family organise things together. Before you carry on, take a look
            at how MyKhaya looks after your information.
          </p>
          {childDoc?.is_test && (
            <div className="legal-test-banner" role="status">
              <strong>TEST LEGAL FLOW</strong>
              <span>This is a test version of the MyKhaya legal acceptance experience.</span>
            </div>
          )}
          {childDoc && legalStatus.child_self && (
            <OutstandingDocument
              document={childDoc}
              verbLabel="I've read this"
              childFriendly
              onSubmit={(versionId) =>
                api
                  .acknowledgeChildLegalDocument({
                    document_version_id: versionId,
                    platform: platform(),
                  })
                  .then(() => undefined)
              }
              onComplete={() => void refreshLegalStatus()}
            />
          )}
          <div className="legal-gate-secondary-actions">
            <button type="button" className="danger legal-gate-reject" onClick={() => setRejectOpen(true)} disabled={signingOut}>
              Reject and sign out
            </button>
          </div>
        </div>
        {rejectOpen && (
          <BottomSheet title="Reject updated privacy notice?" onDismiss={() => !signingOut && setRejectOpen(false)}>
            <p>You won&rsquo;t be able to continue until you acknowledge the current privacy notice. You&rsquo;ll be signed out of MyKhaya.</p>
            <div className="legal-gate-confirm-actions">
              <button type="button" className="secondary" onClick={() => setRejectOpen(false)} disabled={signingOut}>
                Cancel
              </button>
              <button type="button" className="danger" onClick={() => void signOut()} disabled={signingOut}>
                {signingOut ? "Signing out…" : "Reject and sign out"}
              </button>
            </div>
          </BottomSheet>
        )}
      </main>
    );
  }

  const outstanding = legalStatus.documents.filter((doc) => doc.required && !doc.satisfied);
  const rejectionTitle = outstanding.length > 1 ? "Reject updated legal documents?" : "Reject updated Terms?";
  const rejectionMessage = outstanding.length > 1
    ? "You won't be able to continue until you accept the current legal documents. You'll be signed out of MyKhaya."
    : "You won't be able to continue until you accept the current Terms. You'll be signed out of MyKhaya.";

  return (
    <main className="legal-gate">
      <div className="card legal-gate-card">
        <div className="legal-gate-brand"><Logo /></div>
        {outstanding.some((doc) => doc.is_test) && (
          <div className="legal-test-banner" role="status">
            <strong>TEST LEGAL FLOW</strong>
            <span>This is a test version of the MyKhaya legal acceptance experience.</span>
          </div>
        )}
        <h1>{outstanding.length > 1 ? "We've updated our legal documents" : "We've updated our Terms"}</h1>
        <p className="muted">
          Please review {outstanding.length > 1 ? "the updated documents" : "the updated Terms"} before continuing.
        </p>
        {outstanding.map((doc) => (
          <OutstandingDocument
            key={doc.document_key}
            document={doc}
            verbLabel={doc.action_verb === "acknowledge" ? "Acknowledge and continue" : "Accept and continue"}
            onSubmit={(versionId) =>
              api
                .acceptLegalDocument({
                  document_key: doc.document_key,
                  document_version_id: versionId,
                  context: "policy_update",
                  platform: platform(),
                })
                .then(() => undefined)
            }
            onComplete={() => void refreshLegalStatus()}
          />
        ))}
        <div className="legal-gate-secondary-actions">
          <button type="button" className="danger legal-gate-reject" onClick={() => setRejectOpen(true)} disabled={signingOut}>
            Reject and sign out
          </button>
        </div>
      </div>
      {rejectOpen && (
        <BottomSheet title={rejectionTitle} onDismiss={() => !signingOut && setRejectOpen(false)}>
          <p>{rejectionMessage}</p>
          <div className="legal-gate-confirm-actions">
            <button type="button" className="secondary" onClick={() => setRejectOpen(false)} disabled={signingOut}>
              Cancel
            </button>
            <button type="button" className="danger" onClick={() => void signOut()} disabled={signingOut}>
              {signingOut ? "Signing out…" : "Reject and sign out"}
            </button>
          </div>
        </BottomSheet>
      )}
    </main>
  );
}
