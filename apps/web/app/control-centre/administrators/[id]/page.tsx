"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import QRCode from "qrcode";
import {
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
} from "@simplewebauthn/browser";
import {
  Fingerprint,
  KeyRound,
  LogOut,
  Pencil,
  Plus,
  Power,
  PowerOff,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UserCog,
} from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { PlatformReauthModal } from "@/components/platform-reauth-modal";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";
import { isSelfAdministrator } from "@/components/platform-mfa-logic";
import { PLATFORM_ROLES } from "@/components/platform-types";
import type {
  AdministratorSecurity,
  AdminSessionSummary,
  PlatformActor,
} from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard, CcColumns } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcActionBar, type CcAction } from "@/components/control-centre/action-bar";
import { CcDangerZone } from "@/components/control-centre/danger-zone";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState, CcErrorState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcDialog, CcDialogActions, CcConfirmDialog } from "@/components/control-centre/dialog";
import { CcRecordList, CcRecordCard } from "@/components/control-centre/record-list";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

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

function auditReason(formData: FormData): string {
  const value = formData.get("audit_reason");
  return typeof value === "string" ? value : "";
}

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
  const isOwner = me?.role === "platform_owner";

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
        <CcPage>
          <CcErrorState>{error}</CcErrorState>
        </CcPage>
      </PlatformShell>
    );
  }
  if (!security || !me) {
    return (
      <PlatformShell>
        <CcPage>
          <CcLoadingState label="Loading administrator…" />
        </CcPage>
      </PlatformShell>
    );
  }

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow={isSelf ? "Your administrator account" : "Administrator"}
          title={
            <>
              {security.display_name}{" "}
              <CcBadge tone={security.is_active ? "success" : "danger"}>
                {security.is_active ? "Active" : "Deactivated"}
              </CcBadge>{" "}
              <CcBadge tone={security.mfa_enrolled ? "success" : "warning"}>
                {security.mfa_enrolled ? "MFA enrolled" : "MFA not enrolled"}
              </CcBadge>
            </>
          }
          description={`${security.email} · ${titleCase(security.role)}`}
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

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
            isOwner={isOwner}
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
      </CcPage>
      {reauth.modal}
    </PlatformShell>
  );
}

function OverviewTab({
  security,
  isSelf,
  isOwner,
  reauth,
  onChanged,
  setError,
}: {
  security: AdministratorSecurity;
  isSelf: boolean;
  isOwner: boolean;
  reauth: ReturnType<typeof useReauth>;
  onChanged: (message: string) => void;
  setError: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [activeConfirmOpen, setActiveConfirmOpen] = useState(false);
  const [roleOpen, setRoleOpen] = useState(false);
  const [proposedRole, setProposedRole] = useState(security.role);

  const runToggleActive = async (reason: string) => {
    setActiveConfirmOpen(false);
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
  };

  const runRoleChange = async (reason: string) => {
    setRoleOpen(false);
    const run = async () => {
      setBusy(true);
      setError("");
      try {
        await platformApi.patch(`/administrators/${security.id}`, {
          role: proposedRole,
          reason,
          confirmed: true,
        });
        onChanged(`Role changed to ${titleCase(proposedRole)}.`);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(cause instanceof ApiError ? cause.message : "The role could not be changed.");
      } finally {
        setBusy(false);
      }
    };
    try {
      await run();
    } catch (cause) {
      reauth.require(run)(cause);
    }
  };

  const actions: CcAction[] = [];
  if (!isSelf) {
    actions.push({
      key: "toggle-active",
      label: security.is_active ? "Deactivate administrator" : "Reactivate administrator",
      icon: security.is_active ? PowerOff : Power,
      variant: security.is_active ? "caution" : "primary",
      disabled: busy,
      onClick: () => setActiveConfirmOpen(true),
    });
  }
  if (isOwner && !isSelf) {
    actions.push({
      key: "change-role",
      label: "Change role",
      icon: UserCog,
      variant: "secondary",
      disabled: busy,
      onClick: () => {
        setProposedRole(security.role);
        setRoleOpen(true);
      },
    });
  }

  return (
    <>
      <CcColumns ratio="1-1">
        <CcCard title="Account details">
          <CcMetadataGrid>
            <CcMetadataItem label="Email">{security.email}</CcMetadataItem>
            <CcMetadataItem label="Role">{titleCase(security.role)}</CcMetadataItem>
          </CcMetadataGrid>
        </CcCard>
        <CcCard title="Status" icon={ShieldCheck}>
          <CcStatusCard
            tone={security.is_active ? "success" : "danger"}
            status={security.is_active ? "Active" : "Deactivated"}
            description={
              security.is_active
                ? "This administrator can sign in to the Control Centre."
                : "This administrator cannot currently sign in."
            }
            items={[
              { label: "MFA", value: security.mfa_enrolled ? "Enrolled" : "Not enrolled" },
            ]}
          />
        </CcCard>
      </CcColumns>

      {actions.length > 0 && (
        <CcCard title="Actions" description="Manage this administrator's access and role." icon={UserCog}>
          <CcActionBar actions={actions} />
        </CcCard>
      )}

      <CcConfirmDialog
        open={activeConfirmOpen}
        onClose={() => setActiveConfirmOpen(false)}
        title={security.is_active ? "Deactivate administrator" : "Reactivate administrator"}
        description={
          security.is_active
            ? `Deactivate ${security.display_name}? They will no longer be able to sign in.`
            : `Reactivate ${security.display_name}? They will be able to sign in again.`
        }
        confirmLabel={security.is_active ? "Deactivate" : "Reactivate"}
        variant={security.is_active ? "destructive" : "default"}
        onConfirm={(formData) => runToggleActive(auditReason(formData))}
      />

      <CcConfirmDialog
        open={roleOpen}
        onClose={() => setRoleOpen(false)}
        title="Change role"
        description={
          <>
            Change {security.display_name}&rsquo;s role from <strong>{titleCase(security.role)}</strong> to{" "}
            <strong>{titleCase(proposedRole)}</strong>?
          </>
        }
        extraFields={
          <CcField label="New role">
            <select value={proposedRole} onChange={(event) => setProposedRole(event.target.value)}>
              {PLATFORM_ROLES.map((role) => (
                <option key={role.value} value={role.value}>
                  {role.label}
                </option>
              ))}
            </select>
          </CcField>
        }
        confirmLabel="Change role"
        onConfirm={(formData) => runRoleChange(auditReason(formData))}
      />
    </>
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
  const [resetOpen, setResetOpen] = useState(false);

  const runResetMfa = async (reason: string) => {
    setResetOpen(false);
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
  };

  // PCC-SEC-006: an Administrator/Security viewer gets the reduced summary
  // shape (counts, no raw session IPs/user-agents/session IDs) — the full
  // per-credential/per-session lists are Owner-only, see AdministratorSecurity.
  const passkeyCount = security.webauthn_credentials?.length ?? security.webauthn_credential_count ?? 0;

  return (
    <>
      <CcColumns ratio="1-1">
        <CcCard title="Authenticator app" icon={KeyRound}>
          <p>{security.totp_enabled ? "Configured" : "Not configured"}</p>
        </CcCard>
        <CcCard title="Passkeys" icon={Fingerprint}>
          <p>{passkeyCount} registered</p>
        </CcCard>
      </CcColumns>
      {security.sessions === undefined && (
        <CcCard title="Active sessions">
          <p>
            {security.active_session_count ?? 0}
            {security.last_seen_at ? ` · last active ${relativeTime(security.last_seen_at)}` : ""}
          </p>
        </CcCard>
      )}

      <CcDangerZone
        title="Danger zone"
        description="Resetting this administrator's MFA removes every passkey, their authenticator app, and their recovery codes, and signs them out everywhere. They will need to enrol a new method the next time they sign in."
      >
        <CcActionBar
          actions={[
            {
              key: "reset-mfa",
              label: "Reset MFA for this administrator",
              icon: ShieldAlert,
              variant: "destructive",
              disabled: busy,
              onClick: () => setResetOpen(true),
            },
          ]}
        />
      </CcDangerZone>

      <CcConfirmDialog
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset MFA"
        description="This removes every passkey, their authenticator app and their recovery codes, and signs them out everywhere."
        confirmLabel="Reset MFA"
        variant="destructive"
        onConfirm={(formData) => runResetMfa(auditReason(formData))}
      />
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
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);
  const [disableTotpOpen, setDisableTotpOpen] = useState(false);
  const [recoveryConfirmOpen, setRecoveryConfirmOpen] = useState(false);

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

  const runRemovePasskey = async (credentialId: string) => {
    setRemoveTarget(null);
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
  };

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

  const runDisableTotp = async (reason: string) => {
    setDisableTotpOpen(false);
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
  };

  const runGenerateRecoveryCodes = async (reason: string) => {
    setRecoveryConfirmOpen(false);
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
  };

  const recoveryVerb = (recoveryStatus ?? 0) > 0 ? "Regenerate" : "Generate";

  // Self-view always gets the full-detail shape from the backend (see
  // PCC-SEC-006), so this is never actually undefined here — the fallback is
  // only to satisfy the shared (partly-optional) AdministratorSecurity type.
  const ownCredentials = security.webauthn_credentials ?? [];

  return (
    <>
      <CcCard
        title="Passkeys"
        icon={Fingerprint}
        actions={
          <button className="secondary" onClick={setUpPasskey} disabled={busy}>
            <Plus aria-hidden size={16} strokeWidth={2} /> Add a passkey
          </button>
        }
      >
        <CcRecordList emptyMessage="No passkeys registered yet.">
          {ownCredentials.map((credential) => (
            <CcRecordCard
              key={credential.id}
              title={credential.label}
              meta={[
                `Added ${readableDate(credential.created_at)} · Last used ${
                  credential.last_used_at ? relativeTime(credential.last_used_at) : "never"
                }`,
              ]}
              actions={
                <>
                  <button
                    type="button"
                    className="tertiary"
                    disabled={renaming === credential.id}
                    onClick={() => renamePasskey(credential.id, credential.label)}
                  >
                    <Pencil aria-hidden size={14} strokeWidth={2} /> Rename
                  </button>
                  <button type="button" className="tertiary" onClick={() => setRemoveTarget(credential.id)}>
                    <Trash2 aria-hidden size={14} strokeWidth={2} /> Remove
                  </button>
                </>
              }
            />
          ))}
        </CcRecordList>
      </CcCard>

      <CcCard title="Authenticator app" icon={KeyRound}>
        {security.totp_enabled ? (
          <>
            <p>{`Configured${security.totp_verified_at ? ` · verified ${readableDate(security.totp_verified_at)}` : ""}.`}</p>
            <CcActionBar
              actions={[
                {
                  key: "disable-totp",
                  label: "Disable authenticator app",
                  variant: "caution",
                  onClick: () => setDisableTotpOpen(true),
                },
              ]}
            />
          </>
        ) : totpSetup ? (
          <form onSubmit={verifyTotp} className="mfa-method">
            <img src={totpSetup.qr} alt="Scan with your authenticator app" width={200} height={200} />
            <p>
              Manual key: <code>{totpSetup.secret}</code>
            </p>
            <CcField label="6-digit code">
              <input name="code" inputMode="numeric" pattern="[0-9]*" minLength={6} maxLength={6} required />
            </CcField>
            <button disabled={busy}>{busy ? "Verifying…" : "Verify and enable"}</button>
          </form>
        ) : (
          <button className="secondary" onClick={startTotp}>
            Set up an authenticator app
          </button>
        )}
      </CcCard>

      <CcCard title="Recovery codes" icon={ShieldCheck}>
        <p>
          {recoveryStatus === null
            ? "Loading…"
            : `${recoveryStatus} unused recovery code${recoveryStatus === 1 ? "" : "s"} remaining.`}
        </p>
        {recoveryCodes ? (
          <>
            <CcNotice tone="warning">
              Save these now — they will not be shown again. Generating new codes invalidates these.
            </CcNotice>
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
          <button className="secondary" onClick={() => setRecoveryConfirmOpen(true)} disabled={!security.mfa_enrolled}>
            {(recoveryStatus ?? 0) > 0 ? "Regenerate recovery codes" : "Generate recovery codes"}
          </button>
        )}
        {!security.mfa_enrolled && (
          <small>Set up a passkey or authenticator app first — recovery codes back up an existing method.</small>
        )}
      </CcCard>

      {/* Plain confirm (no reason) — this mirrors the pre-migration
          window.confirm behaviour exactly; removing a passkey never
          required a reason, so CcConfirmDialog's mandatory reason field
          would add a requirement that didn't exist before. */}
      <CcDialog open={Boolean(removeTarget)} onClose={() => setRemoveTarget(null)} title="Remove passkey">
        <div className="cc-dialog-scroll">
          <p>Remove this passkey? You will no longer be able to sign in with it.</p>
        </div>
        <CcDialogActions>
          <button type="button" className="secondary" onClick={() => setRemoveTarget(null)}>
            Cancel
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => removeTarget && void runRemovePasskey(removeTarget)}
          >
            Remove
          </button>
        </CcDialogActions>
      </CcDialog>

      <CcConfirmDialog
        open={disableTotpOpen}
        onClose={() => setDisableTotpOpen(false)}
        title="Disable authenticator app"
        description="Disable your authenticator app? You can set it up again later."
        confirmLabel="Disable"
        variant="destructive"
        onConfirm={(formData) => runDisableTotp(auditReason(formData))}
      />

      <CcConfirmDialog
        open={recoveryConfirmOpen}
        onClose={() => setRecoveryConfirmOpen(false)}
        title={`${recoveryVerb} recovery codes`}
        description={
          recoveryVerb === "Regenerate"
            ? "Regenerating recovery codes invalidates every previous code."
            : "Generate a fresh set of recovery codes for this account."
        }
        confirmLabel={recoveryVerb}
        variant={recoveryVerb === "Regenerate" ? "destructive" : "default"}
        onConfirm={(formData) => runGenerateRecoveryCodes(auditReason(formData))}
      />
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
  const [revokeAllOpen, setRevokeAllOpen] = useState(false);

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

  const runRevokeAllOthers = async (reason: string) => {
    setRevokeAllOpen(false);
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
  };

  const rows = isSelf ? ownSessions : security.sessions;
  // PCC-SEC-006: an Administrator/Security viewer only gets a session count
  // (security.sessions is absent for that summary shape), not the raw
  // IP/user-agent list an Owner sees — show that instead of a stuck spinner.
  if (!isSelf && security.sessions === undefined) {
    return (
      <CcCard title="Active sessions">
        <p>
          {security.active_session_count ?? 0} active session
          {security.active_session_count === 1 ? "" : "s"}
          {security.last_seen_at ? ` · last active ${relativeTime(security.last_seen_at)}` : ""}
        </p>
        <small>Session IP/device detail is visible to Platform Owners only.</small>
      </CcCard>
    );
  }

  return (
    <>
      <CcCard
        title="Active sessions"
        icon={Fingerprint}
        actions={
          isSelf ? (
            <button className="secondary" onClick={() => setRevokeAllOpen(true)}>
              <LogOut aria-hidden size={16} strokeWidth={2} /> Sign out every other device
            </button>
          ) : undefined
        }
      >
        {!rows ? (
          <CcLoadingState label="Loading sessions…" />
        ) : (
          <CcRecordList emptyMessage="No active sessions.">
            {rows.map((row) => (
              <CcRecordCard
                key={row.id}
                title={row.user_agent}
                badge={"current" in row && row.current ? "This device" : undefined}
                badgeTone="info"
                meta={[`Signed in ${readableDate(row.created_at)} · Last active ${relativeTime(row.last_seen_at)} · ${row.source_ip}`]}
                actions={
                  isSelf && !("current" in row && row.current) ? (
                    <button type="button" className="tertiary" onClick={() => revokeOne(row.id)}>
                      Revoke
                    </button>
                  ) : undefined
                }
              />
            ))}
          </CcRecordList>
        )}
      </CcCard>

      <CcConfirmDialog
        open={revokeAllOpen}
        onClose={() => setRevokeAllOpen(false)}
        title="Sign out every other device"
        description="This signs you out of every session except this one."
        confirmLabel="Sign out other devices"
        variant="destructive"
        onConfirm={(formData) => runRevokeAllOthers(auditReason(formData))}
      />
    </>
  );
}

function ActivityTab({ audit }: { audit: AuditRow[] | null }) {
  const columns: CcTableColumn<AuditRow>[] = [
    { key: "when", header: "When", render: (row) => readableDate(row.created_at) },
    { key: "action", header: "Action", render: (row) => titleCase(row.action) },
    { key: "outcome", header: "Outcome", render: (row) => titleCase(row.outcome) },
    { key: "reason", header: "Reason", render: (row) => row.reason ?? "—" },
  ];
  return (
    <CcCard title="Activity">
      <CcTable
        columns={columns}
        rows={audit}
        rowKey={(row) => row.id}
        emptyMessage="No recorded activity for this administrator yet."
        caption="Administrator activity"
      />
    </CcCard>
  );
}
