"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate, titleCase } from "@/components/platform-format";
import type { ConsumerMfaPolicy, MfaPolicy } from "@/components/platform-types";
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

type ProviderStatus = {
  provider: "apple" | "google";
  state: "enabled" | "disabled" | "not_configured" | "framework_available";
  configured: boolean;
  framework_available: boolean;
  client_identifier: string | null;
  redirect_uri: string | null;
  credential_configured: boolean;
  enabled: boolean;
  last_configuration_test: string | null;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function GlobalSecurityPage() {
  const [policy, setPolicy] = useState<MfaPolicy | null>(null);
  const [browserPolicy, setBrowserPolicy] = useState<ConsumerMfaPolicy | null>(null);
  const [events, setEvents] = useState<SecurityEvent[] | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingChange, setPendingChange] = useState<boolean | null>(null);
  const [pendingBrowserChange, setPendingBrowserChange] = useState<"optional" | "required" | null>(null);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      const [policyResult, browserPolicyResult, eventsResult, providersResult] = await Promise.all([
        platformApi.get<MfaPolicy>("/auth/mfa/policy"),
        platformApi.get<ConsumerMfaPolicy>("/auth/mfa/browser-policy"),
        platformApi.get<{ items: SecurityEvent[] }>("/security?page_size=25"),
        platformApi.get<{ providers: ProviderStatus[] }>("/auth/providers"),
      ]);
      setPolicy(policyResult);
      setBrowserPolicy(browserPolicyResult);
      setEvents(eventsResult.items);
      setProviders(providersResult.providers);
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

  const applyBrowserChange = useCallback(
    (reasonText: string) =>
      guarded(async () => {
        if (pendingBrowserChange === null) return;
        setSaving(true);
        setError("");
        try {
          const result = await platformApi.put<ConsumerMfaPolicy>("/auth/mfa/browser-policy", {
            policy: pendingBrowserChange,
            allowed_methods: browserPolicy?.allowed_methods ?? ["totp", "email"],
            reason: reasonText,
            confirmed: true,
          });
          setBrowserPolicy(result);
          setPendingBrowserChange(null);
          setMessage("Browser MFA policy updated.");
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The browser MFA policy could not be changed."));
        } finally {
          setSaving(false);
        }
      })(),
    [browserPolicy?.allowed_methods, guarded, pendingBrowserChange],
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

        {!browserPolicy ? (
          <CcLoadingState label="Loading browser MFA policy…" />
        ) : (
          <CcCard
            title="Browser MFA"
            description="Consumer browser MFA is separate from PCC administrator MFA. Native application authentication is unaffected."
            icon={ShieldCheck}
            actions={<CcBadge tone={browserPolicy.effective === "required" ? "success" : "warning"}>{titleCase(browserPolicy.effective)}</CcBadge>}
          >
            <p>
              Effective policy: <strong>{titleCase(browserPolicy.effective)}</strong> · Source: <strong>{titleCase(browserPolicy.source)}</strong> · Allowed methods: {browserPolicy.allowed_methods.map(titleCase).join(", ")}. Email codes expire after {browserPolicy.email_code_lifetime_minutes} minutes.
            </p>
            <p>Rollout gate: {browserPolicy.enforcement_enabled ? "enabled" : "disabled"}. The deployment flag remains the final enforcement gate.</p>
            {pendingBrowserChange === null ? (
              <button className={browserPolicy.configured === "required" ? "secondary" : undefined} onClick={() => setPendingBrowserChange(browserPolicy.configured === "required" ? "optional" : "required")}>
                {browserPolicy.configured === "required" ? "Make browser MFA optional" : "Require browser MFA"}
              </button>
            ) : (
              <form onSubmit={(event) => { event.preventDefault(); const value = new FormData(event.currentTarget).get("reason"); void applyBrowserChange(typeof value === "string" ? value : ""); }} className="mfa-method">
                <CcField label="Reason for this change">
                  <input name="browser-reason" minLength={10} maxLength={500} required autoFocus />
                </CcField>
                <div className="platform-modal-actions">
                  <button type="button" className="secondary" onClick={() => setPendingBrowserChange(null)} disabled={saving}>Cancel</button>
                  <button disabled={saving}>{saving ? "Saving…" : "Confirm browser MFA policy"}</button>
                </div>
              </form>
            )}
          </CcCard>
        )}

        <CcCard
          title="Sign-in providers"
          description="Provider state is deployment-managed. Secrets and provider tokens are never shown here."
        >
          {!providers ? (
            <CcLoadingState label="Loading provider configuration…" />
          ) : (
            <div className="summary-groups">
              {providers.map((provider) => (
                <div key={provider.provider}>
                  <h3>{provider.provider === "apple" ? "Apple" : "Google"}</h3>
                  <dl>
                    <div>
                      <dt>Status</dt>
                      <dd>{titleCase(provider.state.replaceAll("_", " "))}</dd>
                    </div>
                    <div>
                      <dt>Client / service identifier</dt>
                      <dd>{provider.client_identifier ?? "Not configured"}</dd>
                    </div>
                    <div>
                      <dt>Signing credential</dt>
                      <dd>{provider.credential_configured ? "Configured" : "Not configured"}</dd>
                    </div>
                    {provider.redirect_uri && (
                      <div>
                        <dt>Callback URI</dt>
                        <dd>{provider.redirect_uri}</dd>
                      </div>
                    )}
                  </dl>
                  <small>
                    Configure through the deployment secret environment. Provider sign-in is not
                    enabled by configuration alone.
                  </small>
                </div>
              ))}
            </div>
          )}
        </CcCard>

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
