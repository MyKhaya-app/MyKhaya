"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import type { LegalDocument } from "@/components/legal-logic";

const KEY_PATTERN = /^[a-z][a-z0-9_-]*$/;

function fieldValue(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

export default function NewLegalDocumentPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    const key = fieldValue(data, "key").trim();
    if (!KEY_PATTERN.test(key)) {
      setError(
        "Key must start with a lowercase letter and contain only lowercase letters, numbers, - or _.",
      );
      return;
    }
    setSubmitting(true);
    try {
      const created = await platformApi.post<LegalDocument>(
        "/legal/documents",
        {
          key,
          display_name: fieldValue(data, "display_name").trim(),
          audience: data.get("audience"),
          scope: data.get("scope"),
          action_verb: data.get("action_verb"),
          acceptance_required: data.get("acceptance_required") === "on",
        },
      );
      router.push(`/legal/documents/${created.id}`);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not create this document.",
      );
      setSubmitting(false);
    }
  }

  return (
    <PlatformShell>
      <CcPage className="cc-legal-new-document">
        <CcPageHeader
          eyebrow="Legal & Compliance"
          title="New legal document"
          description="Register a new document type. No content is published until an administrator explicitly publishes a version."
        />
        <CcLegalSubnav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        <CcSection title="Document details">
          <CcCard>
            <form className="cc-legal-document-form" onSubmit={submit}>
              <label>
                Key
                <input
                  name="key"
                  type="text"
                  required
                  maxLength={50}
                  placeholder="terms, privacy, children_privacy, cookies…"
                />
                <small>A stable identifier. Cannot be changed later.</small>
              </label>
              <label>
                Display name
                <input
                  name="display_name"
                  type="text"
                  required
                  maxLength={200}
                  placeholder="Terms & Conditions"
                />
              </label>
              <label>
                Audience
                <select name="audience" defaultValue="adult">
                  <option value="adult">
                    Adult — accepted/acknowledged directly by a user
                  </option>
                  <option value="child">
                    Child — authorised by a guardian and acknowledged by the
                    child
                  </option>
                </select>
              </label>
              <label>
                Scope
                <select name="scope" defaultValue="global">
                  <option value="global">Global — applies across MyKhaya</option>
                  <option value="founding_beta">Founding Beta — applies to Beta registration and enrolment</option>
                </select>
                <small>Founding Beta documents are only required in the Beta flow.</small>
              </label>
              <label>
                Action for adult audience
                <select name="action_verb" defaultValue="accept">
                  <option value="accept">
                    Accept (contractual, e.g. Terms & Conditions)
                  </option>
                  <option value="acknowledge">
                    Acknowledge (informational, e.g. Privacy Policy)
                  </option>
                </select>
                <small>Only relevant for an adult-audience document.</small>
              </label>
              <label className="cc-legal-document-form-checkbox">
                <input
                  name="acceptance_required"
                  type="checkbox"
                  defaultChecked
                />
                Acceptance is required for this document type
              </label>
              <div className="cc-legal-document-form-actions">
                <button
                  type="submit"
                  className="cc-action cc-action-primary"
                  disabled={submitting}
                >
                  {submitting ? "Creating…" : "Create document"}
                </button>
              </div>
            </form>
          </CcCard>
        </CcSection>
      </CcPage>
    </PlatformShell>
  );
}
