"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Bell, KeyRound, Send } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard, CcColumns, CcSection } from "@/components/control-centre/section";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { CcToggle } from "@/components/control-centre/toggle";

type PushSettings = {
  enabled: boolean;
  subject: string | null;
  vapid_public_key: string | null;
  private_key_configured: boolean;
  updated_at: string | null;
  editable: boolean;
};

type NativeEnvironmentBreakdown = {
  production: number;
  sandbox: number;
  legacy: number;
};

type RecentFailure = {
  id: string;
  notification_type: string;
  failed_at: string;
  safe_failure_message: string | null;
  // Every field below exists so a single failed device-delivery attempt is
  // never mistaken for "the whole notification failed" or "the whole user
  // was unreachable" — see the PCC push audit's "Recent failures" finding.
  // `channel`/`platform`/`apns_environment` describe *which* delivery
  // failed; `recipient_user_id` and the two nullable id fields let an
  // operator confirm whether a sibling delivery for the same user/event
  // succeeded elsewhere, without this page needing to guess or aggregate.
  channel: "web" | "native";
  platform: "ios" | "android" | null;
  apns_environment: "sandbox" | "production" | null;
  recipient_user_id: string | null;
  native_push_device_id: string | null;
  push_subscription_id: string | null;
};

type PushState = {
  configured: boolean;
  managed_by: "environment" | "platform_admin" | "unconfigured";
  public_key: string | null;
  // `active_subscriptions` is kept for compatibility (identical value to
  // `active_web_subscriptions`) — this page now reads only the explicit
  // field. See docs/architecture/notification-engine.md and the PCC push
  // audit: this count has only ever measured Web Push subscriptions, never
  // native registrations, despite the historical "Active devices" label.
  active_subscriptions: number;
  active_web_subscriptions: number;
  active_native_registrations: number;
  users_with_active_native_push: number;
  native_registrations_by_environment: NativeEnvironmentBreakdown;
  recent_failures: RecentFailure[];
  push_settings: PushSettings;
};

type NativeDeviceRow = {
  id: string;
  user_id: string;
  display_name: string | null;
  email: string | null;
  platform: "ios" | "android";
  device_label: string | null;
  installation_id: string;
  apns_environment: "sandbox" | "production" | null;
  last_seen_at: string | null;
  disabled_at: string | null;
  disabled_reason: string | null;
};

type NativeDevicePage = {
  items: NativeDeviceRow[];
  page: number;
  page_size: number;
  total: number;
};

const NATIVE_DEVICES_PAGE_SIZE = 25;

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

function publicKeySummary(key: string | null): string {
  return key ? `Configured · ending ${key.slice(-8)}` : "Not generated";
}

type TestPushResult = {
  channel: "web" | "native";
  platform: "ios" | "android" | null;
  device_label: string | null;
  result: string;
};

// A human label for the transport an operator would otherwise have to infer
// from channel+platform — distinguishes iOS/APNs, Android/FCM and Web Push
// without a bigger per-device registry view (out of scope for this phase).
function providerLabel(row: { channel: "web" | "native"; platform: "ios" | "android" | null }): string {
  if (row.channel === "web") return "Web Push";
  if (row.platform === "android") return "Android · FCM";
  if (row.platform === "ios") return "iOS · APNs";
  return "Native";
}

// Same purpose as providerLabel above, applied to a Recent failures row —
// kept distinct so it can also fold in the APNs environment, which a test
// push result row doesn't carry.
function failureProviderLabel(row: RecentFailure): string {
  const base = providerLabel(row);
  if (row.channel === "native" && row.platform === "ios" && row.apns_environment) {
    return `${base} (${titleCase(row.apns_environment)})`;
  }
  return base;
}

export default function PushPage() {
  const [data, setData] = useState<PushState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [testResults, setTestResults] = useState<TestPushResult[]>([]);
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [rotateOpen, setRotateOpen] = useState(false);
  const [nativeDevices, setNativeDevices] = useState<NativeDevicePage | null>(null);
  const [nativeDevicesPage, setNativeDevicesPage] = useState(1);
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
  useEffect(() => {
    const params = new URLSearchParams({
      page: String(nativeDevicesPage),
      page_size: String(NATIVE_DEVICES_PAGE_SIZE),
    });
    platformApi
      .get<NativeDevicePage>(`/push/native-devices?${params.toString()}`)
      .then(setNativeDevices)
      .catch((cause) => setError(safeError(cause, "Could not load native push registrations.")));
  }, [nativeDevicesPage]);
  const nativeDevicesTotalPages = nativeDevices
    ? Math.max(1, Math.ceil(nativeDevices.total / NATIVE_DEVICES_PAGE_SIZE))
    : 1;

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
        setTestResults([]);
        try {
          const result = await platformApi.post<{ results: TestPushResult[] }>(
            "/push/test",
            { recipient: form.get("recipient"), reason: form.get("reason"), confirmed: true },
          );
          const accepted = result.results.filter(
            (row) => row.result === "accepted" || row.result === "queued",
          ).length;
          setMessage(`${accepted} of ${result.results.length} device(s) accepted the test push.`);
          setTestResults(result.results);
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

  const testResultColumns: CcTableColumn<TestPushResult>[] = [
    { key: "device", header: "Device", render: (row) => row.device_label ?? "Unlabelled" },
    { key: "provider", header: "Provider", render: (row) => providerLabel(row) },
    { key: "result", header: "Result", render: (row) => titleCase(row.result) },
  ];

  const failureColumns: CcTableColumn<RecentFailure>[] = [
    { key: "type", header: "Type", render: (row) => titleCase(row.notification_type) },
    { key: "provider", header: "Delivery", render: (row) => failureProviderLabel(row) },
    { key: "failed", header: "Failed", render: (row) => readableDate(row.failed_at) },
    { key: "detail", header: "Safe failure", render: (row) => row.safe_failure_message ?? "Unavailable" },
  ];

  const nativeDeviceColumns: CcTableColumn<NativeDeviceRow>[] = [
    { key: "user", header: "User", render: (row) => row.display_name ?? "Unknown" },
    { key: "email", header: "Email", render: (row) => row.email ?? "Unavailable" },
    { key: "label", header: "Device label", render: (row) => row.device_label ?? "Unlabelled" },
    { key: "platform", header: "Platform", render: (row) => (row.platform === "android" ? "Android" : "iOS") },
    { key: "installation", header: "Installation ID", render: (row) => row.installation_id },
    {
      key: "environment",
      header: "APNs environment",
      render: (row) =>
        row.platform === "android" ? "—" : titleCase(row.apns_environment ?? "legacy"),
    },
    {
      key: "last_seen",
      header: "Last seen",
      render: (row) => (row.last_seen_at ? readableDate(row.last_seen_at) : "Never"),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <CcBadge tone={row.disabled_at ? "neutral" : "success"}>
          {row.disabled_at ? "Disabled" : "Active"}
        </CcBadge>
      ),
    },
    {
      key: "disabled_reason",
      header: "Disabled reason",
      render: (row) => row.disabled_reason ?? "—",
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
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
            <CcStatusCard
              tone={data.configured ? "success" : "warning"}
              status={data.configured ? "Push transport ready" : "Push transport not configured"}
              description="Operational state is summarised here; service configuration and key actions are separated below."
              items={[
                { label: "Managed by", value: titleCase(data.managed_by) },
                { label: "Active web push subscriptions", value: data.active_web_subscriptions },
                { label: "Recent failures", value: data.recent_failures.length },
                { label: "Public key", value: publicKeySummary(data.public_key) },
              ]}
            />
            <CcColumns ratio="1-1">
              <CcCard
                title="Transport"
                icon={Bell}
                actions={<CcBadge tone={data.configured ? "success" : "neutral"}>{data.configured ? "Configured" : "Not configured"}</CcBadge>}
              >
                <CcMetadataGrid>
                  <CcMetadataItem label="Managed by">{titleCase(data.managed_by)}</CcMetadataItem>
                  <CcMetadataItem label="VAPID public key">
                    {publicKeySummary(data.public_key)}
                  </CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
              <CcCard title="Delivery">
                <CcMetadataGrid>
                  <CcMetadataItem label="Active web push subscriptions">
                    {data.active_web_subscriptions}
                  </CcMetadataItem>
                  <CcMetadataItem label="Recent failures">{data.recent_failures.length}</CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
            </CcColumns>

            <CcCard
              title="Native push (APNs / FCM)"
              description="Separate from Web Push above — iOS/Android app registrations, not browser subscriptions. See docs/architecture/notification-engine.md."
            >
              <CcMetadataGrid>
                <CcMetadataItem label="Active native registrations">
                  {data.active_native_registrations}
                </CcMetadataItem>
                <CcMetadataItem label="Users with native push">
                  {data.users_with_active_native_push}
                </CcMetadataItem>
                <CcMetadataItem label="Production APNs">
                  {data.native_registrations_by_environment.production}
                </CcMetadataItem>
                <CcMetadataItem label="Sandbox APNs">
                  {data.native_registrations_by_environment.sandbox}
                </CcMetadataItem>
                <CcMetadataItem label="Legacy registrations">
                  {data.native_registrations_by_environment.legacy}
                </CcMetadataItem>
              </CcMetadataGrid>
            </CcCard>

            <CcSection title="Credentials and high-impact actions" description="Public key status is summarised; private material is never displayed. Rotation invalidates current device registrations.">
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
            </CcSection>

            <CcSection title="Push configuration" description="Service settings and the contact address used by the push provider.">
            <div className="cc-config-panel">
              <form onSubmit={saveSettings}>
                <fieldset disabled={!settings?.editable}>
                  <CcToggle label="Push delivery enabled" name="enabled" defaultChecked={settings?.enabled} disabled={!settings?.editable} />
                  <div className="cc-form-grid">
                  <CcField label="Contact address (mailto: or https://)">
                    <input name="subject" defaultValue={settings?.subject ?? ""} placeholder="mailto:ops@mykhaya.example" maxLength={320} />
                  </CcField>
                  <CcField label="Reason for change">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  </div>
                  <CcActionBar
                    actions={[
                      { key: "save", label: saving ? "Saving…" : "Save push settings", variant: "primary", type: "submit", disabled: saving },
                    ]}
                  />
                </fieldset>
              </form>
              {settings?.updated_at && <p className="cc-technical-value">Last updated {relativeTime(settings.updated_at)}.</p>}
            </div>
            </CcSection>

            {data.configured && (
              <CcSection title="Delivery testing" description="Test tools are separated from service configuration and send only to the selected registered recipient.">
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
                {testResults.length > 0 && (
                  <CcTable
                    columns={testResultColumns}
                    rows={testResults}
                    rowKey={(row) => `${row.channel}-${row.device_label ?? "unlabelled"}-${row.result}`}
                    emptyMessage="No devices to show."
                    caption="Test push results by device"
                  />
                )}
              </CcCard>
              </CcSection>
            )}

            <CcSection title="Delivery history" description="Recent failures with safe, non-secret error details.">
            <CcCard
              title="Recent delivery failures"
              description="Each row is one device's delivery attempt, not a whole notification or a whole user — a device shown here can fail while another device (or channel) for the same person and the same notification succeeds."
            >
              <CcTable
                columns={failureColumns}
                rows={data.recent_failures}
                rowKey={(row) => row.id}
                emptyMessage="No recent push delivery failures."
                caption="Recent push delivery failures"
              />
            </CcCard>
            </CcSection>

            <CcSection title="Native registrations" description="Read-only — iOS/Android app registrations across every user, including disabled ones. Never shows the raw device token.">
            <CcCard title="Native push devices">
              <CcTable
                columns={nativeDeviceColumns}
                rows={nativeDevices?.items ?? null}
                rowKey={(row) => row.id}
                emptyMessage="No native push registrations."
                caption="Native push device registrations"
              />
              {nativeDevices && nativeDevices.items.length > 0 && (
                <div className="platform-modal-actions">
                  <button
                    type="button"
                    className="secondary"
                    disabled={nativeDevicesPage <= 1}
                    onClick={() => setNativeDevicesPage((current) => Math.max(1, current - 1))}
                  >
                    Previous
                  </button>
                  <span>
                    Page {nativeDevices.page} of {nativeDevicesTotalPages} ({nativeDevices.total} devices)
                  </span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nativeDevicesPage >= nativeDevicesTotalPages}
                    onClick={() =>
                      setNativeDevicesPage((current) => Math.min(nativeDevicesTotalPages, current + 1))
                    }
                  >
                    Next
                  </button>
                </div>
              )}
            </CcCard>
            </CcSection>
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
