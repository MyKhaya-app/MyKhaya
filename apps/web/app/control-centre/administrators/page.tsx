"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, UserPlus, XCircle } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import {
  invitationActionsAvailable,
  invitationStateBadgeClass,
} from "@/components/platform-mfa-logic";
import { readableDate, titleCase } from "@/components/platform-format";
import { PLATFORM_ROLES } from "@/components/platform-types";
import type { AdministratorInvitation, PlatformActor } from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection } from "@/components/control-centre/section";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge, toneFromStateClass } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";

type AdministratorRow = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  active: boolean;
  mfa_enrolled: boolean;
  last_login_at: string | null;
};

export default function AdministratorsPage() {
  const [me, setMe] = useState<PlatformActor | null>(null);
  const [rows, setRows] = useState<AdministratorRow[] | null>(null);
  const [invitations, setInvitations] = useState<AdministratorInvitation[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<AdministratorInvitation | null>(null);
  const { guarded, modal } = useReauthGuard();

  const isOwner = me?.role === "platform_owner";

  const load = useCallback(async () => {
    setError("");
    try {
      const [actor, administrators] = await Promise.all([
        platformApi.get<PlatformActor>("/auth/me"),
        platformApi.get<AdministratorRow[]>("/administrators"),
      ]);
      setMe(actor);
      setRows(administrators);
      if (actor.role === "platform_owner") {
        setInvitations(await platformApi.get<AdministratorInvitation[]>("/administrators/invitations"));
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load administrators.");
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const createInvitation = guarded(async (data: FormData) => {
    setError("");
    try {
      await platformApi.post("/administrators/invitations", {
        email: data.get("email"),
        display_name: data.get("display_name"),
        role: data.get("role"),
        reason: data.get("reason"),
        confirmed: true,
      });
      setMessage("Invitation sent.");
      setShowAddForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "The invitation could not be sent.");
    }
  });

  const resendInvitation = guarded(async (id: string) => {
    setError("");
    try {
      await platformApi.post(`/administrators/invitations/${id}/resend`, {});
      setMessage("Invitation resent — the previous link no longer works.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "The invitation could not be resent.");
    }
  });

  const revokeInvitation = guarded(async (id: string) => {
    setRevokeTarget(null);
    setError("");
    try {
      await platformApi.post(`/administrators/invitations/${id}/revoke`, {});
      setMessage("Invitation revoked.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "The invitation could not be revoked.");
    }
  });

  const administratorColumns: CcTableColumn<AdministratorRow>[] = [
    { key: "name", header: "Name", render: (row) => <a href={`/administrators/${row.id}`}>{row.display_name}</a> },
    { key: "email", header: "Email", render: (row) => row.email },
    { key: "role", header: "Role", render: (row) => titleCase(row.role) },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <CcBadge tone={row.active ? "success" : "danger"}>{row.active ? "Active" : "Deactivated"}</CcBadge>
      ),
    },
    {
      key: "mfa",
      header: "MFA",
      render: (row) => (
        <CcBadge tone={row.mfa_enrolled ? "success" : "warning"}>
          {row.mfa_enrolled ? "Enrolled" : "Not enrolled"}
        </CcBadge>
      ),
    },
    {
      key: "last-login",
      header: "Last sign-in",
      render: (row) => (row.last_login_at ? readableDate(row.last_login_at) : "Never"),
    },
  ];

  const invitationColumns: CcTableColumn<AdministratorInvitation>[] = [
    { key: "email", header: "Email", render: (row) => row.email },
    { key: "role", header: "Role", render: (row) => titleCase(row.role) },
    {
      key: "state",
      header: "State",
      render: (row) => (
        <CcBadge tone={toneFromStateClass(invitationStateBadgeClass(row.state))}>{titleCase(row.state)}</CcBadge>
      ),
    },
    { key: "invited-by", header: "Invited by", render: (row) => row.invited_by_display_name ?? "—" },
    { key: "invited", header: "Invited", render: (row) => readableDate(row.created_at) },
    { key: "expires", header: "Expires", render: (row) => readableDate(row.expires_at) },
    {
      key: "actions",
      header: "Actions",
      render: (row) =>
        invitationActionsAvailable(row.state) ? (
          <div className="cc-action-bar">
            <button type="button" className="tertiary" onClick={() => void resendInvitation(row.id)}>
              Resend
            </button>
            <button type="button" className="tertiary" onClick={() => setRevokeTarget(row)}>
              Revoke
            </button>
          </div>
        ) : null,
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Global privileged access"
          title="Administrators"
          description="The people who can access this global privileged environment — separate from Home Admins, who only manage their own Home and never gain Control Centre access."
          primaryAction={
            isOwner ? (
              <button onClick={() => setShowAddForm(true)}>
                <UserPlus aria-hidden size={16} strokeWidth={2} /> Add administrator
              </button>
            ) : undefined
          }
          secondaryActions={
            <button className="secondary" onClick={() => void load()}>
              <RefreshCw aria-hidden size={16} strokeWidth={2} /> Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        <CcSection title="Administrators">
          <CcTable
            columns={administratorColumns}
            rows={rows}
            rowKey={(row) => row.id}
            emptyMessage="No administrators."
            caption="Administrators"
          />
        </CcSection>

        {isOwner && (
          <CcSection title="Pending invitations">
            <CcTable
              columns={invitationColumns}
              rows={invitations}
              rowKey={(row) => row.id}
              emptyMessage="No invitations have been sent."
              caption="Pending invitations"
            />
          </CcSection>
        )}
      </CcPage>

      <CcDialog
        open={Boolean(showAddForm)}
        onClose={() => setShowAddForm(false)}
        title="Add administrator"
      >
        <form
          className="cc-dialog-form"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            void createInvitation(new FormData(event.currentTarget));
          }}
        >
          <div className="cc-dialog-scroll">
            <p>
              This sends a secure, single-use enrolment link that expires in 24 hours. The recipient sets
              their own password and completes MFA enrolment before they gain access — nothing here creates
              or shares a password on their behalf.
            </p>
            <CcField label="Display name">
              <input name="display_name" type="text" required maxLength={100} />
            </CcField>
            <CcField label="Email">
              <input name="email" type="email" required maxLength={320} />
            </CcField>
            <CcField label="Role">
              <select name="role" required defaultValue="platform_administrator">
                {PLATFORM_ROLES.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </CcField>
            <CcField label="Reason (at least 10 characters)">
              <input name="reason" type="text" required minLength={10} maxLength={500} />
            </CcField>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setShowAddForm(false)}>
              Cancel
            </button>
            <button type="submit">
              <Plus aria-hidden size={16} strokeWidth={2} /> Send invitation
            </button>
          </CcDialogActions>
        </form>
      </CcDialog>

      <CcDialog
        open={Boolean(revokeTarget)}
        onClose={() => setRevokeTarget(null)}
        title="Revoke invitation"
      >
        <div className="cc-dialog-scroll">
          <p>
            Revoke the invitation for {revokeTarget?.email}? The link will stop working immediately.
          </p>
        </div>
        <CcDialogActions>
          <button type="button" className="secondary" onClick={() => setRevokeTarget(null)}>
            Cancel
          </button>
          <button type="button" className="danger" onClick={() => revokeTarget && void revokeInvitation(revokeTarget.id)}>
            <XCircle aria-hidden size={16} strokeWidth={2} /> Revoke
          </button>
        </CcDialogActions>
      </CcDialog>

      {modal}
    </PlatformShell>
  );
}
