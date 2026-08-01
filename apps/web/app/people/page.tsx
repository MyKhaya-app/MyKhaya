"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { InvitationListItem, Member } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

function expiration(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function People() {
  const { activeHome, activeHomeId } = useActiveHome();
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<InvitationListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const canInvite = useMemo(
    () => ["owner", "administrator"].includes(activeHome?.role ?? ""),
    [activeHome?.role],
  );

  async function load() {
    if (!activeHomeId) return;
    const [membersData, invitationsData] = await Promise.all([
      api.members(activeHomeId),
      canInvite ? api.listInvitations(activeHomeId) : Promise.resolve([]),
    ]);
    setMembers(membersData);
    setInvitations(invitationsData);
  }

  useEffect(() => {
    load().catch((reason: Error) => setError(reason.message));
  }, [activeHomeId, canInvite]);

  async function invite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!activeHomeId) return;
    const d = new FormData(e.currentTarget);
    try {
      await api.post("/invitations", {
        group_id: activeHomeId,
        email: d.get("email"),
        role: d.get("role"),
      });
      setMessage("Invitation sent. The join link was emailed securely.");
      setError("");
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "We could not send that invitation.",
      );
    }
  }

  async function resend(invitationId: string) {
    try {
      await api.resendInvitation(invitationId);
      setMessage("Invitation resent.");
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "Could not resend invitation.",
      );
    }
  }

  async function revoke(invitationId: string) {
    try {
      await api.revokeInvitation(invitationId);
      setMessage("Invitation revoked.");
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "Could not revoke invitation.",
      );
    }
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>People</h1>
            <p>Manage members and invitations for this Home.</p>
          </div>
          {canInvite && <button onClick={() => setOpen(!open)}>+ Invite someone</button>}
        </div>

        {open && canInvite && (
          <section className="card invite-card">
            <h2>Invite someone you trust</h2>
            <form onSubmit={invite}>
              <label>
                Email
                <input name="email" type="email" required />
              </label>
              <label>
                Role
                <select name="role" defaultValue="adult_member">
                  <option value="adult_member">Adult member</option>
                  <option value="administrator">Administrator</option>
                  <option value="member">Member</option>
                  <option value="guest">Guest</option>
                </select>
              </label>
              <button>Send invitation</button>
            </form>
          </section>
        )}

        <FormStatus message={message} error={error} />

        {canInvite && (
          <section className="card details">
            <h2>Pending invitations</h2>
            {!invitations.length ? (
              <p className="hint">No pending invitations right now.</p>
            ) : (
              <div className="invitation-list">
                {invitations.map((invitation) => (
                  <article key={invitation.id}>
                    <div>
                      <strong>{invitation.email}</strong>
                      <small>
                        {invitation.role.replace("_", " ")} · Expires {expiration(invitation.expires_at)}
                      </small>
                    </div>
                    <div className="actions compact-actions">
                      <button
                        className="secondary"
                        onClick={() => resend(invitation.id)}
                        type="button"
                      >
                        Resend
                      </button>
                      <button onClick={() => revoke(invitation.id)} type="button">
                        Revoke
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        <section className="people-grid">
          {members.map((member) => (
            <article className="card person" key={member.user_id}>
              <i>{member.display_name[0]}</i>
              <div>
                <h2>{member.display_name}</h2>
                <p>{member.email}</p>
                <span>{member.role.replace("_", " ")}</span>
              </div>
            </article>
          ))}
          {!members.length && (
            <article className="card details">
              <h2>It is just you here at the moment</h2>
              <p className="hint">Invite someone you trust to join your Home.</p>
            </article>
          )}
        </section>
      </main>
    </AppShell>
  );
}
