"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
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
} from "lucide-react";

type Lifecycle = "active" | "disabled" | "archived";

type HomeDetail = {
  id: string;
  name: string;
  active: boolean;
  lifecycle: Lifecycle;
  created_at: string;
  members: { user_id: string; display_name: string; email: string; role: string }[];
  pending_invitations: { id: string; email: string; role: string; expires_at: string }[];
  feature_overrides: { feature: string; enabled: boolean }[];
  notes: { id: string; body: string; created_at: string }[];
};

const FEATURES = [
  "calendar",
  "tasks",
  "shopping",
  "meals",
  "plans",
  "wish_lists",
  "notifications",
  "external_sharing",
] as const;

const safeError = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;

const featureLabel = (feature: string) => feature.replaceAll("_", " ");

export default function PlatformHomeDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<HomeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [reactivateOpen, setReactivateOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [featureDialog, setFeatureDialog] = useState<{ feature: string; enabled: boolean } | null>(null);
  const [moveMemberTarget, setMoveMemberTarget] = useState<HomeDetail["members"][number] | null>(null);
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

  const setFeature = guarded(async (feature: string, enabled: boolean, formData: FormData) => {
    setFeatureDialog(null);
    setBusy(`feature:${feature}`);
    setError("");
    try {
      await platformApi.put(`/homes/${encodeURIComponent(id)}/feature-flags/${feature}`, {
        enabled,
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage(`${featureLabel(feature)} override updated.`);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, `Unable to update the ${featureLabel(feature)} override.`));
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
              <CcRecordList emptyMessage="No members yet.">
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
              <CcRecordList emptyMessage="No pending invitations.">
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

            <CcSection title="Feature availability">
              <CcRecordList>
                {FEATURES.map((feature) => {
                  const enabled = Boolean(data.feature_overrides.find((item) => item.feature === feature)?.enabled);
                  return (
                    <CcRecordCard
                      key={feature}
                      title={featureLabel(feature)}
                      badge={enabled ? "Enabled" : "Disabled"}
                      badgeTone={enabled ? "success" : "neutral"}
                      actions={
                        <button
                          type="button"
                          className="secondary cc-action"
                          disabled={Boolean(busy)}
                          onClick={() => setFeatureDialog({ feature, enabled: !enabled })}
                        >
                          {enabled ? (
                            <ToggleLeft aria-hidden size={16} strokeWidth={2} />
                          ) : (
                            <ToggleRight aria-hidden size={16} strokeWidth={2} />
                          )}
                          <span>{enabled ? "Disable" : "Enable"}</span>
                        </button>
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
        title={featureDialog ? `${featureDialog.enabled ? "Enable" : "Disable"} ${featureLabel(featureDialog.feature)}` : ""}
        description={
          featureDialog
            ? `${featureDialog.enabled ? "Enable" : "Disable"} ${featureLabel(featureDialog.feature)} for this Home?`
            : ""
        }
        confirmLabel={featureDialog?.enabled ? "Enable" : "Disable"}
        onConfirm={(formData) => {
          if (featureDialog) void setFeature(featureDialog.feature, featureDialog.enabled, formData);
        }}
      />

      {data && moveMemberTarget && (
        <MoveMemberDialog
          open
          onClose={() => setMoveMemberTarget(null)}
          userId={moveMemberTarget.user_id}
          userDisplayName={moveMemberTarget.display_name}
          userEmail={moveMemberTarget.email}
          sourceHomes={[{ id: data.id, name: data.name, role: moveMemberTarget.role }]}
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
