"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { PlatformReauthModal } from "@/components/platform-reauth-modal";
import { readableDate, titleCase } from "@/components/platform-format";
import type { MfaPolicy } from "@/components/platform-types";

type SecurityEvent = {
  id: string;
  created_at: string;
  event_type: string;
  severity: string;
  outcome: string;
  safe_detail: string | null;
};

export default function GlobalSecurityPage() {
  const [policy, setPolicy] = useState<MfaPolicy | null>(null);
  const [events, setEvents] = useState<SecurityEvent[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingChange, setPendingChange] = useState<boolean | null>(null);
  const [showReauth, setShowReauth] = useState(false);

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
      setError(cause instanceof ApiError ? cause.message : "Could not load security policy.");
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  function requestToggle(nextRequired: boolean) {
    setPendingChange(nextRequired);
    setShowReauth(true);
  }

  async function applyChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingChange === null) return;
    setSaving(true);
    setError("");
    setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await platformApi.put<MfaPolicy>("/auth/mfa/policy", {
        required: pendingChange,
        reason: data.get("reason"),
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
      setError(cause instanceof ApiError ? cause.message : "The policy could not be changed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Global platform security policy</p>
            <h1>Security</h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}
        {!policy ? (
          <p role="status">Loading security policy…</p>
        ) : (
          <section className="action-panel">
            <div className="diagnostic-heading">
              <h2>Require MFA for platform administrators</h2>
              <strong className={`state-label ${policy.required ? "state-healthy" : "state-not-configured"}`}>
                {policy.required ? "Required" : "Optional"}
              </strong>
            </div>
            <p>
              <span className="scope-note">Platform setting — changes here affect every platform
              administrator across the whole MyKhaya installation.</span>
            </p>
            {policy.environment_enforced ? (
              <p className="notice">
                Managed by the deployment environment (MYKHAYA_ADMIN_MFA_REQUIRED). MFA is
                permanently required in this deployment and cannot be turned off here.
              </p>
            ) : (
              <>
                <p>
                  When enabled, every platform administrator must have at least one MFA method
                  (a passkey or an authenticator app) configured before they can use the Control
                  Centre. An administrator who signs in without one is sent through mandatory
                  enrollment rather than being locked out.
                </p>
                {pendingChange === null ? (
                  <button
                    className={policy.required ? "secondary" : undefined}
                    onClick={() => requestToggle(!policy.required)}
                  >
                    {policy.required ? "Make MFA optional" : "Require MFA for all administrators"}
                  </button>
                ) : (
                  <form onSubmit={applyChange} className="mfa-method">
                    <label>
                      Reason for this change
                      <input name="reason" minLength={10} maxLength={500} required autoFocus />
                    </label>
                    <div className="platform-modal-actions">
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setPendingChange(null)}
                        disabled={saving}
                      >
                        Cancel
                      </button>
                      <button disabled={saving}>
                        {saving
                          ? "Saving…"
                          : pendingChange
                            ? "Require MFA"
                            : "Make MFA optional"}
                      </button>
                    </div>
                  </form>
                )}
              </>
            )}
          </section>
        )}
        <section>
          <h2>Recent security events</h2>
          {!events ? (
            <p role="status">Loading security events…</p>
          ) : events.length === 0 ? (
            <p className="quiet-state">No recent security events.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Event</th>
                    <th>Severity</th>
                    <th>Outcome</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id}>
                      <td>{readableDate(event.created_at)}</td>
                      <td>{titleCase(event.event_type)}</td>
                      <td>{titleCase(event.severity)}</td>
                      <td>{titleCase(event.outcome)}</td>
                      <td>{event.safe_detail ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
      {showReauth && (
        <PlatformReauthModal
          onVerified={() => setShowReauth(false)}
          onCancel={() => {
            setShowReauth(false);
            setPendingChange(null);
          }}
        />
      )}
    </PlatformShell>
  );
}
