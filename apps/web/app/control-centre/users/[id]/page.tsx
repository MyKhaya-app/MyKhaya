"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, usePathname } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { readableDate } from "@/components/platform-format";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcRecordCard, CcRecordList } from "@/components/control-centre/record-list";
import { CcActionBar, type CcAction } from "@/components/control-centre/action-bar";
import { CcDangerZone } from "@/components/control-centre/danger-zone";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState, CcErrorState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { MoveMemberDialog } from "@/components/control-centre/move-member-dialog";
import {
  Archive, ArchiveRestore, CalendarDays, ChevronRight, Clock3, Copy,
  FileText, Home, KeyRound, Mail, Power, Shield, ShieldOff,
  Shuffle, UserRound, UserRoundCog, UsersRound, UserX,
} from "lucide-react";

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

function detailDate(value: string | null) {
  return value ? new Date(value).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Never";
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function methodLabel(method: string) {
  return method.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function PlatformUserDetail() {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const activeTab = pathname.endsWith("/account")
    ? "account"
    : pathname.endsWith("/authentication")
      ? "authentication"
      : pathname.endsWith("/homes")
        ? "homes"
        : pathname.endsWith("/permissions")
          ? "permissions"
          : pathname.endsWith("/activity")
            ? "activity"
            : pathname.endsWith("/notes")
              ? "notes"
              : "overview";
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

  function UserProfileView() {
    if (loading) return <CcLoadingState label="Loading user…" />;
    if (!data) return <CcErrorState>{error || "User not found."}</CcErrorState>;

    return (
      <>
        <div className="cc-user-profile-breadcrumb"><a href="/users"><span aria-hidden="true">←</span> Users</a><ChevronRight aria-hidden="true" size={15} /><span>{data.display_name}</span></div>
        <header className="cc-user-profile-header">
          <div className="cc-user-profile-identity"><div className="cc-user-profile-icon" aria-hidden="true"><UserRound size={27} /></div><div><div className="cc-user-profile-name"><h1>{data.display_name}</h1><CcBadge tone={statusTone}>{statusLabel}</CcBadge></div><p>{data.email}</p><div className="cc-user-profile-id"><span>User ID: {data.id}</span><button type="button" aria-label="Copy user ID" onClick={() => void navigator.clipboard?.writeText(data.id)}><Copy size={16} /></button></div></div></div>
          <div className="cc-user-profile-header-side"><div className="cc-user-profile-actions"><a className="cc-user-profile-secondary" href="/users">←&nbsp; Back to Users</a></div><dl className="cc-user-profile-meta"><div><dt>Created</dt><dd>{detailDate(data.created_at)}</dd></div><div><dt>Last login</dt><dd>{detailDate(data.last_login_at)}</dd></div><div><dt>Last active</dt><dd>{detailDate(data.last_activity_at)}</dd></div></dl></div>
        </header>
        {message && <CcNotice tone="success">{message}</CcNotice>}{error && <CcNotice tone="error">{error}</CcNotice>}
        <nav className="cc-user-profile-tabs-route-top" aria-label="User detail sections"><a className={activeTab === "overview" ? "is-active" : undefined} href={`/users/${id}`}><Clock3 size={17} /> Overview</a><a className={activeTab === "account" ? "is-active" : undefined} href={`/users/${id}/account`}><UserRoundCog size={17} /> Account</a><a className={activeTab === "authentication" ? "is-active" : undefined} href={`/users/${id}/authentication`}><Shield size={17} /> Authentication</a><a className={activeTab === "homes" ? "is-active" : undefined} href={`/users/${id}/homes`}><Home size={17} /> Homes</a><a className={activeTab === "permissions" ? "is-active" : undefined} href={`/users/${id}/permissions`}><UsersRound size={17} /> Permissions</a><a className={activeTab === "activity" ? "is-active" : undefined} href={`/users/${id}/activity`}><Clock3 size={17} /> Activity</a><a className={activeTab === "notes" ? "is-active" : undefined} href={`/users/${id}/notes`}><FileText size={17} /> Notes</a></nav>
        <nav className="cc-user-profile-tabs" aria-label="User detail sections"><a className="is-active" href="#overview"><Clock3 size={17} /> Overview</a><a href="#account"><UserRoundCog size={17} /> Account</a><a href="#authentication"><Shield size={17} /> Authentication</a><a href="#homes"><Home size={17} /> Homes</a><a href="#permissions"><UsersRound size={17} /> Permissions</a><a href="#activity"><Clock3 size={17} /> Activity</a><a href="#notes"><FileText size={17} /> Notes</a></nav>
        <section className="cc-user-summary" id="overview"><div className="cc-user-summary-person"><span className="cc-user-summary-avatar">{initials(data.display_name)}</span><div><strong>{data.display_name}</strong><span>{data.email}</span></div></div><div className="cc-user-summary-item"><span>Status</span><strong><CcBadge tone={statusTone}>{statusLabel}</CcBadge></strong></div><div className="cc-user-summary-item"><span>Email</span><strong><Mail size={16} /><CcBadge tone={data.verified ? "success" : "warning"}>{data.verified ? "Verified" : "Unverified"}</CcBadge></strong></div><div className="cc-user-summary-item"><span>MFA</span><strong><Shield size={16} /><CcBadge tone="info">{methodLabel(data.authentication_mfa.effective)}</CcBadge></strong></div><div className="cc-user-summary-item"><span>Homes</span><strong><Home size={16} /> {data.homes.length}</strong></div><div className="cc-user-summary-item"><span>Member since</span><strong><CalendarDays size={16} /> {detailDate(data.created_at)}</strong></div></section>
        <nav className="cc-user-profile-tabs-route" aria-label="User detail sections"><a className={activeTab === "overview" ? "is-active" : undefined} href={`/users/${id}`}><Clock3 size={17} /> Overview</a><a className={activeTab === "account" ? "is-active" : undefined} href={`/users/${id}/account`}><UserRoundCog size={17} /> Account</a><a className={activeTab === "authentication" ? "is-active" : undefined} href={`/users/${id}/authentication`}><Shield size={17} /> Authentication</a><a className={activeTab === "homes" ? "is-active" : undefined} href={`/users/${id}/homes`}><Home size={17} /> Homes</a><a className={activeTab === "permissions" ? "is-active" : undefined} href={`/users/${id}/permissions`}><UsersRound size={17} /> Permissions</a><a className={activeTab === "activity" ? "is-active" : undefined} href={`/users/${id}/activity`}><Clock3 size={17} /> Activity</a><a className={activeTab === "notes" ? "is-active" : undefined} href={`/users/${id}/notes`}><FileText size={17} /> Notes</a></nav>
        <div className="cc-user-detail-grid">
          <section className="cc-user-profile-card" id="account"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><UserRoundCog size={19} /></span><h2>Account Details</h2><button type="button" className="cc-user-profile-link-button" disabled>Edit</button></div><dl className="cc-user-profile-list"><div><dt>Full name</dt><dd>{data.display_name}</dd></div><div><dt>Email address</dt><dd>{data.email} <CcBadge tone={data.verified ? "success" : "warning"}>{data.verified ? "Verified" : "Unverified"}</CcBadge></dd></div><div><dt>Phone number</dt><dd className="is-muted">Not provided</dd></div><div><dt>Date of birth</dt><dd className="is-muted">Not provided</dd></div><div><dt>Account created</dt><dd>{detailDate(data.created_at)}</dd></div><div><dt>Last login</dt><dd>{detailDate(data.last_login_at)}</dd></div><div><dt>Last active</dt><dd>{detailDate(data.last_activity_at)}</dd></div><div><dt>Status</dt><dd><CcBadge tone={statusTone}>{statusLabel}</CcBadge></dd></div></dl></section>
          <section className="cc-user-profile-card" id="authentication"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><Shield size={19} /></span><h2>Authentication &amp; MFA</h2><button type="button" className="cc-user-profile-link-button" disabled>Edit</button></div><dl className="cc-user-profile-list"><div><dt>MFA status</dt><dd><CcBadge tone="warning">{methodLabel(data.authentication_mfa.effective)}</CcBadge><small>This user has not enabled two-factor authentication.</small></dd></div><div><dt>Policy override</dt><dd>{data.authentication_mfa.configured === "inherit" ? "Inherit from Home" : methodLabel(data.authentication_mfa.configured)}</dd></div><div><dt>Allowed methods</dt><dd><span className="cc-user-chip-list">{data.authentication_mfa.allowed_methods.map((method) => <span className="cc-user-chip" key={method}>{methodLabel(method)}</span>)}</span></dd></div><div><dt>Enrolled methods</dt><dd>{data.authentication_mfa.methods.filter((method) => method.enabled).map((method) => methodLabel(method.method)).join(", ") || "None"}</dd></div></dl><form className="cc-user-mfa-form" onSubmit={updateMfaPolicy}><CcField label="User policy override"><select name="policy" defaultValue={data.authentication_mfa.configured}><option value="inherit">Inherit</option><option value="optional">Optional</option><option value="required">Force MFA</option></select></CcField><CcField label="Reason for this change"><input name="reason" minLength={10} maxLength={500} required /></CcField><button disabled={Boolean(busy)}><Mail size={16} /> Save MFA policy</button></form><small className="cc-user-security-note">Authenticator secrets and verification codes are never shown here. TOTP reset/removal is intentionally unavailable.</small></section>
          <div className="cc-user-profile-side-column"><section className="cc-user-profile-card" id="homes"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><Home size={19} /></span><h2>Homes &amp; Memberships</h2><button type="button" className="cc-user-profile-link-button" disabled>Manage</button></div><div className="cc-user-profile-card-body"><strong>{data.homes.length} {data.homes.length === 1 ? "home" : "homes"}</strong>{data.homes.length ? data.homes.map((home) => <div className="cc-user-home-item" key={home.id}><Home size={19} /><span><strong>{home.name}</strong><small>{methodLabel(home.role)}</small></span><CcBadge tone="info">{home.role.replaceAll("_", " ")}</CcBadge></div>) : <p className="is-muted">Not a member of any Home.</p>}</div></section><section className="cc-user-profile-card" id="permissions"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><UsersRound size={19} /></span><h2>Roles &amp; Permissions</h2><button type="button" className="cc-user-profile-link-button" disabled>Manage</button></div><dl className="cc-user-profile-list cc-user-permissions-list"><div><dt>Home role</dt><dd>{data.homes[0] ? methodLabel(data.homes[0].role) : "None"}</dd></div><div><dt>Home memberships</dt><dd>{data.homes.length}</dd></div><div><dt>Platform access</dt><dd>Not part of this user record</dd></div></dl></section></div>
        </div>
        <div className="cc-user-bottom-grid"><section className="cc-user-profile-card" id="activity"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><Clock3 size={19} /></span><h2>Recent Activity</h2><a className="cc-user-profile-link-button" href="#activity">View all</a></div><div className="cc-user-activity-list">{data.sessions.length ? data.sessions.map((session) => <div className="cc-user-activity-item" key={session.id}><span className="cc-user-activity-dot" /><div><strong>User session active</strong><small>{detailDate(session.last_seen_at)} · {session.user_agent}</small></div></div>) : <p className="cc-user-profile-empty">No recent activity available.</p>}</div></section><section className="cc-user-profile-card" id="notes"><div className="cc-user-profile-card-heading"><span className="cc-user-profile-card-icon"><FileText size={19} /></span><h2>Administrative Notes</h2><button type="submit" form="cc-user-note-form" className="cc-user-profile-link-button">Add note</button></div><form className="cc-user-note-form" id="cc-user-note-form" onSubmit={addNote}><CcField label=""><textarea name="note" minLength={2} maxLength={1000} required placeholder="Add an internal note about this user…" /></CcField><div className="cc-user-note-footer"><span>Notes are only visible to PCC administrators.</span><span>0/500</span></div></form><div className="cc-user-notes-list">{data.notes.length ? data.notes.map((note) => <article key={note.id}><strong>{detailDate(note.created_at)}</strong><p>{note.body}</p></article>) : <p className="cc-user-profile-empty">No administrative notes yet.</p>}</div></section></div>
        <section className="cc-user-card cc-user-actions-card cc-user-actions-section"><div className="cc-user-card-heading"><div><span className="cc-user-card-kicker">Administration</span><h2>Actions</h2></div></div><CcActionBar actions={actions} /></section>
        <div className="cc-user-danger-zone">{data.lifecycle !== "archived" && data.lifecycle !== "anonymised" && <CcDangerZone title="Suspend or archive user" description="Suspending this user signs them out everywhere and blocks sign-in until reactivated. Archiving does the same but also retires the account from normal operational views — restore it later to bring it back."><CcActionBar actions={[...(data.lifecycle === "active" ? [{ key: "suspend", label: "Suspend user", icon: ShieldOff, variant: "destructive" as const, disabled: Boolean(busy), onClick: () => setOpenDialog("suspend") }] : []), { key: "archive", label: "Archive user", icon: Archive, variant: "destructive", disabled: Boolean(busy), onClick: () => setOpenDialog("archive") }]} /></CcDangerZone>}{data.lifecycle === "archived" && <CcDangerZone title="Anonymise user" description="This permanently removes the user's identifying account information and sign-in credentials while retaining historical household records under an anonymised identity. This cannot be undone."><CcActionBar actions={[{ key: "anonymise", label: "Anonymise user", icon: UserX, variant: "destructive", disabled: Boolean(busy), onClick: () => void openAnonymise() }]} /></CcDangerZone>}</div>
      </>
    );
  }

  return (
    <PlatformShell>
      <CcPage wide className={`cc-user-detail cc-user-profile-page is-tab-${activeTab}`}>
        <UserProfileView />
        <div className="cc-user-legacy-content">
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
        </div>
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
