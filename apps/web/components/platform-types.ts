// Shared types for the new MFA/administrator-security surface. Most existing
// Control Centre pages redeclare their own local response shapes inline
// (there's no shared platform-types module in this codebase yet) — this file
// exists because the MFA flow's shapes are reused across several new pages
// (login, setup-mfa, security, administrators), not to retrofit the rest of
// the Control Centre.

export type PlatformSessionStatus = "full" | "pending_mfa" | "mfa_setup_required";

export type PlatformActor = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  mfa_enrolled: boolean;
  session_status: PlatformSessionStatus;
  // Only populated at session_status "pending_mfa" — the fallback methods
  // that genuinely exist for this account, so the login page never offers a
  // method that isn't actually set up. Optional here only because existing
  // callers construct PlatformActor values for other session statuses,
  // where the backend always sends an empty array.
  available_factors?: ("passkey" | "totp" | "recovery_code")[];
  // Only populated once, atomically with the response that completes this
  // administrator's first MFA factor — never retrievable again afterwards.
  recovery_codes?: string[] | null;
};

export type WebAuthnCredential = {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
};

// PCC-SEC-006: GET /administrators/{id}/security returns one of two shapes
// depending on the viewer's role — the full detail (with per-credential and
// per-session data) for an Owner viewer, or a reduced summary (counts only,
// no raw session IPs/user-agents/session IDs, no per-credential labels) for
// an Administrator/Security viewer. Modelled as one type with the
// full-detail-only fields optional, rather than two separate types, so the
// tab components below can render either shape without a big branch.
export type AdministratorSecurity = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  mfa_enrolled: boolean;
  totp_enabled: boolean;
  totp_verified_at: string | null;
  recovery_codes_remaining: number;
  // Full-detail fields — present only when the viewer is an Owner.
  webauthn_credentials?: WebAuthnCredential[];
  sessions?: AdminSessionSummary[];
  // Summary fields — present only when the viewer is an Administrator or
  // Security operator (i.e. webauthn_credentials/sessions are absent).
  webauthn_credential_count?: number;
  active_session_count?: number;
  last_seen_at?: string | null;
};

export type AdminSessionSummary = {
  id: string;
  created_at: string;
  last_seen_at: string;
  absolute_expires_at: string;
  user_agent: string;
  source_ip: string;
  // Only present when viewing your own session list.
  current?: boolean;
};

export type MfaPolicy = {
  required: boolean;
  environment_enforced: boolean;
};

export type InvitationState = "pending" | "accepted" | "expired" | "revoked";

export type AdministratorInvitation = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  state: InvitationState;
  invited_by_display_name: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
};

export type AdministratorInvitationPreview = {
  email: string;
  display_name: string;
  role: string;
  invited_by_display_name: string | null;
  expires_at: string;
};

export const PLATFORM_ROLES: { value: string; label: string }[] = [
  { value: "platform_owner", label: "Owner" },
  { value: "platform_administrator", label: "Administrator" },
  { value: "security_operator", label: "Security" },
  { value: "support_operator", label: "Support" },
  { value: "read_only_operator", label: "Read-only" },
];
