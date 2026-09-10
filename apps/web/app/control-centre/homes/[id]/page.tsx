"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard, CcColumns } from "@/components/control-centre/section";
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
import {
  Archive,
  ArchiveRestore,
  Power,
  PowerOff,
  Shuffle,
  ToggleLeft,
  ToggleRight,
  Trash2,
} from "lucide-react";

type Lifecycle = "active" | "disabled" | "archived";

// PCC Polish Phase 1: the current optional Home modules only, exactly as
// the backend already filters them (home_admin_manageable, non-hidden,
// non-core — see routers.platform.home_detail) — Notifications, External
// sharing, Tasks and Plans never appear in this list at all, matching the
// Home Admin Module Management screen's own established exclusion. Reuses
// mykhaya.routers.features.module_state, the same platform/plan/Home
// resolver that screen and consumer navigation already share, rather than
// a second parallel computation.
type ModuleState = {
  id: string;
  name: string;
  platform_enabled: boolean;
  entitled: boolean;
  // null = no Home FeatureOverride row (inherits platform/plan); otherwise
  // the row's own enabled value — distinct from effective_enabled, which
  // also factors in platform/plan.
  home_override: boolean | null;
  effective_enabled: boolean;
  blocked_by: "platform" | "plan" | "home" | null;
  toggleable: boolean;
};

type HomeDetail = {
  id: string;
  name: string;
  active: boolean;
  lifecycle: Lifecycle;
  created_at: string;
  members: { user_id: string; display_name: string; email: string; role: string }[];
  pending_invitations: { id: string; email: string; role: string; expires_at: string }[];
  feature_overrides: { feature: string; enabled: boolean }[];
  modules: ModuleState[];
  notes: { id: string; body: string; created_at: string }[];
};

const safeError = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;

// Truthful per the agreed authority order (platform, then plan, then Home
// Admin enablement) — never implies a Home override can bypass platform OFF
// or a plan restriction. See ModuleState.blocked_by.
function effectiveStateLabel(module: ModuleState): { text: string; tone: "success" | "neutral" } {
  if (module.effective_enabled) return { text: "Enabled", tone: "success" };
  if (module.blocked_by === "platform") return { text: "Blocked by platform", tone: "neutral" };
  if (module.blocked_by === "plan") return { text: "Not included in plan", tone: "neutral" };
  return { text: "Disabled by Home", tone: "neutral" };
}

function homeOverrideLabel(module: ModuleState): string {
  if (module.home_override === null) return "Inherit";
  return module.home_override ? "Enabled" : "Disabled";
}

export default function PlatformHomeDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<HomeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [reactivateOpen, setReactivateOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [featureDialog, setFeatureDialog] = useState<
    { feature: string; name: string; enabled: boolean } | null
  >(null);
  const [moveMemberTarget, setMoveMemberTarget] = useState<HomeDetail["members"][number] | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBlockers, setDeleteBlockers] = useState<string[] | null>(null);
  const { guarded, modal } = useReauthGuard();

  async function load() {
    setLoading(true);
    try {
      const result = await platformApi.get<HomeDetail>(`/homes/${encodeURIComponent(id)}`);
      setData(result);
    } catch (cause) {
      setError(safeError(cause, "Unable to load this Home."));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, [id]);

  // suspend/reactivate and feature-flag updates all hit endpoints the
  // backend guards with require_recent_auth() (see
  // apps/api/mykhaya/routers/platform.py: home_state,
  // update_home_feature_flag) — `guarded` re-throws a 403 "recent
  // authentication required" so useReauthGuard can show
  // PlatformReauthModal and transparently retry the same action once the
  // operator re-authenticates. The GET load and note-adding below are not
  // recent-auth-gated server-side, so they are never wrapped.
  const stateAction = guarded(
    async (action: "suspend" | "reactivate" | "archive" | "restore", formData: FormData) => {
      setSuspendOpen(false);
      setReactivateOpen(false);
      setArchiveOpen(false);
      setRestoreOpen(false);
      setBusy(action);
      setError("");
      try {
        const result = await platformApi.post<{ message: string }>(
          `/homes/${encodeURIComponent(id)}/${action}`,
          { reason: formData.get("audit_reason"), confirmed: true },
        );
        setMessage(result.message);
        await load();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(safeError(cause, `Unable to ${action} this Home.`));
      } finally {
        setBusy("");
      }
    },
  );

  const setFeature = guarded(
    async (feature: string, name: string, enabled: boolean, formData: FormData) => {
      setFeatureDialog(null);
      setBusy(`feature:${feature}`);
      setError("");
      try {
        await platformApi.put(`/homes/${encodeURIComponent(id)}/feature-flags/${feature}`, {
          enabled,
          reason: formData.get("audit_reason"),
          confirmed: true,
        });
        setMessage(`${name} override updated.`);
        await load();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) throw cause;
        setError(safeError(cause, `Unable to update the ${name} override.`));
      } finally {
        setBusy("");
      }
    },
  );

  async function openDelete() {
    setDeleteBlockers(null);
    setDeleteOpen(true);
    try {
      const result = await platformApi.get<{ eligible: boolean; blockers: string[] }>(
        `/homes/${encodeURIComponent(id)}/permanent-delete/eligibility`,
      );
      setDeleteBlockers(result.blockers);
    } catch (cause) {
      setDeleteBlockers([safeError(cause, "Unable to check deletion eligibility.")]);
    }
  }

  // The backend independently revalidates every precondition on the
  // mutation itself (see routers.platform.permanent_delete_home) — the
  // eligibility preflight above is purely a UX convenience so operators see
  // blockers before typing a confirmation, not a substitute for that
  // server-side check.
  const runDelete = guarded(async (formData: FormData) => {
    setDeleteOpen(false);
    setBusy("permanent-delete");
    setError("");
    try {
      await platformApi.post<{ message: string }>(`/homes/${encodeURIComponent(id)}/permanent-delete`, {
        reason: formData.get("audit_reason"),
        confirmation_text: formData.get("confirmation_text"),
        confirmed: true,
      });
      router.push("/homes");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to permanently delete this Home."));
      setBusy("");
    }
  });

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await platformApi.post(`/homes/${encodeURIComponent(id)}/notes`, { body: form.get("note") });
      formElement.reset();
      setMessage("Administrative note added.");
      await load();
    } catch (cause) {
      setError(safeError(cause, "Unable to add this note."));
    }
  }

  const statusTone: CcBadgeTone =
    data?.lifecycle === "archived" ? "neutral" : data?.lifecycle === "active" ? "success" : "danger";
  const statusLabel =
    data?.lifecycle === "archived" ? "Archived" : data?.lifecycle === "active" ? "Active" : "Disabled";

  // Archived is a retired/hidden record — only Restore makes sense on it
  // (see Slice 3: "Do not offer nonsensical actions such as 'Reactivate'
  // and 'Restore' simultaneously").
  const actions: CcAction[] = !data
    ? []
    : data.lifecycle === "archived"
      ? [
          {
            key: "restore",
            label: "Restore Home",
            icon: ArchiveRestore,
            variant: "primary" as const,
            disabled: Boolean(busy),
            onClick: () => setRestoreOpen(true),
          },
        ]
      : data.lifecycle === "disabled"
        ? [
            {
              key: "reactivate",
              label: "Reactivate Home",
              icon: Power,
              variant: "primary" as const,
              disabled: Boolean(busy),
              onClick: () => setReactivateOpen(true),
            },
          ]
        : [];

  return (
    <PlatformShell>
      <CcPage>
        <p>
          <a href="/homes">&larr; Homes</a>
        </p>
        {loading ? (
          <CcLoadingState label="Loading Home…" />
        ) : !data ? (
          <CcErrorState>{error || "Home not found."}</CcErrorState>
        ) : (
          <>
            <CcPageHeader
              eyebrow="Home account"
              title={
                <>
                  {data.name} <CcBadge tone={statusTone}>{statusLabel}</CcBadge>
                </>
              }
              description="Home content is not available in this interface."
            />
            {message && <CcNotice tone="success">{message}</CcNotice>}
            {error && <CcNotice tone="error">{error}</CcNotice>}

            <CcColumns ratio="2-1">
              <CcSection title="Home details">
                <CcCard>
                  <CcMetadataGrid>
                    <CcMetadataItem label="Home ID">{data.id}</CcMetadataItem>
                    <CcMetadataItem label="Created">{new Date(data.created_at).toLocaleString()}</CcMetadataItem>
                  </CcMetadataGrid>
                </CcCard>
              </CcSection>

              <CcSection title="Status">
                <CcStatusCard
                  tone={statusTone}
                  status={statusLabel}
                  description="Home content is not available in this interface."
                />
              </CcSection>
            </CcColumns>

            <CcSection title="Memberships">
              <CcRecordList variant="grid" emptyMessage="No members yet.">
                {data.members.map((member) => (
                  <CcRecordCard
                    key={member.user_id}
                    title={member.display_name}
                    meta={[member.email, member.role.replaceAll("_", " ")]}
                    actions={
                      <button
                        type="button"
                        className="secondary cc-action"
                        disabled={Boolean(busy)}
                        onClick={() => setMoveMemberTarget(member)}
                      >
                        <Shuffle aria-hidden size={16} strokeWidth={2} />
                        <span>Move</span>
                      </button>
                    }
                  />
                ))}
              </CcRecordList>
            </CcSection>

            <CcSection title="Pending invitations">
              <CcRecordList variant="grid" emptyMessage="No pending invitations.">
                {data.pending_invitations.map((invitation) => (
                  <CcRecordCard
                    key={invitation.id}
                    title={invitation.email}
                    meta={[
                      invitation.role.replaceAll("_", " "),
                      `expires ${new Date(invitation.expires_at).toLocaleDateString()}`,
                    ]}
                  />
                ))}
              </CcRecordList>
            </CcSection>

            <CcSection
              title="Module availability"
              description="Why each module currently resolves the way it does for this Home — platform availability and plan entitlement always outrank the Home's own override (see docs/architecture/feature-flags.md)."
            >
              <CcRecordList variant="grid">
                {data.modules.map((module) => {
                  const effective = effectiveStateLabel(module);
                  // What toggling actually does: flips an explicit Home
                  // override away from whatever currently resolves "on" —
                  // the inherited/effective state when there's no override
                  // yet, or the override's own value when there is one.
                  // Never bypasses platform/plan: the button only ever
                  // writes the Home's own FeatureOverride row, exactly as
                  // before (PCC Polish Phase 1 — no new control).
                  const currentlyOn = module.home_override ?? module.effective_enabled;
                  // A Home override can never make a module available when
                  // platform or plan already blocks it (see
                  // mykhaya.features.is_feature_enabled) — the control is
                  // disabled in both cases so an operator can never attempt
                  // a meaningless override, matching this same truthful
                  // meta-line mechanism already used for Platform/Plan/Home
                  // above rather than a new visual treatment.
                  const controlDisabled =
                    module.blocked_by === "platform" || module.blocked_by === "plan";
                  const meta = [
                    `Platform: ${module.platform_enabled ? "Enabled" : "Disabled"}`,
                    `Plan: ${module.entitled ? "Included" : "Not included"}`,
                    `Home: ${homeOverrideLabel(module)}`,
                  ];
                  if (module.blocked_by === "platform") meta.push("Controlled by platform");
                  if (module.blocked_by === "plan") meta.push("Not included in this Home's plan");
                  return (
                    <CcRecordCard
                      key={module.id}
                      title={module.name}
                      meta={meta}
                      badge={`Effective: ${effective.text}`}
                      badgeTone={effective.tone}
                      actions={
                        module.toggleable && (
                          <button
                            type="button"
                            className="secondary cc-action"
                            disabled={Boolean(busy) || controlDisabled}
                            onClick={() =>
                              setFeatureDialog({
                                feature: module.id,
                                name: module.name,
                                enabled: !currentlyOn,
                              })
                            }
                          >
                            {currentlyOn ? (
                              <ToggleLeft aria-hidden size={16} strokeWidth={2} />
                            ) : (
                              <ToggleRight aria-hidden size={16} strokeWidth={2} />
                            )}
                            <span>{currentlyOn ? "Disable" : "Enable"}</span>
                          </button>
                        )
                      }
                    />
                  );
                })}
              </CcRecordList>
            </CcSection>

            <CcSection title="Administrative notes">
              <CcCard>
                <form onSubmit={addNote}>
                  <CcField label="New internal note">
                    <textarea name="note" minLength={2} maxLength={1000} required />
                  </CcField>
                  <div className="cc-action-bar">
                    <button className="cc-action cc-action-primary">Add administrative note</button>
                  </div>
                </form>
              </CcCard>
              <CcRecordList emptyMessage="No administrative notes yet.">
                {data.notes.map((note) => (
                  <CcRecordCard key={note.id} title={new Date(note.created_at).toLocaleString()}>
                    <p>{note.body}</p>
                  </CcRecordCard>
                ))}
              </CcRecordList>
            </CcSection>

            {data.lifecycle !== "active" && (
              <CcSection title="Actions">
                <CcActionBar actions={actions} />
              </CcSection>
            )}

            {data.lifecycle !== "archived" && (
              <CcDangerZone
                title="Suspend or archive Home"
                description="Suspending this Home blocks access for every member until it is reactivated. Archiving does the same but also retires the Home from normal operational views — restore it later to bring it back."
              >
                <CcActionBar
                  actions={[
                    ...(data.lifecycle === "active"
                      ? [
                          {
                            key: "suspend",
                            label: "Suspend Home",
                            icon: PowerOff,
                            variant: "destructive" as const,
                            disabled: Boolean(busy),
                            onClick: () => setSuspendOpen(true),
                          },
                        ]
                      : []),
                    {
                      key: "archive",
                      label: "Archive Home",
                      icon: Archive,
                      variant: "destructive",
                      disabled: Boolean(busy),
                      onClick: () => setArchiveOpen(true),
                    },
                  ]}
                />
              </CcDangerZone>
            )}

            {data.lifecycle === "archived" && (
              <CcDangerZone
                title="Permanently delete Home"
                description="This permanently removes this empty Home. This cannot be undone. Homes containing household history cannot be permanently deleted here."
              >
                <CcActionBar
                  actions={[
                    {
                      key: "permanent-delete",
                      label: "Permanently delete Home",
                      icon: Trash2,
                      variant: "destructive",
                      disabled: Boolean(busy),
                      onClick: () => void openDelete(),
                    },
                  ]}
                />
              </CcDangerZone>
            )}
          </>
        )}
      </CcPage>

      <CcConfirmDialog
        open={suspendOpen}
        onClose={() => setSuspendOpen(false)}
        title="Suspend Home"
        description="Suspend this Home? Every member will lose access until it is reactivated."
        confirmLabel="Suspend Home"
        variant="destructive"
        onConfirm={(formData) => stateAction("suspend", formData)}
      />

      <CcConfirmDialog
        open={reactivateOpen}
        onClose={() => setReactivateOpen(false)}
        title="Reactivate Home"
        description="Reactivate this Home and restore access for its members?"
        confirmLabel="Reactivate Home"
        onConfirm={(formData) => stateAction("reactivate", formData)}
      />

      <CcConfirmDialog
        open={archiveOpen}
        onClose={() => setArchiveOpen(false)}
        title="Archive Home"
        description="Archiving this Home removes it from normal operational views and prevents members using it. The Home and its data are retained and can be restored later."
        confirmLabel="Archive Home"
        variant="destructive"
        onConfirm={(formData) => stateAction("archive", formData)}
      />

      <CcConfirmDialog
        open={restoreOpen}
        onClose={() => setRestoreOpen(false)}
        title="Restore Home"
        description="Restore this Home to Active and allow members to use it again?"
        confirmLabel="Restore Home"
        onConfirm={(formData) => stateAction("restore", formData)}
      />

      <CcConfirmDialog
        open={featureDialog !== null}
        onClose={() => setFeatureDialog(null)}
        title={featureDialog ? `${featureDialog.enabled ? "Enable" : "Disable"} ${featureDialog.name}` : ""}
        description={
          featureDialog
            ? `${featureDialog.enabled ? "Enable" : "Disable"} ${featureDialog.name} for this Home? This only sets the Home's own override — it cannot make a module available if the platform or plan currently blocks it.`
            : ""
        }
        confirmLabel={featureDialog?.enabled ? "Enable" : "Disable"}
        onConfirm={(formData) => {
          if (featureDialog) {
            void setFeature(featureDialog.feature, featureDialog.name, featureDialog.enabled, formData);
          }
        }}
      />

      {data && (
        <CcConfirmDialog
          open={deleteOpen}
          onClose={() => setDeleteOpen(false)}
          title="Permanently delete Home"
          description="This permanently removes this empty Home. This cannot be undone. Homes containing household history cannot be permanently deleted here."
          confirmLabel="Permanently delete Home"
          variant="destructive"
          onConfirm={(formData) => {
            if (!deleteBlockers || deleteBlockers.length === 0) void runDelete(formData);
          }}
          extraFields={
            <>
              {deleteBlockers === null && <p>Checking eligibility…</p>}
              {deleteBlockers && deleteBlockers.length > 0 && (
                <CcNotice tone="error">This Home cannot be permanently deleted yet: {deleteBlockers.join(", ")}</CcNotice>
              )}
              <label>
                Type this Home&rsquo;s name to confirm ({data.name})
                <input name="confirmation_text" type="text" required autoComplete="off" />
              </label>
            </>
          }
        />
      )}

      {data && moveMemberTarget && (
        <MoveMemberDialog
          open
          onClose={() => setMoveMemberTarget(null)}
          userId={moveMemberTarget.user_id}
          userDisplayName={moveMemberTarget.display_name}
          userEmail={moveMemberTarget.email}
          sourceHomes={[
            {
              id: data.id,
              name: data.name,
              role: moveMemberTarget.role,
              memberCount: data.members.length,
              lifecycle: statusLabel,
            },
          ]}
          onMoved={(moveMessage) => {
            setMessage(moveMessage);
            setMoveMemberTarget(null);
            void load();
          }}
        />
      )}

      {modal}
    </PlatformShell>
  );
}
