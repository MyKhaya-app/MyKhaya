"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
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
    if (!window.confirm("Revoke this invitation? The link will stop working immediately."))
      return;
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

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Global privileged access</p>
            <h1>Administrators</h1>
          </div>
          <div className="platform-modal-actions">
            {isOwner && (
              <button className="secondary" onClick={() => setShowAddForm(true)}>
                Add administrator
              </button>
            )}
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          </div>
        </div>
        <p className="scope-note">
          The people who can access this global privileged environment — separate from Home
          Admins, who only manage their own Home and never gain Control Centre access.
        </p>
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
        {!rows ? (
          <p role="status">Loading administrators…</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>MFA</th>
                  <th>Last sign-in</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link href={`/administrators/${row.id}`}>{row.display_name}</Link>
                    </td>
                    <td>{row.email}</td>
                    <td>{titleCase(row.role)}</td>
                    <td>
                      <strong
                        className={`state-label ${row.active ? "state-healthy" : "state-unavailable"}`}
                      >
                        {row.active ? "Active" : "Deactivated"}
                      </strong>
                    </td>
                    <td>
                      <strong
                        className={`state-label ${row.mfa_enrolled ? "state-healthy" : "state-not-configured"}`}
                      >
                        {row.mfa_enrolled ? "Enrolled" : "Not enrolled"}
                      </strong>
                    </td>
                    <td>{row.last_login_at ? readableDate(row.last_login_at) : "Never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {isOwner && (
          <section className="action-panel">
            <h2>Pending invitations</h2>
            {!invitations ? (
              <p role="status">Loading invitations…</p>
            ) : invitations.length === 0 ? (
              <p className="quiet-state">No invitations have been sent.</p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Role</th>
                      <th>State</th>
                      <th>Invited by</th>
                      <th>Invited</th>
                      <th>Expires</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invitations.map((invitation) => (
                      <tr key={invitation.id}>
                        <td>{invitation.email}</td>
                        <td>{titleCase(invitation.role)}</td>
                        <td>
                          <strong
                            className={`state-label ${invitationStateBadgeClass(invitation.state)}`}
                          >
                            {titleCase(invitation.state)}
                          </strong>
                        </td>
                        <td>{invitation.invited_by_display_name ?? "—"}</td>
                        <td>{readableDate(invitation.created_at)}</td>
                        <td>{readableDate(invitation.expires_at)}</td>
                        <td>
                          {invitationActionsAvailable(invitation.state) && (
                            <div className="platform-modal-actions">
                              <button
                                type="button"
                                className="tertiary"
                                onClick={() => resendInvitation(invitation.id)}
                              >
                                Resend
                              </button>
                              <button
                                type="button"
                                className="tertiary"
                                onClick={() => revokeInvitation(invitation.id)}
                              >
                                Revoke
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </main>

      {showAddForm && (
        <div
          className="platform-modal-backdrop"
          role="presentation"
          onClick={() => setShowAddForm(false)}
        >
          <div
            className="platform-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-administrator-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="add-administrator-title">Add administrator</h2>
            <p>
              This sends a secure, single-use enrolment link that expires in 24 hours. The
              recipient sets their own password and completes MFA enrolment before they gain
              access — nothing here creates or shares a password on their behalf.
            </p>
            <form
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                void createInvitation(new FormData(event.currentTarget));
              }}
            >
              <label>
                Display name
                <input name="display_name" type="text" required maxLength={100} />
              </label>
              <label>
                Email
                <input name="email" type="email" required maxLength={320} />
              </label>
              <label>
                Role
                <select name="role" required defaultValue="platform_administrator">
                  {PLATFORM_ROLES.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reason (at least 10 characters)
                <input name="reason" type="text" required minLength={10} maxLength={500} />
              </label>
              <div className="platform-modal-actions">
                <button type="button" className="secondary" onClick={() => setShowAddForm(false)}>
                  Cancel
                </button>
                <button type="submit">Send invitation</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {modal}
    </PlatformShell>
  );
}
