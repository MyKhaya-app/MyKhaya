"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Camera, Copy, RefreshCw, Trash2, UserPlus } from "lucide-react";
import type {
  CalendarUsage,
  HomeJoinCode,
  HomeJoinRequestListItem,
  HouseholdRelationship,
  InvitationListItem,
  Member,
} from "@mykhaya/shared-types";
import type { ColourKey } from "@mykhaya/design-tokens";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { isImageFormatRejection, normalizeAvatarFile } from "@/components/avatar-upload";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { canAddMember, memberLimitMessage } from "@/components/member-entitlement-logic";
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
  adult: "Adult",
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
  // Same default access as Partner (see mykhaya.household_permissions
  // .default_profile) — Adult is for another genuine household member who
  // isn't the Home Admin's partner: an older child living at home, a
  // housemate, a sibling, another adult relative.
  adult:
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

// Canonical member-management destination, reached from More → "Members and
// roles" (see components/settings-page.tsx). Previously this same
// component lived at /people (the Family bottom-nav tab); that route is now
// a people-focused household overview instead (see app/people/page.tsx),
// with all administrative controls (invite, change relationship/colour,
// child privacy) moved here — the Family tab only links out to this page
// via "Manage family members", never duplicates it.
export default function ManageMembers() {
  const { activeHome, activeHomeId } = useActiveHome();
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<InvitationListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [livesInHome, setLivesInHome] = useState<boolean | null>(null);
  const [inviteMethod, setInviteMethod] = useState<"email" | "code">("email");
  const [relationship, setRelationship] =
    useState<HouseholdRelationship>("partner");
  const [joinCode, setJoinCode] = useState<HomeJoinCode | null>(null);
  const [joinCodeBusy, setJoinCodeBusy] = useState(false);
  const [joinCodeCopied, setJoinCodeCopied] = useState(false);
  const [joinRequests, setJoinRequests] = useState<HomeJoinRequestListItem[]>([]);
  const [joinRequestRelationship, setJoinRequestRelationship] = useState<
    Record<string, HouseholdRelationship>
  >({});
  const [joinRequestBusy, setJoinRequestBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<PageStatus>({ kind: "idle" });
  const [sending, setSending] = useState(false);
  const [filter, setFilter] = useState<FamilyFilter>("all");
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [colourEditing, setColourEditing] = useState<string | null>(null);
  const [colourBusy, setColourBusy] = useState(false);
  const [memberUsage, setMemberUsage] = useState<CalendarUsage | null>(null);
  const [externalInvitesEnabled, setExternalInvitesEnabled] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState<string | null>(null);

  useEffect(() => {
    api.me().then((user) => setCurrentUserId(user.id));
  }, []);

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => {
        setMemberUsage(billing.member_usage);
        setExternalInvitesEnabled(billing.external_invites_enabled);
      })
      .catch(() => {
        setMemberUsage(null);
        setExternalInvitesEnabled(false);
      });
  }, [activeHomeId]);

  const canInvite =
    activeHome?.capabilities.includes("members.invite") ?? false;
  const canManage =
    activeHome?.capabilities.includes("members.manage_relationships") ?? false;
  const canAssignHomeAdmin = activeHome?.relationship === "home_admin";
  // Fails closed while loading/unknown — "Add member" only ever appears once
  // the plan's actual member limit is confirmed, never optimistically.
  const canGrowMembership = memberUsage ? canAddMember(memberUsage) : false;
  const nonChildRelationships = useMemo(
    () =>
      [
        "home_admin",
        "partner",
        "adult",
        "extended_family",
        "friend",
      ] as HouseholdRelationship[],
    [],
  );

  async function load() {
    if (!activeHomeId) return;
    const [memberRows, invitationRows, joinRequestRows] = await Promise.all([
      api.members(activeHomeId),
      canInvite ? api.listInvitations(activeHomeId) : Promise.resolve([]),
      canInvite ? api.listHomeJoinRequests(activeHomeId) : Promise.resolve([]),
    ]);
    setMembers(memberRows);
    setJoinRequests(joinRequestRows);
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

  useEffect(() => {
    if (!activeHomeId || !canInvite || inviteMethod !== "code") return;
    api.getHomeJoinCode(activeHomeId).then(setJoinCode).catch(() => setJoinCode(null));
  }, [activeHomeId, canInvite, inviteMethod]);

  async function regenerateJoinCode() {
    if (!activeHomeId || joinCodeBusy) return;
    setJoinCodeBusy(true);
    setStatus({ kind: "idle" });
    try {
      const next = await api.regenerateHomeJoinCode(activeHomeId);
      setJoinCode(next);
      setJoinCodeCopied(false);
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not generate a join code.",
      });
    } finally {
      setJoinCodeBusy(false);
    }
  }

  async function copyJoinCode() {
    if (!joinCode?.code) return;
    try {
      await navigator.clipboard.writeText(joinCode.code);
      setJoinCodeCopied(true);
    } catch {
      // Clipboard access can fail silently (permissions, insecure context) —
      // the code is still shown on screen and selectable by hand either way.
    }
  }

  async function approveJoinRequest(request: HomeJoinRequestListItem) {
    if (!activeHomeId || joinRequestBusy) return;
    const nextRelationship = joinRequestRelationship[request.id] ?? "partner";
    setJoinRequestBusy(request.id);
    setStatus({ kind: "idle" });
    try {
      await api.approveHomeJoinRequest(activeHomeId, request.id, {
        relationship: nextRelationship,
        confirmed: true,
      });
      setStatus({
        kind: "success",
        message: `${request.display_name} is now a member of ${activeHome?.name ?? "this Home"}.`,
      });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not approve that request.",
      });
    } finally {
      setJoinRequestBusy(null);
    }
  }

  async function declineJoinRequest(request: HomeJoinRequestListItem) {
    if (!activeHomeId || joinRequestBusy) return;
    if (!window.confirm(`Decline ${request.display_name}'s request to join?`)) return;
    setJoinRequestBusy(request.id);
    setStatus({ kind: "idle" });
    try {
      await api.declineHomeJoinRequest(activeHomeId, request.id, { confirmed: true });
      setStatus({ kind: "success", message: "Request declined." });
      await load();
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Could not decline that request.",
      });
    } finally {
      setJoinRequestBusy(null);
    }
  }

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
      });
      // The email send itself happens asynchronously (worker + outbox, so a slow or
      // temporarily-down mail provider never blocks this request) — this only
      // confirms the invitation was created and the email queued, not that it has
      // landed in an inbox yet. See the "Pending invitations" list for delivery
      // status, and Resend if it doesn't arrive.
      setStatus({ kind: "success", message: "Invitation created — sending the email now." });
      setOpen(false);
      setLivesInHome(null);
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

  async function changeChildAvatar(member: Member, file: File) {
    if (!activeHomeId || avatarBusy) return;
    setAvatarBusy(member.user_id);
    setStatus({ kind: "idle" });
    try {
      const updated = await api.uploadMemberAvatar(
        activeHomeId,
        member.user_id,
        await normalizeAvatarFile(file),
      );
      setMembers((current) =>
        current.map((item) => (item.user_id === updated.user_id ? updated : item)),
      );
      setStatus({ kind: "success", message: `${member.display_name}'s photo was updated.` });
    } catch (cause) {
      setStatus({
        kind: "error",
        message:
          cause instanceof ApiError && isImageFormatRejection(cause)
            ? "Choose a JPEG, PNG or WebP photo."
            : cause instanceof ApiError
              ? cause.message
              : "That photo could not be updated.",
      });
    } finally {
      setAvatarBusy(null);
    }
  }

  async function removeChildAvatar(member: Member) {
    if (!activeHomeId || avatarBusy || !window.confirm(`Remove ${member.display_name}'s photo?`))
      return;
    setAvatarBusy(member.user_id);
    setStatus({ kind: "idle" });
    try {
      const updated = await api.removeMemberAvatar(activeHomeId, member.user_id);
      setMembers((current) =>
        current.map((item) => (item.user_id === updated.user_id ? updated : item)),
      );
      setStatus({ kind: "success", message: `${member.display_name}'s photo was removed.` });
    } catch (cause) {
      setStatus({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "That photo could not be removed.",
      });
    } finally {
      setAvatarBusy(null);
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
    <AppShellContent>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{activeHome?.name ?? "Home"}</p>
            <h1>Members and roles</h1>
            <p className="muted">Relationships, invitations and access for {activeHome?.name ?? "your Home"}</p>
          </div>
          {canInvite && canGrowMembership && (
            <button type="button" onClick={() => setOpen((value) => !value)}>
              <UserPlus size={18} aria-hidden="true" />
              Add member
            </button>
          )}
        </div>

        {canInvite && memberUsage && !canGrowMembership && (
          <FamilyUpsell
            title="Invite household members"
            description={
              memberLimitMessage(memberUsage) ??
              "Available with MyKhaya Family."
            }
          />
        )}

        {open && canInvite && canGrowMembership && (
          <section className="card invite-card">
            <div className="section-heading">
              <div>
                <h2>Add someone to this Home</h2>
                <p>
                  {livesInHome === null
                    ? "First, tell us how they connect to your household."
                    : "Choose the relationship first; advanced permissions remain separate."}
                </p>
              </div>
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  setOpen(false);
                  setLivesInHome(null);
                }}
              >
                Close
              </button>
            </div>

            {livesInHome === null && (
              <div className="lives-in-home-question">
                <p>Does this person live in your household?</p>
                <p className="muted">
                  Home members can participate across household features —
                  calendars, routines, lists and more. People outside the
                  household (grandparents, other relatives, friends, another
                  family) should be connected instead, with access only to
                  what you choose to share.
                </p>
                <div className="actions">
                  <button type="button" onClick={() => setLivesInHome(true)}>
                    Yes, they live here
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => setLivesInHome(false)}
                  >
                    No, they&rsquo;re outside the household
                  </button>
                </div>
              </div>
            )}

            {livesInHome === false && (
              <div className="child-flow-callout">
                <p>
                  Give them access to specific calendars instead — they&rsquo;ll
                  see only what you share, and they never become a member of
                  this Home.
                </p>
                {!externalInvitesEnabled && (
                  <p className="quiet-state">
                    Sharing a calendar outside the Home is available with
                    MyKhaya Family.
                  </p>
                )}
                <div className="actions">
                  <Link className="button" href="/calendar/calendars">
                    Share a calendar
                  </Link>
                  <button
                    className="tertiary"
                    type="button"
                    onClick={() => setLivesInHome(null)}
                  >
                    Back
                  </button>
                </div>
              </div>
            )}

            {livesInHome === true && (
              <>
                <div className="family-filters" role="group" aria-label="How to add this person">
                  <button
                    type="button"
                    className={inviteMethod === "email" ? "active" : "secondary"}
                    aria-pressed={inviteMethod === "email"}
                    onClick={() => setInviteMethod("email")}
                  >
                    Invite by email
                  </button>
                  <button
                    type="button"
                    className={inviteMethod === "code" ? "active" : "secondary"}
                    aria-pressed={inviteMethod === "code"}
                    onClick={() => setInviteMethod("code")}
                  >
                    Share join code
                  </button>
                </div>

                {inviteMethod === "email" && (
                  <form onSubmit={invite}>
                    <label>
                      Relationship
                      <select
                        value={relationship}
                        onChange={(event) =>
                          setRelationship(event.target.value as HouseholdRelationship)
                        }
                      >
                        {canAssignHomeAdmin && <option value="home_admin">Home Admin</option>}
                        <option value="partner">Partner</option>
                        <option value="adult">Adult</option>
                        <option value="child">Child</option>
                      </select>
                    </label>
                    <p className="relationship-help">
                      {
                        relationshipHelp[
                          relationship as Exclude<
                            HouseholdRelationship,
                            "review_required" | "extended_family" | "friend"
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
                    <button
                      className="tertiary"
                      type="button"
                      onClick={() => setLivesInHome(null)}
                    >
                      Back
                    </button>
                  </form>
                )}

                {inviteMethod === "code" && (
                  <div className="join-code-panel">
                    <p>
                      Give this code to someone you want to join {activeHome?.name ?? "your Home"}.
                      They can enter it when setting up MyKhaya or from their account later.
                    </p>
                    {joinCode?.code ? (
                      <>
                        <p className="join-code-value" aria-label="Home join code">
                          {joinCode.code}
                        </p>
                        <div className="actions compact-actions">
                          <button type="button" className="secondary" onClick={copyJoinCode}>
                            <Copy size={16} aria-hidden="true" />
                            {joinCodeCopied ? "Copied" : "Copy code"}
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            onClick={regenerateJoinCode}
                            disabled={joinCodeBusy}
                          >
                            <RefreshCw size={16} aria-hidden="true" />
                            {joinCodeBusy ? "Generating…" : "Generate new code"}
                          </button>
                        </div>
                      </>
                    ) : (
                      <button type="button" onClick={regenerateJoinCode} disabled={joinCodeBusy}>
                        {joinCodeBusy ? "Generating…" : "Generate a join code"}
                      </button>
                    )}
                    <p className="muted">
                      Anyone with this code can request to join this Home. A Home Admin must
                      approve them before they become a member.
                    </p>
                    <button
                      className="tertiary"
                      type="button"
                      onClick={() => setLivesInHome(null)}
                    >
                      Back
                    </button>
                  </div>
                )}
              </>
            )}
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

        {canInvite && joinRequests.length > 0 && (
          <section className="card details">
            <h2>Join requests ({joinRequests.length})</h2>
            <div className="invitation-list">
              {joinRequests.map((request) => (
                <article key={request.id}>
                  <div>
                    <strong>{request.display_name}</strong>
                    <small>
                      {request.email} · Requested using Home code
                    </small>
                  </div>
                  <div className="actions compact-actions">
                    <label className="visually-hidden" htmlFor={`join-request-relationship-${request.id}`}>
                      Relationship for {request.display_name}
                    </label>
                    <select
                      id={`join-request-relationship-${request.id}`}
                      value={joinRequestRelationship[request.id] ?? "partner"}
                      onChange={(event) =>
                        setJoinRequestRelationship((current) => ({
                          ...current,
                          [request.id]: event.target.value as HouseholdRelationship,
                        }))
                      }
                    >
                      {canAssignHomeAdmin && <option value="home_admin">Home Admin</option>}
                      <option value="partner">Partner</option>
                      <option value="adult">Adult</option>
                    </select>
                    <button
                      className="secondary"
                      type="button"
                      disabled={joinRequestBusy === request.id}
                      onClick={() => declineJoinRequest(request)}
                    >
                      Decline
                    </button>
                    <button
                      type="button"
                      disabled={joinRequestBusy === request.id}
                      onClick={() => approveJoinRequest(request)}
                    >
                      {joinRequestBusy === request.id ? "Approving…" : "Approve"}
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
                  <div className="family-member-avatar">
                    <Avatar
                      id={member.user_id}
                      name={member.display_name}
                      colour={member.colour}
                      avatarVersion={member.avatar_version}
                      size="lg"
                    />
                    {canManage && member.relationship === "child" && (
                      <>
                        <label className="family-member-avatar-action">
                          <Camera size={15} aria-hidden="true" />
                          <span className="visually-hidden">
                            {member.avatar_version ? "Replace" : "Add"} {member.display_name}'s photo
                          </span>
                          <input
                            type="file"
                            accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
                            className="visually-hidden"
                            disabled={avatarBusy === member.user_id}
                            onChange={(event) => {
                              const file = event.target.files?.[0];
                              event.currentTarget.value = "";
                              if (file) void changeChildAvatar(member, file);
                            }}
                          />
                        </label>
                        {member.avatar_version && (
                          <button
                            type="button"
                            className="family-member-avatar-remove"
                            aria-label={`Remove ${member.display_name}'s photo`}
                            disabled={avatarBusy === member.user_id}
                            onClick={() => void removeChildAvatar(member)}
                          >
                            <Trash2 size={13} aria-hidden="true" />
                          </button>
                        )}
                      </>
                    )}
                  </div>
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
                          {nonChildRelationships.map((value) => {
                            const isExternal = value === "extended_family" || value === "friend";
                            // Extended Family/Friend is retired as a Home-member
                            // relationship (see routers.groups.update_member) —
                            // a member who already holds it keeps their own
                            // current option selectable (transition-safe), but
                            // no one can be moved *into* it any more, on any
                            // plan. New external access goes through calendar
                            // sharing instead.
                            const locked = isExternal && member.relationship !== value;
                            return (
                              <option key={value} value={value} disabled={locked}>
                                {relationshipLabels[value]}
                                {locked ? " (retired)" : ""}
                              </option>
                            );
                          })}
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
    </AppShellContent>
  );
}
