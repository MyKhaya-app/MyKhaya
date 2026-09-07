"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Mail as MailIcon, Send } from "lucide-react";
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

type SmtpSettings = {
  enabled: boolean;
  host: string;
  port: number;
  connection_security: "none" | "starttls" | "tls";
  auth_enabled: boolean;
  username: string | null;
  password_configured: boolean;
  sender_name: string;
  sender_email: string;
  reply_to: string | null;
  timeout_seconds: number;
  updated_at: string | null;
  editable: boolean;
};

type MailState = {
  configured: boolean;
  transport: string | null;
  sender_identity: string | null;
  queue_depth: number;
  last_successful_delivery: string | null;
  recent_failures: { id: string; job_type: string; failed_at: string; safe_failure_message: string | null }[];
  managed_by: "environment" | "platform_admin" | "unconfigured";
  smtp_settings: SmtpSettings;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function MailPage() {
  const [data, setData] = useState<MailState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [clearPasswordOpen, setClearPasswordOpen] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<MailState>("/mail"));
    } catch (cause) {
      setError(safeError(cause, "Could not load email delivery state."));
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

  // PUT /mail/smtp-settings, POST /mail/smtp-settings/clear-password and
  // POST /mail/test are all guarded server-side with require_recent_auth()
  // (apps/api/mykhaya/routers/platform.py) — a 403 transparently opens
  // PlatformReauthModal and retries the same submit once verified.
  // FormData is read synchronously from the event here, before guarded()
  // is entered — a reauth retry replays the wrapped callback after the
  // operator re-authenticates, by which point React has already detached
  // event.currentTarget from the original submit event, so reading the
  // form inside the guarded callback would crash on retry.
  const testEmail = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setSending(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.post<{ message: string }>("/mail/test", {
            recipient: form.get("recipient"),
            reason: form.get("reason"),
            confirmed: true,
          });
          setMessage(result.message);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The test email could not be sent."));
        } finally {
          setSending(false);
        }
      })();
    },
    [load, guarded],
  );

  const saveSmtpSettings = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const connectionSecurity = (form.get("connection_security") as string | null) ?? "starttls";
      const authEnabled = form.get("auth_enabled") === "on";
      const password = (form.get("password") as string | null) ?? "";
      return guarded(async () => {
        setSaving(true);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.put<{ message: string }>("/mail/smtp-settings", {
            enabled: form.get("enabled") === "on",
            host: form.get("host"),
            port: Number(form.get("port")),
            connection_security: connectionSecurity,
            auth_enabled: authEnabled,
            username: authEnabled ? form.get("username") : null,
            password: password ? password : null,
            sender_name: form.get("sender_name"),
            sender_email: form.get("sender_email"),
            reply_to: form.get("reply_to") || null,
            timeout_seconds: Number(form.get("timeout_seconds")),
            reason: form.get("reason"),
            confirmed: true,
          });
          setMessage(result.message);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The SMTP settings could not be saved."));
        } finally {
          setSaving(false);
        }
      })();
    },
    [load, guarded],
  );

  const clearPassword = useCallback(
    (formData: FormData) =>
      guarded(async () => {
        const reason = formData.get("audit_reason");
        setClearPasswordOpen(false);
        setError("");
        setMessage("");
        try {
          const result = await platformApi.post<{ message: string }>("/mail/smtp-settings/clear-password", {
            reason,
            confirmed: true,
          });
          setMessage(result.message);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The stored password could not be cleared."));
        }
      })(),
    [load, guarded],
  );

  const settings = data?.smtp_settings;

  const failureColumns: CcTableColumn<MailState["recent_failures"][number]>[] = [
    { key: "type", header: "Type", render: (row) => titleCase(row.job_type) },
    { key: "failed", header: "Failed", render: (row) => readableDate(row.failed_at) },
    { key: "detail", header: "Safe failure", render: (row) => row.safe_failure_message ?? "Unavailable" },
  ];

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Delivery operations"
          title="Email"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!data ? (
          <CcLoadingState label="Loading email delivery state…" />
        ) : (
          <>
            <CcColumns ratio="1-1">
              <CcCard
                title="Transport"
                icon={MailIcon}
                actions={<CcBadge tone={data.configured ? "success" : "neutral"}>{data.configured ? "Configured" : "Not configured"}</CcBadge>}
              >
                <CcMetadataGrid>
                  <CcMetadataItem label="Transport type">{data.transport ?? "Not configured"}</CcMetadataItem>
                  {data.sender_identity && <CcMetadataItem label="Sender identity">{data.sender_identity}</CcMetadataItem>}
                  <CcMetadataItem label="Managed by">{titleCase(data.managed_by)}</CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
              <CcCard title="Delivery">
                <CcMetadataGrid>
                  <CcMetadataItem label="Queue depth">{data.queue_depth}</CcMetadataItem>
                  <CcMetadataItem label="Last successful delivery">
                    {data.last_successful_delivery ? relativeTime(data.last_successful_delivery) : "No successful delivery recorded"}
                  </CcMetadataItem>
                  <CcMetadataItem label="Recent failures">{data.recent_failures.length}</CcMetadataItem>
                </CcMetadataGrid>
              </CcCard>
            </CcColumns>

            <CcCard title="SMTP configuration">
              {!settings?.editable && (
                <CcNotice tone="warning">
                  Managed by the deployment environment (MYKHAYA_SMTP_HOST). These fields cannot be
                  changed here — edit the server&rsquo;s .env and redeploy.
                </CcNotice>
              )}
              <form onSubmit={saveSmtpSettings}>
                <fieldset disabled={!settings?.editable}>
                  <CcField label="Enabled">
                    <input type="checkbox" name="enabled" defaultChecked={settings?.enabled} />
                  </CcField>
                  <CcField label="Host">
                    <input name="host" defaultValue={settings?.host} maxLength={255} />
                  </CcField>
                  <CcField label="Port">
                    <input name="port" type="number" min={1} max={65535} defaultValue={settings?.port ?? 587} />
                  </CcField>
                  <CcField label="Connection security">
                    <select name="connection_security" defaultValue={settings?.connection_security ?? "starttls"}>
                      <option value="starttls">STARTTLS</option>
                      <option value="tls">Implicit TLS</option>
                      <option value="none">None (development only)</option>
                    </select>
                  </CcField>
                  <CcField label="Authentication enabled">
                    <input type="checkbox" name="auth_enabled" defaultChecked={settings?.auth_enabled} />
                  </CcField>
                  <CcField label="Username">
                    <input name="username" defaultValue={settings?.username ?? ""} maxLength={320} />
                  </CcField>
                  <CcField
                    label="Password"
                    help={settings?.password_configured ? "A password is currently stored." : undefined}
                  >
                    <input
                      name="password"
                      type="password"
                      autoComplete="new-password"
                      placeholder={settings?.password_configured ? "Leave blank to keep the stored password" : "Enter a password"}
                      maxLength={1000}
                    />
                  </CcField>
                  {settings?.password_configured && (
                    <CcActionBar
                      actions={[
                        {
                          key: "clear-password",
                          label: "Clear stored password",
                          onClick: () => setClearPasswordOpen(true),
                        },
                      ]}
                    />
                  )}
                  <CcField label="Sender name">
                    <input name="sender_name" defaultValue={settings?.sender_name ?? "MyKhaya"} maxLength={100} />
                  </CcField>
                  <CcField label="Sender email">
                    <input name="sender_email" type="email" defaultValue={settings?.sender_email} maxLength={320} />
                  </CcField>
                  <CcField label="Reply-to (optional)">
                    <input name="reply_to" type="email" defaultValue={settings?.reply_to ?? ""} maxLength={320} />
                  </CcField>
                  <CcField label="Connection timeout (seconds)">
                    <input name="timeout_seconds" type="number" min={1} max={60} defaultValue={settings?.timeout_seconds ?? 10} />
                  </CcField>
                  <CcField label="Reason for change">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  <CcActionBar
                    actions={[
                      { key: "save", label: saving ? "Saving…" : "Save SMTP settings", variant: "primary", type: "submit", disabled: saving },
                    ]}
                  />
                </fieldset>
              </form>
              {settings?.updated_at && <p className="cc-technical-value">Last updated {relativeTime(settings.updated_at)}.</p>}
            </CcCard>

            {data.configured && (
              <CcCard title="Send a test email" icon={Send} description="The recipient address is not written to the audit log; the action and recipient domain are audited. Defaults to your own address — a successful result means the SMTP server accepted the message, not that it reached the recipient's inbox.">
                <form onSubmit={testEmail}>
                  <CcField label="Recipient">
                    <input name="recipient" type="email" required value={recipient} onChange={(event) => setRecipient(event.target.value)} />
                  </CcField>
                  <CcField label="Reason for test">
                    <input name="reason" minLength={10} maxLength={500} required />
                  </CcField>
                  <CcActionBar
                    actions={[
                      { key: "send", label: sending ? "Sending…" : "Send test email", variant: "primary", type: "submit", disabled: sending },
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
                emptyMessage="No recent email delivery failures."
                caption="Recent email delivery failures"
              />
            </CcCard>
          </>
        )}
      </CcPage>

      <CcConfirmDialog
        open={clearPasswordOpen}
        onClose={() => setClearPasswordOpen(false)}
        title="Clear stored SMTP password"
        description="The stored SMTP password will be removed. Authentication will fail until a new password is saved."
        confirmLabel="Clear stored password"
        variant="destructive"
        onConfirm={clearPassword}
      />
      {modal}
    </PlatformShell>
  );
}
