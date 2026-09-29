"use client";

import { useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge } from "@/components/control-centre/badge";

type Document = { key: string; display_name: string; archived_at: string | null; published_version: { version: string } | null; draft_version: { version: string } | null };
type Provider = { provider: string; state: string; dpa_status: string | null; transfer_mechanism: string | null };
type TestMode = { enabled: boolean; test_user_ids: string[] };

const manualChecks = [
  "External legal/privacy review completed",
  "Lawful-basis, children’s-data and DPIA review completed",
  "Subscription, marketing and DVLA terms reviewed",
  "Privacy and support contacts are monitored",
];

export default function LaunchReadinessPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [testMode, setTestMode] = useState<TestMode>({ enabled: false, test_user_ids: [] });
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      platformApi.get<Document[]>("/legal/documents"),
      platformApi.get<Provider[]>("/compliance/subprocessors"),
      platformApi.get<TestMode>("/compliance/legal-test-mode"),
    ]).then(([loadedDocuments, loadedProviders, loadedTestMode]) => {
      setDocuments(loadedDocuments);
      setProviders(loadedProviders);
      setTestMode(loadedTestMode);
    }).catch((cause: unknown) => setError(cause instanceof ApiError ? cause.message : "Unable to load launch-readiness checks."));
  }, []);
  const requiredKeys = ["terms", "privacy", "children_privacy", "cookies"];
  const documentChecks = requiredKeys.map((key) => {
    const document = documents.find((item) => item.key === key);
    return { key, label: document?.display_name ?? key, ready: Boolean(document?.published_version) };
  });
  async function toggleTestMode() {
    const designated = window.prompt("Comma-separated user IDs to designate for Legal Test Mode:", testMode.test_user_ids.join(","));
    if (designated === null) return;
    const test_user_ids = designated.split(",").map((value) => value.trim()).filter(Boolean);
    const reason = window.prompt("Reason for changing Legal Test Mode (at least 10 characters):", "Controlled legal flow testing");
    if (!reason) return;
    try {
      const result = await platformApi.put<TestMode>("/compliance/legal-test-mode", { enabled: !testMode.enabled, test_user_ids, reason, confirmed: true });
      setTestMode(result);
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : "Unable to change Legal Test Mode."); }
  }
  return <PlatformShell><CcPage wide className="cc-launch-readiness"><CcPageHeader eyebrow="Legal & Compliance" title="Launch Readiness" description="Operational checks to support review. Green checks do not certify legal compliance or replace human approval." /><CcLegalSubnav />{error && <CcNotice tone="error">{error}</CcNotice>}{testMode.enabled && <CcNotice tone="warning">LEGAL TEST MODE — acceptance activity is test evidence, not production legal acceptance.</CcNotice>}<section className="cc-user-profile-card"><h2>Automated checks</h2>{documentChecks.map((check) => <p key={check.key}><CcBadge tone={check.ready ? "success" : "warning"}>{check.ready ? "Ready" : "Review"}</CcBadge> {check.label} published</p>)}<p><CcBadge tone={providers.length ? "info" : "warning"}>{providers.length ? `${providers.length} recorded` : "Review"}</CcBadge> Subprocessor register metadata</p><p><CcBadge tone="warning">Manual review</CcBadge> Retention, transfer and deployment configuration findings</p></section><section className="cc-user-profile-card"><h2>Legal Test Mode</h2><p className="muted">Restricted to designated users and explicitly test-marked immutable records. Production public legal pages are not affected. Test records remain immutable; repeat testing uses a new test version or designated account.</p><p><CcBadge tone={testMode.enabled ? "warning" : "neutral"}>{testMode.enabled ? "Enabled" : "Off"}</CcBadge> {testMode.test_user_ids.length} designated test user(s)</p><button className="cc-action" onClick={() => void toggleTestMode()}>{testMode.enabled ? "Disable Legal Test Mode" : "Enable Legal Test Mode"}</button></section><section className="cc-user-profile-card"><h2>Manual/legal review</h2>{manualChecks.map((check) => <p key={check}><CcBadge tone="warning">Not recorded</CcBadge> {check}</p>)}<p className="muted">Record evidence through the approved operational process. This page intentionally does not infer legal approval from technical checks.</p></section></CcPage></PlatformShell>;
}
