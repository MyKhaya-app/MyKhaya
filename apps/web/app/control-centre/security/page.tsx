"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate, titleCase } from "@/components/platform-format";
import type { MfaPolicy } from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState, CcEmptyState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

type SecurityEvent = {
  id: string;
  created_at: string;
  event_type: string;
  severity: string;
  outcome: string;
  safe_detail: string | null;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function GlobalSecurityPage() {
  const [policy, setPolicy] = useState<MfaPolicy | null>(null);
  const [events, setEvents] = useState<SecurityEvent[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingChange, setPendingChange] = useState<boolean | null>(null);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      const [policyResult, eventsResult] = await Promise.all([
        platformApi.get<MfaPolicy>("/auth/mfa/policy"),
        platformApi.get<{ items: SecurityEvent[] }>("/security?page_size=25"),
      ]);
      setPolicy(policyResult);
      setEvents(eventsResult.items);
    } catch (cause) {
      setError(safeError(cause, "Could not load security policy."));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // PUT /auth/mfa/policy is guarded server-side with require_recent_auth()
  // (apps/api/mykhaya/routers/platform.py) — a 403 here transparently opens
  // PlatformReauthModal and retries the same submit once verified, same as
  // every other recent-auth-gated mutation in the Control Centre.
  const applyChange = useCallback(
    (reasonText: string) =>
      guarded(async () => {
        if (pendingChange === null) return;
        setSaving(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.put<MfaPolicy>("/auth/mfa/policy", {
            required: pendingChange,
            reason: reasonText,
            confirmed: true,
          });
          setPolicy(result);
          setMessage(
            result.required
              ? "MFA is now required for every platform administrator."
              : "MFA is now optional for platform administrators.",
          );
          setPendingChange(null);
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The policy could not be changed."));
        } finally {
          setSaving(false);
        }
      })(),
    [pendingChange, guarded],
  );

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const raw = data.get("reason");
    void applyChange(typeof raw === "string" ? raw : "");
  }

  const columns: CcTableColumn<SecurityEvent>[] = [
    { key: "when", header: "When", render: (row) => readableDate(row.created_at) },
    { key: "event", header: "Event", render: (row) => titleCase(row.event_type) },
    { key: "severity", header: "Severity", render: (row) => titleCase(row.severity) },
    { key: "outcome", header: "Outcome", render: (row) => titleCase(row.outcome) },
    { key: "detail", header: "Detail", render: (row) => row.safe_detail ?? "—" },
  ];

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Global platform security policy"
          title="Security"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!policy ? (
          <CcLoadingState label="Loading security policy…" />
        ) : (
          <CcCard
            title="Require MFA for platform administrators"
            description="Platform setting — changes here affect every platform administrator across the whole MyKhaya installation."
            icon={ShieldCheck}
            actions={<CcBadge tone={policy.required ? "success" : "warning"}>{policy.required ? "Required" : "Optional"}</CcBadge>}
          >
            {policy.environment_enforced ? (
              <CcNotice tone="warning">
                Managed by the deployment environment (MYKHAYA_ADMIN_MFA_REQUIRED). MFA is permanently
                required in this deployment and cannot be turned off here.
              </CcNotice>
            ) : (
              <>
                <p>
                  When enabled, every platform administrator must have at least one MFA method (a
                  passkey or an authenticator app) configured before they can use the Control Centre.
                  An administrator who signs in without one is sent through mandatory enrollment rather
                  than being locked out.
                </p>
                {pendingChange === null ? (
                  <button className={policy.required ? "secondary" : undefined} onClick={() => setPendingChange(!policy.required)}>
                    {policy.required ? "Make MFA optional" : "Require MFA for all administrators"}
                  </button>
                ) : (
                  <form onSubmit={onSubmit} className="mfa-method">
                    <CcField label="Reason for this change">
                      <input name="reason" minLength={10} maxLength={500} required autoFocus />
                    </CcField>
                    <div className="platform-modal-actions">
                      <button type="button" className="secondary" onClick={() => setPendingChange(null)} disabled={saving}>
                        Cancel
                      </button>
                      <button disabled={saving}>
                        {saving ? "Saving…" : pendingChange ? "Require MFA" : "Make MFA optional"}
                      </button>
                    </div>
                  </form>
                )}
              </>
            )}
          </CcCard>
        )}

        <CcCard title="Recent security events">
          {!events ? (
            <CcLoadingState label="Loading security events…" />
          ) : events.length === 0 ? (
            <CcEmptyState>No recent security events.</CcEmptyState>
          ) : (
            <CcTable
              columns={columns}
              rows={events}
              rowKey={(row) => row.id}
              caption="Recent security events"
            />
          )}
        </CcCard>
      </CcPage>
      {modal}
    </PlatformShell>
  );
}
