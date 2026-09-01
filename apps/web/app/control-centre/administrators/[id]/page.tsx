"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import QRCode from "qrcode";
import {
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
} from "@simplewebauthn/browser";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { PlatformReauthModal } from "@/components/platform-reauth-modal";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";
import { isSelfAdministrator } from "@/components/platform-mfa-logic";
import type {
  AdministratorSecurity,
  AdminSessionSummary,
  PlatformActor,
} from "@/components/platform-types";

type Tab = "overview" | "security" | "sessions" | "activity";
type AuditRow = {
  id: string;
  created_at: string;
  action: string;
  outcome: string;
  administrator_id: string | null;
  target_id: string | null;
  reason: string | null;
};

function useReauth() {
  const [pending, setPending] = useState<(() => void | Promise<void>) | null>(null);
  function require(action: () => void | Promise<void>) {
    return (cause: unknown) => {
      if (cause instanceof ApiError && cause.status === 403) {
        setPending(() => action);
        return;
      }
      throw cause;
    };
  }
  const modal = pending ? (
    <PlatformReauthModal
      onVerified={() => {
        const run = pending;
        setPending(null);
        void run?.();
      }}
      onCancel={() => setPending(null)}
    />
  ) : null;
  return { require, modal };
}

export default function AdministratorDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [me, setMe] = useState<PlatformActor | null>(null);
  const [security, setSecurity] = useState<AdministratorSecurity | null>(null);
  const [ownSessions, setOwnSessions] = useState<AdminSessionSummary[] | null>(null);
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const reauth = useReauth();

  const isSelf = isSelfAdministrator(me, id);

  const load = useCallback(async () => {
    setError("");
    try {
      const [actor, detail] = await Promise.all([
        platformApi.get<PlatformActor>("/auth/me"),
        platformApi.get<AdministratorSecurity>(`/administrators/${id}/security`),
      ]);
      setMe(actor);
      setSecurity(detail);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load this administrator.");
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isSelf || tab !== "sessions") return;
    platformApi
      .get<AdminSessionSummary[]>("/auth/sessions")
      .then(setOwnSessions)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Could not load sessions."));
  }, [isSelf, tab]);

  useEffect(() => {
    if (tab !== "activity") return;
    platformApi
      .get<{ items: AuditRow[] }>(
        `/audit?page_size=100&administrator_id=${encodeURIComponent(id)}`,
      )
      .then((result) => setAudit(result.items))
      .catch(() => setAudit([]));
  }, [tab, id]);

  if (error && !security) {
    return (
      <PlatformShell>
        <main className="platform-page">
          <p className="notice error" role="alert">
            {error}
          </p>
        </main>
      </PlatformShell>
    );
  }
  if (!security || !me) {
    return (
      <PlatformShell>
        <main className="platform-page">
          <p role="status">Loading administrator…</p>
        </main>
      </PlatformShell>
    );
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>{isSelf ? "Your administrator account" : "Administrator"}</p>
            <h1>{security.display_name}</h1>
          </div>
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
        <nav className="admin-detail-tabs" aria-label="Administrator sections">
          {(["overview", "security", "sessions", "activity"] as Tab[]).map((value) => (
            <button
              key={value}
              type="button"
              className={tab === value ? "active" : "tertiary"}
              onClick={() => setTab(value)}
            >
              {titleCase(value)}
            </button>
          ))}
        </nav>

        {tab === "overview" && (
          <OverviewTab
            security={security}
            isSelf={isSelf}
            reauth={reauth}
            onChanged={(msg) => {
              setMessage(msg);
              void load();
            }}
            setError={setError}
          />
        )}
        {tab === "security" && (
          <SecurityTab
            security={security}
            isSelf={isSelf}
            reauth={reauth}
            onChanged={(msg) => {
              setMessage(msg);
              setError("");
              void load();
            }}
            setError={setError}
          />
        )}
        {tab === "sessions" && (
          <SessionsTab
            isSelf={isSelf}
            security={security}
            ownSessions={ownSessions}
            reauth={reauth}
            onChanged={(msg) => {
              setMessage(msg);
              setOwnSessions(null);
              setTab("sessions");
            }}
            setError={setError}
          />
        )}
        {tab === "activity" && <ActivityTab audit={audit} />}
      </main>
      {reauth.modal}
    </PlatformShell>
  );
}

function OverviewTab({
  security,
  isSelf,
  reauth,
  onChanged,
  setError,
}: {
  security: AdministratorSecurity;
  isSelf: boolean;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function toggleActive() {
    const reason = window.prompt(
      `Reason for ${security.is_active ? "deactivating" : "reactivating"} this administrator (at least 10 characters):`,
    );
    if (!reason || reason.trim().length < 10) return;
    const run = async () => {
      setBusy(true);
      setError("");
      try {
        await platformApi.patch(`/administrators/${security.id}`, {
          is_active: !security.is_active,
          reason,
          confirmed: true,
        });
        onChanged(security.is_active ? "Administrator deactivated." : "Administrator reactivated.");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "The change could not be saved.");
      } finally {
        setBusy(false);
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  return (
    <section className="overview-panel">
      <dl>
        <div>
          <dt>Email</dt>
          <dd>{security.email}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{titleCase(security.role)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <strong className={`state-label ${security.is_active ? "state-healthy" : "state-unavailable"}`}>
              {security.is_active ? "Active" : "Deactivated"}
            </strong>
          </dd>
        </div>
        <div>
          <dt>MFA</dt>
          <dd>
            <strong className={`state-label ${security.mfa_enrolled ? "state-healthy" : "state-not-configured"}`}>
              {security.mfa_enrolled ? "Enrolled" : "Not enrolled"}
            </strong>
          </dd>
        </div>
      </dl>
      {!isSelf && (
        <button className="secondary" onClick={toggleActive} disabled={busy}>
          {security.is_active ? "Deactivate administrator" : "Reactivate administrator"}
        </button>
      )}
    </section>
  );
}

function SecurityTab({
  security,
  isSelf,
  reauth,
  onChanged,
  setError,
}: {
  security: AdministratorSecurity;
  isSelf: boolean;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  if (!isSelf) {
    return <OtherAdminSecurityTab security={security} reauth={reauth} onChanged={onChanged} setError={setError} />;
  }
  return <SelfSecurityTab security={security} reauth={reauth} onChanged={onChanged} setError={setError} />;
}

function OtherAdminSecurityTab({
  security,
  reauth,
  onChanged,
  setError,
}: {
  security: AdministratorSecurity;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function resetMfa() {
    const reason = window.prompt(
      "Reason for resetting this administrator's MFA — they will need to enrol again (at least 10 characters):",
    );
    if (!reason || reason.trim().length < 10) return;
    const run = async () => {
      setBusy(true);
      setError("");
      try {
        await platformApi.post(`/administrators/${security.id}/mfa/reset`, { reason, confirmed: true });
        onChanged("MFA was reset for this administrator. They will be asked to enrol again next sign-in.");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "MFA could not be reset.");
      } finally {
        setBusy(false);
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  // PCC-SEC-006: an Administrator/Security viewer gets the reduced summary
  // shape (counts, no raw session IPs/user-agents/session IDs) — the full
  // per-credential/per-session lists are Owner-only, see AdministratorSecurity.
  const passkeyCount = security.webauthn_credentials?.length ?? security.webauthn_credential_count ?? 0;

  return (
    <>
      <section className="overview-grid">
        <section className="overview-panel">
          <h2>Authenticator app</h2>
          <p>{security.totp_enabled ? "Configured" : "Not configured"}</p>
        </section>
        <section className="overview-panel">
          <h2>Passkeys</h2>
          <p>{passkeyCount} registered</p>
        </section>
        {security.sessions === undefined && (
          <section className="overview-panel">
            <h2>Active sessions</h2>
            <p>
              {security.active_session_count ?? 0}
              {security.last_seen_at ? ` · last active ${relativeTime(security.last_seen_at)}` : ""}
            </p>
          </section>
        )}
      </section>
      <section className="danger-zone">
        <h2>Danger zone</h2>
        <p>
          Resetting this administrator&rsquo;s MFA removes every passkey, their authenticator app,
          and their recovery codes, and signs them out everywhere. They will need to enrol a new
          method the next time they sign in.
        </p>
        <button className="danger" onClick={resetMfa} disabled={busy}>
          Reset MFA for this administrator
        </button>
      </section>
    </>
  );
}

function SelfSecurityTab({
  security,
  reauth,
  onChanged,
  setError,
}: {
  security: AdministratorSecurity;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [totpSetup, setTotpSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [recoveryStatus, setRecoveryStatus] = useState<number | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  useEffect(() => {
    platformApi
      .get<{ remaining: number }>("/auth/mfa/recovery-codes/status")
      .then((result) => setRecoveryStatus(result.remaining))
      .catch(() => {});
  }, [security]);

  async function setUpPasskey() {
    setBusy(true);
    setError("");
    try {
      const options = await platformApi.post<{ options_json: string }>(
        "/auth/mfa/webauthn/register/options",
        {},
      );
      const credential = await startRegistration({
        optionsJSON: JSON.parse(options.options_json) as PublicKeyCredentialCreationOptionsJSON,
      });
      const label = window.prompt("Name this passkey (e.g. \"Work laptop\"):", "My passkey") || "My passkey";
      await platformApi.post("/auth/mfa/webauthn/register/verify", {
        label,
        credential_json: JSON.stringify(credential),
      });
      onChanged("Passkey added.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Setting up the passkey did not complete.");
    } finally {
      setBusy(false);
    }
  }

  async function renamePasskey(credentialId: string, currentLabel: string) {
    const label = window.prompt("Rename this passkey:", currentLabel);
    if (!label) return;
    setRenaming(credentialId);
    try {
      await platformApi.patch(`/auth/mfa/webauthn/credentials/${credentialId}`, { label });
      onChanged("Passkey renamed.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The passkey could not be renamed.");
    } finally {
      setRenaming(null);
    }
  }

  async function removePasskey(credentialId: string) {
    if (!window.confirm("Remove this passkey? You will no longer be able to sign in with it.")) return;
    const run = async () => {
      setError("");
      try {
        await platformApi.delete(`/auth/mfa/webauthn/credentials/${credentialId}`);
        onChanged("Passkey removed.");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "The passkey could not be removed.");
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  async function startTotp() {
    setError("");
    try {
      const result = await platformApi.post<{ secret: string; provisioning_uri: string }>(
        "/auth/mfa/totp/setup",
        {},
      );
      const qr = await QRCode.toDataURL(result.provisioning_uri, { margin: 1, width: 200 });
      setTotpSetup({ secret: result.secret, qr });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start authenticator setup.");
    }
  }

  async function verifyTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await platformApi.post("/auth/mfa/totp/verify", { code: data.get("code") });
      setTotpSetup(null);
      onChanged("Authenticator app enabled.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That code is not correct.");
    } finally {
      setBusy(false);
    }
  }

  async function disableTotp() {
    const reason = window.prompt("Reason for disabling your authenticator app (at least 10 characters):");
    if (!reason || reason.trim().length < 10) return;
    const run = async () => {
      setError("");
      try {
        await platformApi.post("/auth/mfa/totp/disable", { reason, confirmed: true });
        onChanged("Authenticator app disabled.");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "TOTP could not be disabled.");
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  async function generateRecoveryCodes() {
    const verb = (recoveryStatus ?? 0) > 0 ? "regenerate" : "generate";
    if (
      verb === "regenerate" &&
      !window.confirm("Regenerating recovery codes invalidates every previous code. Continue?")
    )
      return;
    const reason = window.prompt(
      `Reason to ${verb} recovery codes (at least 10 characters):`,
      "Refreshing recovery codes",
    );
    if (!reason || reason.trim().length < 10) return;
    const run = async () => {
      setError("");
      try {
        const result = await platformApi.post<{ codes: string[] }>("/auth/mfa/recovery-codes", {
          reason,
          confirmed: true,
        });
        setRecoveryCodes(result.codes);
        setRecoveryStatus(result.codes.length);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "Recovery codes could not be generated.");
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  // Self-view always gets the full-detail shape from the backend (see
  // PCC-SEC-006), so this is never actually undefined here — the fallback is
  // only to satisfy the shared (partly-optional) AdministratorSecurity type.
  const ownCredentials = security.webauthn_credentials ?? [];

  return (
    <>
      <section className="action-panel">
        <h2>Passkeys</h2>
        {ownCredentials.length === 0 ? (
          <p className="quiet-state">No passkeys registered yet.</p>
        ) : (
          <ul className="credential-list">
            {ownCredentials.map((credential) => (
              <li key={credential.id}>
                <div>
                  <strong>{credential.label}</strong>
                  <small>
                    Added {readableDate(credential.created_at)} · Last used{" "}
                    {credential.last_used_at ? relativeTime(credential.last_used_at) : "never"}
                  </small>
                </div>
                <div className="platform-modal-actions">
                  <button
                    type="button"
                    className="tertiary"
                    disabled={renaming === credential.id}
                    onClick={() => renamePasskey(credential.id, credential.label)}
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    className="tertiary"
                    onClick={() => removePasskey(credential.id)}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <button className="secondary" onClick={setUpPasskey} disabled={busy}>
          Add a passkey
        </button>
      </section>

      <section className="action-panel">
        <h2>Authenticator app</h2>
        {security.totp_enabled ? (
          <>
            <p>Configured{security.totp_verified_at && ` · verified ${readableDate(security.totp_verified_at)}`}.</p>
            <button className="secondary" onClick={disableTotp}>
              Disable authenticator app
            </button>
          </>
        ) : totpSetup ? (
          <form onSubmit={verifyTotp} className="mfa-method">
            <img src={totpSetup.qr} alt="Scan with your authenticator app" width={200} height={200} />
            <p>
              Manual key: <code>{totpSetup.secret}</code>
            </p>
            <label>
              6-digit code
              <input
                name="code"
                inputMode="numeric"
                pattern="[0-9]*"
                minLength={6}
                maxLength={6}
                required
              />
            </label>
            <button disabled={busy}>{busy ? "Verifying…" : "Verify and enable"}</button>
          </form>
        ) : (
          <button className="secondary" onClick={startTotp}>
            Set up an authenticator app
          </button>
        )}
      </section>

      <section className="action-panel">
        <h2>Recovery codes</h2>
        <p>
          {recoveryStatus === null
            ? "Loading…"
            : `${recoveryStatus} unused recovery code${recoveryStatus === 1 ? "" : "s"} remaining.`}
        </p>
        {recoveryCodes ? (
          <>
            <p className="notice">
              Save these now — they will not be shown again. Generating new codes invalidates
              these.
            </p>
            <ul className="recovery-code-list">
              {recoveryCodes.map((code) => (
                <li key={code}>{code}</li>
              ))}
            </ul>
            <button className="secondary" onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n"))}>
              Copy codes
            </button>
          </>
        ) : (
          <button className="secondary" onClick={generateRecoveryCodes} disabled={!security.mfa_enrolled}>
            {(recoveryStatus ?? 0) > 0 ? "Regenerate recovery codes" : "Generate recovery codes"}
          </button>
        )}
        {!security.mfa_enrolled && (
          <small>Set up a passkey or authenticator app first — recovery codes back up an existing method.</small>
        )}
      </section>
    </>
  );
}

function SessionsTab({
  isSelf,
  security,
  ownSessions,
  reauth,
  onChanged,
  setError,
}: {
  isSelf: boolean;
  security: AdministratorSecurity;
  ownSessions: AdminSessionSummary[] | null;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  const router = useRouter();
  async function revokeOne(sessionId: string) {
    const run = async () => {
      setError("");
      try {
        await platformApi.delete(`/auth/sessions/${sessionId}`);
        onChanged("Session revoked.");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "The session could not be revoked.");
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  async function revokeAllOthers() {
    const reason = window.prompt("Reason for signing out every other device (at least 10 characters):");
    if (!reason || reason.trim().length < 10) return;
    const run = async () => {
      setError("");
      try {
        await platformApi.post("/auth/revoke-all", { reason, confirmed: true });
        router.push("/login");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "Sessions could not be revoked.");
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  }

  const rows = isSelf ? ownSessions : security.sessions;
  // PCC-SEC-006: an Administrator/Security viewer only gets a session count
  // (security.sessions is absent for that summary shape), not the raw
  // IP/user-agent list an Owner sees — show that instead of a stuck spinner.
  if (!isSelf && security.sessions === undefined) {
    return (
      <section className="action-panel">
        <h2>Active sessions</h2>
        <p>
          {security.active_session_count ?? 0} active session
          {security.active_session_count === 1 ? "" : "s"}
          {security.last_seen_at ? ` · last active ${relativeTime(security.last_seen_at)}` : ""}
        </p>
        <small>Session IP/device detail is visible to Platform Owners only.</small>
      </section>
    );
  }

  return (
    <section className="action-panel">
      <h2>Active sessions</h2>
      {!rows ? (
        <p role="status">Loading sessions…</p>
      ) : rows.length === 0 ? (
        <p className="quiet-state">No active sessions.</p>
      ) : (
        <ul className="credential-list">
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <strong>
                  {row.user_agent}
                  {"current" in row && row.current ? " · This device" : ""}
                </strong>
                <small>
                  Signed in {readableDate(row.created_at)} · Last active {relativeTime(row.last_seen_at)} ·{" "}
                  {row.source_ip}
                </small>
              </div>
              {isSelf && !("current" in row && row.current) && (
                <button type="button" className="tertiary" onClick={() => revokeOne(row.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {isSelf && (
        <button className="secondary" onClick={revokeAllOthers}>
          Sign out every other device
        </button>
      )}
    </section>
  );
}

function ActivityTab({ audit }: { audit: AuditRow[] | null }) {
  if (!audit) return <p role="status">Loading activity…</p>;
  if (audit.length === 0) return <p className="quiet-state">No recorded activity for this administrator yet.</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Action</th>
            <th>Outcome</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {audit.map((row) => (
            <tr key={row.id}>
              <td>{readableDate(row.created_at)}</td>
              <td>{titleCase(row.action)}</td>
              <td>{titleCase(row.outcome)}</td>
              <td>{row.reason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
