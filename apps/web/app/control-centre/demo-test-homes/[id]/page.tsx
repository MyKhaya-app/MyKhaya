"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { KeyRound, Power, PowerOff, RefreshCw, Trash2 } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import type { ManagedDemoHome } from "@/components/platform-types";
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
import { CcDialog, CcDialogActions, CcConfirmDialog } from "@/components/control-centre/dialog";
import { validateManagedDemoPassword, MANAGED_DEMO_PASSWORD_MIN_LENGTH } from "../password-validation";

const formatDate = (value: string | null) => (value ? new Date(value).toLocaleString() : "No expiry");
const typeLabel = (value: ManagedDemoHome["fixture_type"]) =>
  value === "apple_review" ? "Apple Review" : value === "demo" ? "Family Demo" : "QA Test";
const safeError = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;

const statusTone: Record<ManagedDemoHome["status"], CcBadgeTone> = {
  enabled: "success",
  disabled: "neutral",
  expired: "danger",
};
const statusLabel: Record<ManagedDemoHome["status"], string> = {
  enabled: "Enabled",
  disabled: "Disabled",
  expired: "Expired",
};

export default function ManagedDemoHomeDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const [home, setHome] = useState<ManagedDemoHome | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [expiry, setExpiry] = useState("");
  const [enableOpen, setEnableOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [refreshOpen, setRefreshOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const { guarded, modal } = useReauthGuard();

  async function load() {
    setLoading(true);
    try {
      const rows = await platformApi.get<ManagedDemoHome[]>("/demo-test-homes");
      const found = rows.find((row) => row.id === id) ?? null;
      setHome(found);
      setExpiry(found?.expires_at ? new Date(found.expires_at).toISOString().slice(0, 16) : "");
      if (!found) setError("Managed Demo/Test Home not found.");
    } catch (error) {
      setError(safeError(error, "Unable to load this managed Demo/Test Home."));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, [id]);

  // Every mutation below hits an endpoint the backend guards with
  // require_recent_auth() (see apps/api/mykhaya/routers/platform.py: create,
  // enable/disable, password reset, refresh, expiry update and delete all
  // call it). `guarded` re-throws a 403 "recent authentication required" so
  // useReauthGuard can show PlatformReauthModal and transparently retry the
  // same action once the operator re-authenticates — plain GETs (`load`)
  // are never wrapped.
  const enable = guarded(async () => {
    setEnableOpen(false);
    setBusy("enable");
    setError("");
    try {
      await platformApi.post(`/demo-test-homes/${id}/enable`, {});
      setMessage("Demo/Test Home enabled.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to enable this Demo/Test Home."));
    } finally {
      setBusy("");
    }
  });

  const disable = guarded(async () => {
    setDisableOpen(false);
    setBusy("disable");
    setError("");
    try {
      await platformApi.post(`/demo-test-homes/${id}/disable`, {});
      setMessage("Demo/Test Home disabled.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to disable this Demo/Test Home."));
    } finally {
      setBusy("");
    }
  });

  const refresh = guarded(async (formData: FormData) => {
    setRefreshOpen(false);
    setBusy("refresh");
    setError("");
    try {
      await platformApi.post(`/demo-test-homes/${id}/refresh`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Demo/Test Home refreshed.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to refresh this Demo/Test Home."));
    } finally {
      setBusy("");
    }
  });

  const remove = guarded(async (formData: FormData) => {
    if (!home) return;
    setDeleteOpen(false);
    setBusy("delete");
    setError("");
    try {
      await platformApi.delete(`/demo-test-homes/${id}`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      router.push("/demo-test-homes");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to delete this managed Demo/Test Home."));
      setBusy("");
    }
  });

  const submitPasswordReset = guarded(async (newPassword: string) => {
    setBusy("password");
    setError("");
    try {
      await platformApi.post(`/demo-test-homes/${id}/password`, { password: newPassword });
      setPasswordOpen(false);
      setMessage("Password reset successfully.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to reset the managed account password."));
    } finally {
      setBusy("");
    }
  });

  async function resetPassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordError("");
    const data = new FormData(event.currentTarget);
    const newPassword = (data.get("new_password") as string | null) ?? "";
    const confirmPassword = (data.get("confirm_password") as string | null) ?? "";
    const validationError = validateManagedDemoPassword(newPassword, confirmPassword);
    if (validationError) {
      setPasswordError(validationError);
      return;
    }
    await submitPasswordReset(newPassword);
  }

  const submitExpiry = guarded(async () => {
    setBusy("expiry");
    setError("");
    try {
      await platformApi.patch(`/demo-test-homes/${id}/expiry`, {
        expires_at: expiry ? new Date(expiry).toISOString() : null,
      });
      setMessage("Expiry updated.");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(safeError(cause, "Unable to update expiry."));
    } finally {
      setBusy("");
    }
  });

  async function saveExpiry(event: React.FormEvent) {
    event.preventDefault();
    await submitExpiry();
  }

  const statusText = useMemo(
    () =>
      home?.status === "expired"
        ? `Expired${home.expires_at ? `: ${formatDate(home.expires_at)}` : ""}`
        : home
          ? statusLabel[home.status]
          : "",
    [home],
  );

  const actions: CcAction[] = home
    ? [
        {
          key: "enable",
          label: "Enable",
          icon: Power,
          variant: "primary",
          disabled: Boolean(busy) || home.status === "enabled",
          onClick: () => setEnableOpen(true),
        },
        ...(home.status === "enabled"
          ? [
              {
                key: "disable",
                label: "Disable",
                icon: PowerOff,
                variant: "caution" as const,
                disabled: Boolean(busy),
                onClick: () => setDisableOpen(true),
              },
            ]
          : []),
        {
          key: "refresh",
          label: "Refresh / Reset",
          icon: RefreshCw,
          variant: "caution",
          disabled: Boolean(busy),
          onClick: () => setRefreshOpen(true),
        },
        {
          key: "reset-password",
          label: "Reset Password",
          icon: KeyRound,
          variant: "secondary",
          disabled: Boolean(busy),
          onClick: () => {
            setPasswordError("");
            setPasswordOpen(true);
          },
        },
      ]
    : [];

  return (
    <PlatformShell>
      <CcPage>
        <p>
          <Link href="/demo-test-homes">← Demo &amp; Test Homes</Link>
        </p>
        {loading ? (
          <CcLoadingState label="Loading managed Home…" />
        ) : !home ? (
          <CcErrorState>{error}</CcErrorState>
        ) : (
          <>
            <CcPageHeader
              eyebrow="Operations"
              title={
                <>
                  {home.display_name} <CcBadge tone={statusTone[home.status]}>{statusLabel[home.status]}</CcBadge>
                </>
              }
              description={`Managed test home for ${typeLabel(home.fixture_type)}`}
            />
            {message && <CcNotice tone="success">{message}</CcNotice>}
            {error && <CcNotice tone="error">{error}</CcNotice>}

            <CcColumns ratio="2-1">
              <CcSection title="Home details">
                <CcCard>
                  <CcMetadataGrid>
                    <CcMetadataItem label="Template">{typeLabel(home.fixture_type)}</CcMetadataItem>
                    <CcMetadataItem label="Owner account">{home.account_email}</CcMetadataItem>
                    <CcMetadataItem label="Verification">
                      <CcBadge tone={home.email_verified ? "success" : "warning"}>
                        {home.email_verified ? "Verified" : "Unverified"}
                      </CcBadge>
                    </CcMetadataItem>
                    <CcMetadataItem label="Family access">
                      <CcBadge tone="info">{home.access === "family" ? "Family" : home.access}</CcBadge>
                    </CcMetadataItem>
                    <CcMetadataItem label="Template version">{home.template_version}</CcMetadataItem>
                    <CcMetadataItem label="Created">{formatDate(home.created_at)}</CcMetadataItem>
                    <CcMetadataItem label="Created by">{home.created_by ?? "CLI / system"}</CcMetadataItem>
                    <CcMetadataItem label="Last refreshed">
                      {home.refreshed_at ? formatDate(home.refreshed_at) : "Never"}
                    </CcMetadataItem>
                    <CcMetadataItem label="Expiry">{formatDate(home.expires_at)}</CcMetadataItem>
                    <CcMetadataItem label="Fixture key">{home.fixture_key}</CcMetadataItem>
                    {home.disabled_at && (
                      <CcMetadataItem label="Disabled at">{formatDate(home.disabled_at)}</CcMetadataItem>
                    )}
                  </CcMetadataGrid>
                </CcCard>
              </CcSection>

              <CcSection title="Status">
                <CcStatusCard
                  tone={statusTone[home.status]}
                  status={statusText}
                  description="This is a managed test/demo Home — its data is fixture-owned and may be reset by a Refresh / Reset."
                  items={[
                    { label: "Expiry", value: formatDate(home.expires_at) },
                    { label: "Access", value: home.access === "family" ? "Family" : home.access },
                  ]}
                />
              </CcSection>
            </CcColumns>

            <CcSection title="Lifecycle" description="Set, change or remove the expiry for this managed Home.">
              <CcCard>
                <form onSubmit={saveExpiry}>
                  <CcField label="Set or change expiry">
                    <input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
                  </CcField>
                  <div className="cc-action-bar">
                    <button className="cc-action cc-action-primary" disabled={busy === "expiry"}>
                      {busy === "expiry" ? "Saving…" : "Save expiry"}
                    </button>
                    <button
                      type="button"
                      className="cc-action cc-action-caution"
                      disabled={busy === "expiry" || !home.expires_at}
                      onClick={() => setExpiry("")}
                    >
                      Remove expiry
                    </button>
                  </div>
                </form>
              </CcCard>
            </CcSection>

            <CcSection title="Actions">
              <CcActionBar actions={actions} />
            </CcSection>

            <CcDangerZone
              title="Danger zone"
              description="Permanently removes this managed environment and its fixture-owned data."
            >
              <CcActionBar
                actions={[
                  {
                    key: "delete",
                    label: "Delete",
                    icon: Trash2,
                    variant: "destructive",
                    disabled: Boolean(busy),
                    onClick: () => setDeleteOpen(true),
                  },
                ]}
              />
            </CcDangerZone>
          </>
        )}
      </CcPage>

      {home && (
        <CcDialog open={enableOpen} onClose={() => setEnableOpen(false)} title="Enable Demo/Test Home">
          <div className="cc-dialog-scroll">
            <p>Enable {home.display_name}?</p>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setEnableOpen(false)}>
              Cancel
            </button>
            <button type="button" onClick={() => void enable()}>
              Enable
            </button>
          </CcDialogActions>
        </CcDialog>
      )}

      <CcConfirmDialog
        open={disableOpen}
        onClose={() => setDisableOpen(false)}
        title="Disable Demo/Test account"
        description="Disable this Demo/Test account? The Home and its data will be retained, but the managed account will no longer be able to sign in."
        confirmLabel="Disable"
        variant="destructive"
        onConfirm={disable}
      />

      <CcConfirmDialog
        open={refreshOpen}
        onClose={() => setRefreshOpen(false)}
        title="Refresh / Reset Demo/Test Home"
        description="Refreshing this Demo/Test Home will reset it to the template state and remove changes made during testing."
        confirmLabel="Refresh / Reset"
        variant="destructive"
        onConfirm={refresh}
      />

      <CcConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="Delete Demo/Test Home"
        description="Delete this Demo/Test Home? This permanently removes the managed environment and its fixture-owned data. This cannot be undone."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={remove}
      />

      {home && (
        <CcDialog
          open={passwordOpen}
          onClose={() => setPasswordOpen(false)}
          title={`Reset password for ${home.account_email}`}
        >
          <form className="cc-dialog-form" onSubmit={resetPassword}>
            <div className="cc-dialog-scroll">
              <CcField label="New password">
                <input
                  name="new_password"
                  type="password"
                  autoComplete="new-password"
                  minLength={MANAGED_DEMO_PASSWORD_MIN_LENGTH}
                />
              </CcField>
              <CcField label="Confirm password">
                <input
                  name="confirm_password"
                  type="password"
                  autoComplete="new-password"
                  minLength={MANAGED_DEMO_PASSWORD_MIN_LENGTH}
                />
              </CcField>
              {passwordError && <CcNotice tone="error">{passwordError}</CcNotice>}
            </div>
            <CcDialogActions>
              <button type="button" className="secondary" onClick={() => setPasswordOpen(false)}>
                Cancel
              </button>
              <button disabled={busy === "password"}>{busy === "password" ? "Resetting…" : "Reset password"}</button>
            </CcDialogActions>
          </form>
        </CcDialog>
      )}

      {modal}
    </PlatformShell>
  );
}
