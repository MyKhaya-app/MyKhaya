"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Bell, KeyRound, Send } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard, CcColumns } from "@/components/control-centre/section";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcConfirmDialog } from "@/components/control-centre/dialog";

type PushSettings = {
  enabled: boolean;
  subject: string | null;
  vapid_public_key: string | null;
  private_key_configured: boolean;
  updated_at: string | null;
  editable: boolean;
};

type PushState = {
  configured: boolean;
  managed_by: "environment" | "platform_admin" | "unconfigured";
  public_key: string | null;
  active_subscriptions: number;
  recent_failures: { id: string; notification_type: string; failed_at: string; safe_failure_message: string | null }[];
  push_settings: PushSettings;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function PushPage() {
  const [data, setData] = useState<PushState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [rotateOpen, setRotateOpen] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<PushState>("/push"));
    } catch (cause) {
      setError(safeError(cause, "Could not load push delivery state."));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    platformApi
      .get<{ email: string }>("/auth/me")
      .then((actor) => setRecipient(actor.email))
      .catch(() => {});
  }, []);

  // PUT /push/vapid-settings, POST /push/vapid-settings/generate-keys and
  // POST /push/test are all guarded server-side with require_recent_auth()
  // (apps/api/mykhaya/routers/platform.py) — a 403 transparently opens
  // PlatformReauthModal and retries the same submit once verified.
  const generateKeys = useCallback(
    (rotate: boolean, formData?: FormData) =>
      guarded(async () => {
        setRotateOpen(false);
        const reason = formData ? formData.get("audit_reason") : "Initial VAPID key pair generated.";
        setGenerating(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.post<{ message: string; public_key: string }>(
            "/push/vapid-settings/generate-keys",
            { rotate, reason, confirmed: true },
          );
          setMessage(result.message);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The VAPID key pair could not be generated."));
        } finally {
          setGenerating(false);
        }
      })(),
    [load, guarded],
  );

  // FormData is read synchronously from the event here, before guarded()
  // is entered — a reauth retry replays the wrapped callback after the
  // operator re-authenticates, by which point React has already detached
  // event.currentTarget from the original submit event, so reading the
  // form inside the guarded callback would crash on retry.
  const saveSettings = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setSaving(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.put<{ message: string }>("/push/vapid-settings", {
            enabled: form.get("enabled") === "on",
            subject: form.get("subject") || null,
            reason: form.get("reason"),
            confirmed: true,
          });
          setMessage(result.message);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The push settings could not be saved."));
        } finally {
          setSaving(false);
        }
      })();
    },
    [load, guarded],
  );

  const testPush = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setSending(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.post<{ results: { device_label: string | null; result: string }[] }>(
            "/push/test",
            { recipient: form.get("recipient"), reason: form.get("reason"), confirmed: true },
          );
          const accepted = result.results.filter((row) => row.result === "accepted").length;
          setMessage(`${accepted} of ${result.results.length} device(s) accepted the test push.`);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The test push could not be sent."));
        } finally {
          setSending(false);
        }
      })();
    },
    [load, guarded],
  );

  const settings = data?.push_settings;

  const failureColumns: CcTableColumn<PushState["recent_failures"][number]>[] = [
    { key: "type", header: "Type", render: (row) => titleCase(row.notification_type) },
    { key: "failed", header: "Failed", render: (row) => readableDate(row.failed_at) },
    { key: "detail", header: "Safe failure", render: (row) => row.safe_failure_message ?? "Unavailable" },
  ];

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Delivery operations"
          title="Push"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!data ? (
          <CcLoadingState label="Loading push delivery state…" />
        ) : (
          <>
            <CcColumns ratio="1-1">
              <CcCard
                title="Transport"
                icon={Bell}
                actions={<CcBadge tone={data.configured ? "success" : "neutral"}>{data.configured ? "Configured" : "Not configured"}</CcBadge>}
              >
                <CcMetadataGrid>
                  <CcMetadataItem label="Managed by">{titleCase(data.managed_by)}</CcMetadataItem>
                  <CcMetadataItem label="VAPID public key">
                    {data.public_key ? <code>{data.public_key}</code> : "Not generated"}
                  </CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
              <CcCard title="Delivery">
                <CcMetadataGrid>
                  <CcMetadataItem label="Active registered devices">{data.active_subscriptions}</CcMetadataItem>
                  <CcMetadataItem label="Recent failures">{data.recent_failures.length}</CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
            </CcColumns>

            <CcCard
              title="VAPID key pair"
              icon={KeyRound}
              description="Rotating replaces the key pair — every device currently registered for push will stop receiving notifications until it re-subscribes."
            >
              {!settings?.editable && (
                <CcNotice tone="warning">
                  Managed by the deployment environment (MYKHAYA_VAPID_PUBLIC_KEY). Keys cannot be
                  generated here — edit the server&rsquo;s .env and redeploy.
                </CcNotice>
              )}
              {settings?.editable && (
                <CcActionBar
                  actions={[
                    settings?.vapid_public_key
                      ? {
                          key: "rotate",
                          label: generating ? "Rotating…" : "Rotate keys",
                          variant: "caution",
                          disabled: generating,
                          onClick: () => setRotateOpen(true),
                        }
                      : {
                          key: "generate",
                          label: generating ? "Generating…" : "Generate VAPID keys",
                          variant: "primary",
                          disabled: generating,
                          onClick: () => void generateKeys(false),
                        },
                  ]}
                />
              )}
            </CcCard>

            <CcCard title="Push configuration">
              <form onSubmit={saveSettings}>
                <fieldset disabled={!settings?.editable}>
                  <CcField label="Enabled">
                    <input type="checkbox" name="enabled" defaultChecked={settings?.enabled} />
                  </CcField>
                  <CcField label="Contact address (mailto: or https://)">
                    <input name="subject" defaultValue={settings?.subject ?? ""} placeholder="mailto:ops@mykhaya.example" maxLength={320} />
                  </CcField>
                  <CcField label="Reason for change">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  <CcActionBar
                    actions={[
                      { key: "save", label: saving ? "Saving…" : "Save push settings", variant: "primary", type: "submit", disabled: saving },
                    ]}
                  />
                </fieldset>
              </form>
              {settings?.updated_at && <p className="cc-technical-value">Last updated {relativeTime(settings.updated_at)}.</p>}
            </CcCard>

            {data.configured && (
              <CcCard
                title="Send a test push"
                icon={Send}
                description="Sends to every active device registered to that household member. A successful result means the push service accepted the message, not that it was displayed on the device."
              >
                <form onSubmit={testPush}>
                  <CcField label="Recipient's email (must have a registered device)">
                    <input name="recipient" type="email" required value={recipient} onChange={(event) => setRecipient(event.target.value)} />
                  </CcField>
                  <CcField label="Reason for test">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  <CcActionBar
                    actions={[
                      { key: "send", label: sending ? "Sending…" : "Send test push", variant: "primary", type: "submit", disabled: sending },
                    ]}
                  />
                </form>
              </CcCard>
            )}

            <CcCard title="Recent delivery failures">
              <CcTable
                columns={failureColumns}
                rows={data.recent_failures}
                rowKey={(row) => row.id}
                emptyMessage="No recent push delivery failures."
                caption="Recent push delivery failures"
              />
            </CcCard>
          </>
        )}
      </CcPage>

      <CcConfirmDialog
        open={rotateOpen}
        onClose={() => setRotateOpen(false)}
        title="Rotate VAPID key pair"
        description="Rotating VAPID keys immediately invalidates every device currently registered for push. Everyone will need to re-enable notifications after this."
        confirmLabel="Rotate keys"
        variant="destructive"
        onConfirm={(formData) => generateKeys(true, formData)}
      />
      {modal}
    </PlatformShell>
  );
}
