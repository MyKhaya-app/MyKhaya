"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { readableDate } from "@/components/platform-format";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcActionBar, type CcAction } from "@/components/control-centre/action-bar";
import { CcDangerZone } from "@/components/control-centre/danger-zone";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState, CcErrorState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { CcRecordCard, CcRecordList } from "@/components/control-centre/record-list";
import { MoveMemberDialog } from "@/components/control-centre/move-member-dialog";
import { Archive, ArchiveRestore, KeyRound, Mail, Power, ShieldOff, Shuffle, UserX } from "lucide-react";

type Lifecycle = "active" | "disabled" | "archived" | "anonymised";
type UserMfaState = {
  configured: "inherit" | "optional" | "required";
  effective: "optional" | "required";
  source: string;
  allowed_methods: string[];
  methods: { method: string; enabled: boolean }[];
};

type UserDetail = {
  id: string;
  email: string;
  display_name: string;
  verified: boolean;
  active: boolean;
  lifecycle: Lifecycle;
  anonymised_at?: string | null;
  created_at: string;
  last_login_at: string | null;
  last_activity_at: string | null;
  homes: { id: string; name: string; role: string }[];
  sessions: { id: string; user_agent: string; last_seen_at: string; expires_at: string }[];
  notes: { id: string; body: string; created_at: string }[];
  authentication_mfa: UserMfaState;
};

type GatedAction =
  | "suspend"
  | "reactivate"
  | "revoke-sessions"
  | "resend-verification"
  | "send-password-reset"
  | "archive"
  | "restore";

const safeError = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;

export default function PlatformUserDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [openDialog, setOpenDialog] = useState<GatedAction | null>(null);
  const [moveMemberOpen, setMoveMemberOpen] = useState(false);
  const [anonymiseOpen, setAnonymiseOpen] = useState(false);
  const [anonymiseBlockers, setAnonymiseBlockers] = useState<string[] | null>(null);
  const { guarded, modal } = useReauthGuard();

  async function load() {
    setLoading(true);
    try {
      const result = await platformApi.get<UserDetail>(`/users/${encodeURIComponent(id)}`);
      setData(result);
    } catch (cause) {
      setError(safeError(cause, "Unable to load this user."));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, [id]);

  // suspend/reactivate/revoke-sessions/resend-verification/send-password-reset
  // all hit endpoints the backend guards with require_recent_auth() (see
  // apps/api/mykhaya/routers/platform.py: _user_state_action,
  // revoke_user_sessions, _enqueue_user_mail) — `guarded` re-throws a 403
  // "recent authentication required" so useReauthGuard can show
  // PlatformReauthModal and transparently retry the same action once the
  // operator re-authenticates. The GET load and note-adding below are not
  // recent-auth-gated server-side, so they are never wrapped.
  const runAction = guarded(async (action: GatedAction, formData: FormData) => {
    setOpenDialog(null);
    setBusy(action);
    setError("");
    try {
      const result = await platformApi.post<{ message: string }>(`/users/${encodeURIComponent(id)}/${action}`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage(result.message);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, `Unable to complete this action.`));
    } finally {
      setBusy("");
    }
  });

  async function openAnonymise() {
    setAnonymiseBlockers(null);
    setAnonymiseOpen(true);
    try {
      const result = await platformApi.get<{ eligible: boolean; blockers: string[] }>(
        `/users/${encodeURIComponent(id)}/anonymise/eligibility`,
      );
      setAnonymiseBlockers(result.blockers);
    } catch (cause) {
      setAnonymiseBlockers([safeError(cause, "Unable to check anonymisation eligibility.")]);
    }
  }

  // The backend independently revalidates every precondition on the mutation
  // itself (see routers.platform.anonymise_user) — the eligibility preflight
  // above is purely a UX convenience so operators see blockers before typing
  // a confirmation, not a substitute for that server-side check.
  const runAnonymise = guarded(async (formData: FormData) => {
    setAnonymiseOpen(false);
    setBusy("anonymise");
    setError("");
    try {
      const result = await platformApi.post<{ message: string }>(`/users/${encodeURIComponent(id)}/anonymise`, {
        reason: formData.get("audit_reason"),
        confirmation_text: formData.get("confirmation_text"),
        confirmed: true,
      });
      setMessage(result.message);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to anonymise this user."));
    } finally {
      setBusy("");
    }
  });

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await platformApi.post(`/users/${encodeURIComponent(id)}/notes`, { body: form.get("note") });
      formElement.reset();
      setMessage("Administrative note added.");
      await load();
    } catch (cause) {
      setError(safeError(cause, "Unable to add this note."));
    }
  }

  const updateMfaPolicy = guarded(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("mfa-policy");
    setError("");
    try {
      await platformApi.put(`/users/${encodeURIComponent(id)}/auth/mfa-policy`, {
        policy: form.get("policy"),
        allowed_methods: ["totp", "email"],
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage("User MFA policy updated.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to update the user MFA policy."));
    } finally {
      setBusy("");
    }
  });

  const statusTone: CcBadgeTone =
    data?.lifecycle === "anonymised"
      ? "neutral"
      : data?.lifecycle === "archived"
        ? "neutral"
        : data?.lifecycle === "active"
          ? "success"
          : "danger";
  const statusLabel =
    data?.lifecycle === "anonymised"
      ? "Anonymised"
      : data?.lifecycle === "archived"
        ? "Archived"
        : data?.lifecycle === "active"
          ? "Active"
          : "Disabled";

  // Anonymised is a dead end — the identity is gone, so no action (not even
  // Restore) makes sense on it (Slice 5B §20/§10). Archived is retired but
  // reversible — Restore is its only sensible action (see Slice 3: "Do not
  // offer nonsensical actions such as 'Reactivate' and 'Restore'
  // simultaneously").
  const actions: CcAction[] = !data
    ? []
    : data.lifecycle === "anonymised"
      ? []
      : data.lifecycle === "archived"
        ? [
            {
              key: "restore",
              label: "Restore user",
              icon: ArchiveRestore,
              variant: "primary" as const,
              disabled: Boolean(busy),
              onClick: () => setOpenDialog("restore"),
            },
          ]
        : [
          ...(data.lifecycle === "disabled"
            ? [
                {
                  key: "reactivate",
                  label: "Reactivate user",
                  icon: Power,
                  variant: "primary" as const,
                  disabled: Boolean(busy),
                  onClick: () => setOpenDialog("reactivate"),
                },
              ]
            : []),
          {
            key: "revoke-sessions",
            label: "Revoke all sessions",
            icon: ShieldOff,
            variant: "destructive",
            disabled: Boolean(busy),
            onClick: () => setOpenDialog("revoke-sessions"),
          },
          ...(data.homes.length > 0
            ? [
                {
                  key: "move-member",
                  label: "Move member",
                  icon: Shuffle,
                  variant: "secondary" as const,
                  disabled: Boolean(busy),
                  onClick: () => setMoveMemberOpen(true),
                },
              ]
            : []),
          ...(!data.verified
            ? [
                {
                  key: "resend-verification",
                  label: "Resend verification email",
                  icon: Mail,
                  variant: "secondary" as const,
                  disabled: Boolean(busy),
                  onClick: () => setOpenDialog("resend-verification"),
                },
              ]
            : []),
          {
            key: "send-password-reset",
            label: "Send password-reset email",
            icon: KeyRound,
            variant: "secondary",
            disabled: Boolean(busy),
            onClick: () => setOpenDialog("send-password-reset"),
          },
        ];

  const dialogCopy: Record<GatedAction, { title: string; description: string; confirmLabel: string; variant?: "destructive" }> = {
    suspend: {
      title: "Suspend user",
      description: "Suspend this user? They will be signed out of every session and unable to sign in until reactivated.",
      confirmLabel: "Suspend user",
      variant: "destructive",
    },
    reactivate: {
      title: "Reactivate user",
      description: "Reactivate this user and allow them to sign in again?",
      confirmLabel: "Reactivate user",
    },
    "revoke-sessions": {
      title: "Revoke all sessions",
      description: "Revoke every active session and trusted device for this user? They will need to sign in again everywhere.",
      confirmLabel: "Revoke all sessions",
      variant: "destructive",
    },
    "resend-verification": {
      title: "Resend verification email",
      description: "Send a new verification email to this user?",
      confirmLabel: "Resend verification",
    },
    "send-password-reset": {
      title: "Send password-reset email",
      description: "Send a password-reset email to this user?",
      confirmLabel: "Send reset email",
    },
    archive: {
      title: "Archive user",
      description:
        "Archiving this user prevents sign-in and removes the account from normal operational views. Historical data and memberships are retained.",
      confirmLabel: "Archive user",
      variant: "destructive",
    },
    restore: {
      title: "Restore user",
      description: "Restore this user to Active? They will need to sign in again normally.",
      confirmLabel: "Restore user",
    },
  };

  return (
    <PlatformShell>
      <CcPage wide className="cc-user-detail">
        <a className="cc-user-back-link" href="/users">&larr; Users</a>
        {loading ? (
          <CcLoadingState label="Loading user…" />
        ) : !data ? (
          <CcErrorState>{error || "User not found."}</CcErrorState>
        ) : (
          <>
            <div className="cc-user-record-header">
              <CcPageHeader
                eyebrow="User account"
                title={data.display_name}
                description={data.email}
              />
              <CcBadge tone={statusTone}>{statusLabel}</CcBadge>
            </div>
            {message && <CcNotice tone="success">{message}</CcNotice>}
            {error && <CcNotice tone="error">{error}</CcNotice>}

            <div className="cc-user-primary-grid">
              <section className="cc-user-card cc-user-account-card">
                <div className="cc-user-card-heading">
                  <div>
                    <span className="cc-user-card-kicker">Account</span>
                    <h2>Account details</h2>
                  </div>
                  <CcBadge tone={data.verified ? "success" : "warning"}>
                    {data.verified ? "Verified" : "Unverified"}
                  </CcBadge>
                </div>
                <CcStatusCard
                  tone={statusTone}
                  status={statusLabel}
                  items={[{ label: "Email verification", value: data.verified ? "Verified" : "Unverified" }]}
                />
                <dl className="cc-user-metadata-list">
                  <div><dt>Created</dt><dd>{readableDate(data.created_at)}</dd></div>
                  <div><dt>Last login</dt><dd>{data.last_login_at ? readableDate(data.last_login_at) : "Never"}</dd></div>
                  <div><dt>Last active</dt><dd>{data.last_activity_at ? readableDate(data.last_activity_at) : "Never"}</dd></div>
                </dl>
              </section>

              <section className="cc-user-card cc-user-membership-card">
                <div className="cc-user-card-heading">
                  <div><span className="cc-user-card-kicker">Access</span><h2>Homes and memberships</h2></div>
                </div>
                <div className="cc-user-membership-list">
                  <CcRecordList variant="grid" emptyMessage="Not a member of any Home.">
                    {data.homes.map((home) => (
                      <CcRecordCard key={home.id} title={home.name} meta={[home.role.replaceAll("_", " ")]} />
                    ))}
                  </CcRecordList>
                </div>
              </section>
            </div>

            <section className="cc-user-card cc-user-security-card cc-user-security-section">
              <div className="cc-user-card-heading">
                <div><span className="cc-user-card-kicker">Security</span><h2>Authentication &amp; MFA</h2></div>
              </div>
              <div className="cc-user-mfa-summary">
                <CcMetadataGrid>
                  <CcMetadataItem label="Configured">{data.authentication_mfa.configured}</CcMetadataItem>
                  <CcMetadataItem label="Effective">{data.authentication_mfa.effective}</CcMetadataItem>
                  <CcMetadataItem label="Source">{data.authentication_mfa.source}</CcMetadataItem>
                  <CcMetadataItem label="Enrolled methods">
                    {data.authentication_mfa.methods.filter((method) => method.enabled).map((method) => method.method).join(", ") || "None"}
                  </CcMetadataItem>
                </CcMetadataGrid>
              </div>
              <div className="cc-user-form-divider" />
                <form className="cc-user-mfa-form" onSubmit={updateMfaPolicy}>
                  <CcField label="User policy override">
                    <select name="policy" defaultValue={data.authentication_mfa.configured}>
                      <option value="inherit">Inherit</option>
                      <option value="optional">Optional</option>
                      <option value="required">Force MFA</option>
                    </select>
                  </CcField>
                  <CcField label="Reason for this change">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  <button disabled={Boolean(busy)}>Save MFA policy</button>
                </form>
                <small className="cc-user-security-note">Authenticator secrets and verification codes are never shown here. TOTP reset/removal is intentionally unavailable.</small>
            </section>

            <div className="cc-user-secondary-grid">
              <section className="cc-user-card cc-user-sessions-card cc-user-sessions-section">
                <div className="cc-user-card-heading"><div><span className="cc-user-card-kicker">Access history</span><h2>Active sessions</h2></div></div>
                <CcRecordList variant="grid" emptyMessage="No active sessions.">
                  {data.sessions.map((session) => (
                    <CcRecordCard key={session.id} title={session.user_agent} meta={[`Last seen ${new Date(session.last_seen_at).toLocaleString()}`]} />
                  ))}
                </CcRecordList>
              </section>

              <section className="cc-user-card cc-user-notes-card cc-user-notes-section">
                <div className="cc-user-card-heading"><div><span className="cc-user-card-kicker">Internal record</span><h2>Administrative notes</h2></div></div>
                <form className="cc-user-note-form" onSubmit={addNote}>
                  <CcField label="New internal note">
                    <textarea name="note" minLength={2} maxLength={1000} required />
                  </CcField>
                  <div className="cc-action-bar">
                    <button className="cc-action cc-action-primary">Add administrative note</button>
                  </div>
                </form>
              <CcRecordList emptyMessage="No administrative notes yet.">
                {data.notes.map((note) => (
                  <CcRecordCard key={note.id} title={new Date(note.created_at).toLocaleString()}>
                    <p>{note.body}</p>
                  </CcRecordCard>
                ))}
              </CcRecordList>
              </section>
            </div>

            <section className="cc-user-card cc-user-actions-card cc-user-actions-section">
              <div className="cc-user-card-heading"><div><span className="cc-user-card-kicker">Administration</span><h2>Actions</h2></div></div>
              <CcActionBar actions={actions} />
            </section>

            <div className="cc-user-danger-zone">
              {data.lifecycle !== "archived" && data.lifecycle !== "anonymised" && (
                <CcDangerZone
                title="Suspend or archive user"
                description="Suspending this user signs them out everywhere and blocks sign-in until reactivated. Archiving does the same but also retires the account from normal operational views — restore it later to bring it back."
              >
                <CcActionBar
                  actions={[
                    ...(data.lifecycle === "active"
                      ? [
                          {
                            key: "suspend",
                            label: "Suspend user",
                            icon: ShieldOff,
                            variant: "destructive" as const,
                            disabled: Boolean(busy),
                            onClick: () => setOpenDialog("suspend"),
                          },
                        ]
                      : []),
                    {
                      key: "archive",
                      label: "Archive user",
                      icon: Archive,
                      variant: "destructive",
                      disabled: Boolean(busy),
                      onClick: () => setOpenDialog("archive"),
                    },
                  ]}
                />
                </CcDangerZone>
              )}

              {data.lifecycle === "archived" && (
                <CcDangerZone
                title="Anonymise user"
                description="This permanently removes the user's identifying account information and sign-in credentials while retaining historical household records under an anonymised identity. This cannot be undone."
              >
                <CcActionBar
                  actions={[
                    {
                      key: "anonymise",
                      label: "Anonymise user",
                      icon: UserX,
                      variant: "destructive",
                      disabled: Boolean(busy),
                      onClick: () => void openAnonymise(),
                    },
                  ]}
                />
                </CcDangerZone>
              )}
            </div>
          </>
        )}
      </CcPage>

      {(Object.keys(dialogCopy) as GatedAction[]).map((action) => (
        <CcConfirmDialog
          key={action}
          open={openDialog === action}
          onClose={() => setOpenDialog(null)}
          title={dialogCopy[action].title}
          description={dialogCopy[action].description}
          confirmLabel={dialogCopy[action].confirmLabel}
          variant={dialogCopy[action].variant}
          onConfirm={(formData) => runAction(action, formData)}
        />
      ))}

      {data && (
        <CcConfirmDialog
          open={anonymiseOpen}
          onClose={() => setAnonymiseOpen(false)}
          title="Anonymise user"
          description="This permanently removes the user's identifying account information and sign-in credentials while retaining historical household records under an anonymised identity. This cannot be undone. Restore will no longer be available."
          confirmLabel="Anonymise user"
          variant="destructive"
          onConfirm={(formData) => {
            if (!anonymiseBlockers || anonymiseBlockers.length === 0) void runAnonymise(formData);
          }}
          extraFields={
            <>
              {anonymiseBlockers === null && <p>Checking eligibility…</p>}
              {anonymiseBlockers && anonymiseBlockers.length > 0 && (
                <CcNotice tone="error">This user cannot be anonymised yet: {anonymiseBlockers.join(", ")}</CcNotice>
              )}
              <label>
                Type this user&rsquo;s current email to confirm ({data.email})
                <input name="confirmation_text" type="text" required autoComplete="off" />
              </label>
            </>
          }
        />
      )}

      {data && (
        <MoveMemberDialog
          open={moveMemberOpen}
          onClose={() => setMoveMemberOpen(false)}
          userId={data.id}
          userDisplayName={data.display_name}
          userEmail={data.email}
          sourceHomes={data.homes}
          onMoved={(moveMessage) => {
            setMessage(moveMessage);
            void load();
          }}
        />
      )}

      {modal}
    </PlatformShell>
  );
}
