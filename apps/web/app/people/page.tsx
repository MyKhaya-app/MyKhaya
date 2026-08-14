"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { UserPlus } from "lucide-react";
import type {
  HouseholdRelationship,
  InvitationListItem,
  Member,
} from "@mykhaya/shared-types";
import type { ColourKey } from "@mykhaya/design-tokens";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

type FamilyFilter = "all" | "adults" | "children" | "extended";

function filterGroup(relationship: HouseholdRelationship): FamilyFilter {
  if (relationship === "child") return "children";
  if (relationship === "extended_family" || relationship === "friend")
    return "extended";
  return "adults";
}

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

// Mutually exclusive by construction — every action on this page (invite, resend,
// revoke, change relationship) reports into this single status, so a success banner
// from one attempt can never linger alongside a later error, or vice versa. Every
// action clears it to "idle" the moment it starts, before setting its own outcome.
type PageStatus =
  | { kind: "idle" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

export default function People() {
  const { activeHome, activeHomeId } = useActiveHome();
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<InvitationListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [relationship, setRelationship] =
    useState<HouseholdRelationship>("partner");
  const [status, setStatus] = useState<PageStatus>({ kind: "idle" });
  const [sending, setSending] = useState(false);
  const [filter, setFilter] = useState<FamilyFilter>("all");
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [colourEditing, setColourEditing] = useState<string | null>(null);
  const [colourBusy, setColourBusy] = useState(false);

  useEffect(() => {
    api.me().then((user) => setCurrentUserId(user.id));
  }, []);

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
    // The API already excludes accepted/revoked invitations and defensively
    // suppresses any invitation whose email already has an active membership
    // (see mykhaya.routers.invitations.list_invitations) — this is a second,
    // belt-and-braces layer on top of that, not the source of truth. A
    // pending invite must never render for an email that's already an active
    // member of this Home, whatever the server returned.
    const activeMemberEmails = new Set(
      memberRows.map((member) => member.email?.toLowerCase()).filter(Boolean),
    );
    setInvitations(
      invitationRows.filter(
        (invitation) =>
          !invitation.accepted_at &&
          !invitation.revoked_at &&
          !activeMemberEmails.has(invitation.email.toLowerCase()),
      ),
    );
  }

  useEffect(() => {
    load().catch((cause: Error) => setStatus({ kind: "error", message: cause.message }));
  }, [activeHomeId, canInvite]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || relationship === "child" || sending) return;
    // Captured now, before any `await` — React can null out event.currentTarget once
    // this handler yields (and setOpen(false) below unmounts the form on the next
    // render regardless), so touching event.currentTarget after the request was the
    // actual cause of the original bug: form.reset() threw on every successful
    // submit, landing in the catch block and showing an error right next to the
    // success message that had just been set.
    const form = event.currentTarget;
    setSending(true);
    setStatus({ kind: "idle" });
    const data = new FormData(form);
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
      // The email send itself happens asynchronously (worker + outbox, so a slow or
      // temporarily-down mail provider never blocks this request) — this only
      // confirms the invitation was created and the email queued, not that it has
      // landed in an inbox yet. See the "Pending invitations" list for delivery
      // status, and Resend if it doesn't arrive.
      setStatus({ kind: "success", message: "Invitation created — sending the email now." });
      setOpen(false);
      form.reset();
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "We could not send that invitation.",
      });
    } finally {
      setSending(false);
    }
  }

  async function changeRelationship(
    member: Member,
    next: HouseholdRelationship,
  ) {
    if (!activeHomeId || !canManage || next === "child") return;
    if (
      !window.confirm(
        `Change ${member.display_name} to ${relationshipLabels[next]}?`,
      )
    )
      return;
    setStatus({ kind: "idle" });
    try {
      await api.patch(`/groups/${activeHomeId}/members/${member.user_id}`, {
        relationship: next,
        permission_profile: null,
        permission_overrides: {},
        shared_resources:
          next === "extended_family" || next === "friend" ? [] : [],
        confirmed: true,
      });
      setStatus({ kind: "success", message: "Relationship and default permission profile updated." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "That relationship could not be changed.",
      });
    }
  }

  async function changeColour(member: Member, colour: ColourKey) {
    if (!activeHomeId || colourBusy) return;
    setColourBusy(true);
    setStatus({ kind: "idle" });
    try {
      await api.updateMemberColour(activeHomeId, member.user_id, colour);
      setColourEditing(null);
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "That colour could not be changed.",
      });
    } finally {
      setColourBusy(false);
    }
  }

  async function resend(invitationId: string) {
    setStatus({ kind: "idle" });
    try {
      await api.resendInvitation(invitationId);
      setStatus({ kind: "success", message: "Invitation re-queued — sending the email now." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not resend invitation.",
      });
    }
  }

  async function revoke(invitationId: string) {
    if (!window.confirm("Revoke this invitation?")) return;
    setStatus({ kind: "idle" });
    try {
      await api.revokeInvitation(invitationId);
      setStatus({ kind: "success", message: "Invitation revoked." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not revoke invitation.",
      });
    }
  }

  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>Family</h1>
            <p className="muted">The people that make {activeHome?.name ?? "your Home"}</p>
          </div>
          {canInvite && (
            <button type="button" onClick={() => setOpen((value) => !value)}>
              <UserPlus size={18} aria-hidden="true" />
              Add member
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
                  <button disabled={sending}>
                    {sending ? "Sending…" : "Send invitation"}
                  </button>
                </>
              )}
            </form>
          </section>
        )}

        <FormStatus
          message={status.kind === "success" ? status.message : undefined}
          error={status.kind === "error" ? status.message : undefined}
        />

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
          <h2 id="household-members-title" className="visually-hidden">
            People in this Home
          </h2>
          <div className="family-filters" role="group" aria-label="Filter family members">
            {(
              [
                ["all", "All"],
                ["adults", "Adults"],
                ["children", "Children"],
                ["extended", "Extended"],
              ] as [FamilyFilter, string][]
            ).map(([value, label]) => {
              const count =
                value === "all"
                  ? members.length
                  : members.filter((m) => filterGroup(m.relationship) === value).length;
              return (
                <button
                  key={value}
                  type="button"
                  className={filter === value ? "active" : "secondary"}
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label} <span>{count}</span>
                </button>
              );
            })}
          </div>
          <div className="family-list">
            {members
              .filter((member) => filter === "all" || filterGroup(member.relationship) === filter)
              .map((member) => (
                <article className="card family-member" key={member.user_id}>
                  <Avatar
                    id={member.user_id}
                    name={member.display_name}
                    colour={member.colour}
                    avatarVersion={member.avatar_version}
                    size="lg"
                  />
                  <div className="family-member-body">
                    <div className="family-member-name">
                      <strong>{member.display_name}</strong>
                      <span className="role-badge">
                        {relationshipLabels[member.relationship]}
                      </span>
                    </div>
                    {member.email && <p className="muted">{member.email}</p>}
                    {canManage && member.relationship !== "child" && (
                      <label className="family-member-relationship">
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
                      <Link className="tertiary" href="/khaya-control-centre/children">
                        Manage child privacy
                      </Link>
                    )}
                    {(member.user_id === currentUserId || canManage) && (
                      <>
                        <button
                          type="button"
                          className="tertiary family-member-colour-toggle"
                          onClick={() =>
                            setColourEditing((current) =>
                              current === member.user_id ? null : member.user_id,
                            )
                          }
                        >
                          Change colour
                        </button>
                        {colourEditing === member.user_id && (
                          <ColourSwatchPicker
                            value={member.colour}
                            onChange={(colour) => changeColour(member, colour)}
                            groupLabel={`${member.display_name}'s colour`}
                            disabled={colourBusy}
                          />
                        )}
                      </>
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
