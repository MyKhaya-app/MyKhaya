"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type {
  HouseholdRelationship,
  InvitationListItem,
  Member,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

const relationshipLabels: Record<HouseholdRelationship, string> = {
  home_admin: "Home Admin",
  partner: "Partner",
  child: "Child",
  extended_family: "Extended Family",
  friend: "Friend",
  review_required: "Needs review",
};

const relationshipHelp: Record<
  Exclude<HouseholdRelationship, "review_required">,
  string
> = {
  home_admin: "Full household administration, security and feature controls.",
  partner:
    "Shared calendars and household content, without automatic system-level control.",
  child: "A managed profile with restrictive defaults and explicit guardians.",
  extended_family: "Only resources explicitly shared with this person.",
  friend: "Minimal access to explicitly shared items only.",
};

function expiration(value: string) {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(
    new Date(value),
  );
}

export default function People() {
  const { activeHome, activeHomeId } = useActiveHome();
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<InvitationListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [relationship, setRelationship] =
    useState<HouseholdRelationship>("partner");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const canInvite =
    activeHome?.capabilities.includes("members.invite") ?? false;
  const canManage =
    activeHome?.capabilities.includes("members.manage_relationships") ?? false;
  const nonChildRelationships = useMemo(
    () =>
      [
        "home_admin",
        "partner",
        "extended_family",
        "friend",
      ] as HouseholdRelationship[],
    [],
  );

  async function load() {
    if (!activeHomeId) return;
    const [memberRows, invitationRows] = await Promise.all([
      api.members(activeHomeId),
      canInvite ? api.listInvitations(activeHomeId) : Promise.resolve([]),
    ]);
    setMembers(memberRows);
    setInvitations(invitationRows);
  }

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [activeHomeId, canInvite]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || relationship === "child" || busy) return;
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api.post("/invitations", {
        group_id: activeHomeId,
        email: data.get("email"),
        relationship,
        shared_resources:
          relationship === "extended_family" || relationship === "friend"
            ? data.getAll("shared_resources")
            : [],
      });
      setMessage("Invitation sent securely.");
      setError("");
      setOpen(false);
      event.currentTarget.reset();
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "We could not send that invitation.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function changeRelationship(
    member: Member,
    next: HouseholdRelationship,
  ) {
    if (!activeHomeId || !canManage || next === "child") return;
    const reason = window.prompt(
      "Reason for changing this household relationship:",
    );
    if (!reason || reason.trim().length < 10) {
      setError("Please provide an audit reason of at least 10 characters.");
      return;
    }
    if (
      !window.confirm(
        `Change ${member.display_name} to ${relationshipLabels[next]}?`,
      )
    )
      return;
    try {
      await api.patch(`/groups/${activeHomeId}/members/${member.user_id}`, {
        relationship: next,
        permission_profile: null,
        permission_overrides: {},
        shared_resources:
          next === "extended_family" || next === "friend" ? [] : [],
        reason: reason.trim(),
        confirmed: true,
      });
      setMessage("Relationship and default permission profile updated.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "That relationship could not be changed.",
      );
    }
  }

  async function resend(invitationId: string) {
    try {
      await api.resendInvitation(invitationId);
      setMessage("Invitation resent.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not resend invitation.",
      );
    }
  }

  async function revoke(invitationId: string) {
    if (!window.confirm("Revoke this invitation?")) return;
    try {
      await api.revokeInvitation(invitationId);
      setMessage("Invitation revoked.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Could not revoke invitation.",
      );
    }
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>Household</h1>
            <p>
              Relationships describe who someone is. Permission profiles control
              access.
            </p>
          </div>
          {canInvite && (
            <button type="button" onClick={() => setOpen((value) => !value)}>
              Invite someone
            </button>
          )}
        </div>

        {open && canInvite && (
          <section className="card invite-card">
            <div className="section-heading">
              <div>
                <h2>Add someone to this Home</h2>
                <p>
                  Choose the relationship first; advanced permissions remain
                  separate.
                </p>
              </div>
              <button
                className="secondary"
                type="button"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>
            <form onSubmit={invite}>
              <label>
                Relationship
                <select
                  value={relationship}
                  onChange={(event) =>
                    setRelationship(event.target.value as HouseholdRelationship)
                  }
                >
                  <option value="home_admin">Home Admin</option>
                  <option value="partner">Partner</option>
                  <option value="child">Child</option>
                  <option value="extended_family">Extended Family</option>
                  <option value="friend">Friend</option>
                </select>
              </label>
              <p className="relationship-help">
                {
                  relationshipHelp[
                    relationship as Exclude<
                      HouseholdRelationship,
                      "review_required"
                    >
                  ]
                }
              </p>
              {relationship === "child" ? (
                <div className="child-flow-callout">
                  <p>
                    Children use a managed profile with an age band, explicit
                    guardians and restrictive permissions. No adult invitation
                    will be sent.
                  </p>
                  <Link
                    className="button"
                    href="/khaya-control-centre/children"
                  >
                    Open child setup
                  </Link>
                </div>
              ) : (
                <>
                  <label>
                    Email
                    <input
                      name="email"
                      type="email"
                      autoComplete="email"
                      required
                    />
                  </label>
                  {(relationship === "extended_family" ||
                    relationship === "friend") && (
                    <fieldset>
                      <legend>Share initially</legend>
                      <label className="check-row">
                        <input
                          name="shared_resources"
                          type="checkbox"
                          value="calendar"
                        />
                        Calendar
                      </label>
                      <small>
                        No wider household access is granted automatically.
                      </small>
                    </fieldset>
                  )}
                  <details>
                    <summary>Advanced permissions</summary>
                    <p>
                      Custom capability overrides will be available here in a
                      later administration release. The selected relationship’s
                      safe default profile will be used now.
                    </p>
                  </details>
                  <button disabled={busy}>
                    {busy ? "Sending…" : "Send invitation"}
                  </button>
                </>
              )}
            </form>
          </section>
        )}

        <FormStatus message={message} error={error} />

        {canInvite && invitations.length > 0 && (
          <section className="card details">
            <h2>Pending invitations</h2>
            <div className="invitation-list">
              {invitations.map((invitation) => (
                <article key={invitation.id}>
                  <div>
                    <strong>{invitation.email}</strong>
                    <small>
                      {relationshipLabels[invitation.relationship]} · Expires{" "}
                      {expiration(invitation.expires_at)}
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
          </section>
        )}

        <section aria-labelledby="household-members-title">
          <h2 id="household-members-title">People in this Home</h2>
          <div className="people-grid">
            {members.map((member) => (
              <article
                className="card person relationship-card"
                key={member.user_id}
              >
                <i aria-hidden="true">{member.display_name[0]}</i>
                <div>
                  <h3>{member.display_name}</h3>
                  {member.email && <p>{member.email}</p>}
                  <strong>{relationshipLabels[member.relationship]}</strong>
                  <small>
                    {member.permission_profile.replaceAll("_", " ")}
                  </small>
                  {canManage && member.relationship !== "child" && (
                    <label>
                      Change relationship
                      <select
                        value={member.relationship}
                        onChange={(event) =>
                          changeRelationship(
                            member,
                            event.target.value as HouseholdRelationship,
                          )
                        }
                      >
                        {nonChildRelationships.map((value) => (
                          <option key={value} value={value}>
                            {relationshipLabels[value]}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {member.relationship === "child" && canManage && (
                    <Link href="/khaya-control-centre/children">
                      Manage child privacy
                    </Link>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
