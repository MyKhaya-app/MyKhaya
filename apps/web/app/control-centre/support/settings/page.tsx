"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { useReauthGuard } from "@/components/platform-reauth-modal";

type ModuleSummary = { key: string; enabled: boolean };
type PlatformSetting = { key: string; state: "configured" | "default" | "unset"; value: unknown };
type NewTicketNotifications = {
  configured: boolean;
  enabled: boolean;
  roles: string[];
  include_support_inbox: boolean;
  recipient_count: number;
  can_manage: boolean;
};
type SupportSettings = {
  support_notification_email: string | null;
  new_ticket_notifications: NewTicketNotifications;
};

// The existing PCC roles; recipients are their active members, resolved
// when each ticket is created.
const PCC_ROLES: [string, string][] = [
  ["platform_owner", "Owners"],
  ["platform_administrator", "Administrators"],
  ["support_operator", "Support operators"],
  ["security_operator", "Security operators"],
  ["read_only_operator", "Read-only operators"],
];

type State = {
  supportEnabled: boolean | null;
  serviceStatusConfigured: boolean | null;
  supportNotificationEmail: string | null | undefined; // undefined = not loaded yet
  newTicket: NewTicketNotifications | null;
  error: string | null;
};

function useSupportSettingsSummary() {
  const [state, setState] = useState<State>({
    supportEnabled: null,
    serviceStatusConfigured: null,
    supportNotificationEmail: undefined,
    newTicket: null,
    error: null,
  });

  useEffect(() => {
    Promise.all([
      platformApi.get<ModuleSummary[]>("/modules"),
      platformApi.get<{ settings: PlatformSetting[] }>("/settings"),
      platformApi.get<SupportSettings>("/support/settings"),
    ])
      .then(([modules, settings, supportSettings]) => {
        const supportModule = modules.find((module) => module.key === "support");
        const statusSetting = settings.settings.find((setting) => setting.key === "service_status_url");
        setState({
          supportEnabled: supportModule?.enabled ?? false,
          serviceStatusConfigured: statusSetting ? statusSetting.state !== "unset" : false,
          supportNotificationEmail: supportSettings.support_notification_email,
          newTicket: supportSettings.new_ticket_notifications ?? null,
          error: null,
        });
      })
      .catch((cause) =>
        setState((previous) => ({
          ...previous,
          error:
            cause instanceof ApiError ? cause.message : "Could not load Support settings.",
        })),
      );
  }, []);

  return [state, setState] as const;
}

function NewTicketNotificationsForm({
  value,
  inbox,
  onSaved,
}: {
  value: NewTicketNotifications;
  inbox: string | null;
  onSaved: (next: NewTicketNotifications) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const { guarded, modal } = useReauthGuard();

  // Saving requires recent authentication; `guarded` shows the re-auth
  // prompt on that 403 and retries the save.
  const save = guarded(async (form: FormData) => {
    setSaving(true);
    setError("");
    setSaved("");
    try {
      const next = await platformApi.put<NewTicketNotifications>(
        "/support/settings/new-ticket-notifications",
        {
          enabled: form.get("enabled") === "on",
          roles: form.getAll("roles"),
          include_support_inbox: form.get("include_support_inbox") === "on",
          reason: form.get("reason"),
          confirmed: true,
        },
      );
      onSaved(next);
      setSaved("New ticket notification settings saved.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not save these settings.");
    } finally {
      setSaving(false);
    }
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void save(new FormData(event.currentTarget));
  }

  const inboxLabel = inbox ? " (" + inbox + ")" : " (not configured in this environment)";
  return (
    <form className="cc-support-notify-form" onSubmit={submit}>
      {saved && <CcNotice tone="success">{saved}</CcNotice>}
      {error && <CcNotice tone="error">{error}</CcNotice>}
      <label className="cc-support-notify-check">
        <input type="checkbox" name="enabled" defaultChecked={value.enabled} /> Email the team when a new ticket is
        created
      </label>
      <fieldset>
        <legend>Send to these PCC roles</legend>
        <div className="cc-support-notify-roles">
          {PCC_ROLES.map(([role, label]) => (
            <label key={role} className="cc-support-notify-check">
              <input type="checkbox" name="roles" value={role} defaultChecked={value.roles.includes(role)} /> {label}
            </label>
          ))}
        </div>
        <small>
          Every active member of a selected role with an email address gets one email, even if they match more than
          one selection.
        </small>
      </fieldset>
      <label className="cc-support-notify-check">
        <input type="checkbox" name="include_support_inbox" defaultChecked={value.include_support_inbox} /> Also send
        to the support inbox{inboxLabel}
      </label>
      <CcField label="Reason for this change" help="Recorded in the PCC audit log.">
        <input name="reason" type="text" required minLength={10} maxLength={500} />
      </CcField>
      <div>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save notification settings"}
        </button>
      </div>
      {modal}
    </form>
  );
}

function rolesSummary(roles: string[]): string {
  const labels = PCC_ROLES.filter(([role]) => roles.includes(role)).map(([, label]) => label);
  return labels.length ? labels.join(", ") : "No roles selected";
}

export default function SupportSettingsPage() {
  const [state, setState] = useSupportSettingsSummary();
  const { supportEnabled, serviceStatusConfigured, supportNotificationEmail, newTicket, error } = state;

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Support"
          title="Support settings"
          description="Current configuration for the Support ticket system."
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}

        <CcSection title="Support availability">
          <CcCard>
            <CcMetadataGrid dense>
              <CcMetadataItem label="Support availability">
                {supportEnabled === null ? (
                  "Loading…"
                ) : (
                  <CcBadge tone={supportEnabled ? "success" : "neutral"}>
                    {supportEnabled ? "Enabled" : "Disabled"}
                  </CcBadge>
                )}
              </CcMetadataItem>
            </CcMetadataGrid>
            <p className="cc-page-meta">
              Managed under <Link href="/modules">Platform Modules</Link>. This page only
              reflects that setting — it is not a second toggle.
            </p>
          </CcCard>
        </CcSection>

        <CcSection title="Support notification email">
          <CcCard>
            <CcMetadataGrid dense>
              <CcMetadataItem label="Support notification email">
                {supportNotificationEmail === undefined ? (
                  "Loading…"
                ) : (
                  <CcBadge tone={supportNotificationEmail ? "success" : "neutral"}>
                    {supportNotificationEmail ? "Configured" : "Not configured"}
                  </CcBadge>
                )}
              </CcMetadataItem>
              {supportNotificationEmail && (
                <CcMetadataItem label="Destination">{supportNotificationEmail}</CcMetadataItem>
              )}
            </CcMetadataGrid>
            <p className="cc-page-meta">
              Set via the MYKHAYA_SUPPORT_NOTIFICATION_EMAIL deployment environment variable —
              not editable here, since it is not a runtime-editable Platform Setting.
            </p>
          </CcCard>
        </CcSection>

        <CcSection title="New ticket email notifications">
          <CcCard>
            {newTicket === null ? (
              supportNotificationEmail === undefined && !error ? "Loading…" : "Unavailable."
            ) : (
              <>
                <CcMetadataGrid dense>
                  <CcMetadataItem label="Status">
                    <CcBadge tone={!newTicket.configured ? "neutral" : newTicket.enabled ? "success" : "warning"}>
                      {!newTicket.configured ? "Not configured" : newTicket.enabled ? "On" : "Off"}
                    </CcBadge>
                  </CcMetadataItem>
                  {newTicket.configured && (
                    <CcMetadataItem label="Recipient roles">{rolesSummary(newTicket.roles)}</CcMetadataItem>
                  )}
                  {newTicket.configured && newTicket.enabled && (
                    <CcMetadataItem label="Recipients now">
                      {newTicket.recipient_count} {newTicket.recipient_count === 1 ? "person" : "people"}
                    </CcMetadataItem>
                  )}
                </CcMetadataGrid>
                <p className="cc-page-meta">
                  {newTicket.configured
                    ? "Recipients get the ticket reference, subject, priority, submission time and a PCC link. Descriptions, attachments and diagnostics are never included."
                    : "Until this is saved, new tickets are emailed only to the support inbox above, as before."}
                </p>
                {newTicket.can_manage ? (
                  <NewTicketNotificationsForm
                    value={newTicket}
                    inbox={supportNotificationEmail ?? null}
                    onSaved={(next) => setState((previous: State) => ({ ...previous, newTicket: next }))}
                  />
                ) : (
                  <p className="cc-page-meta">Only Platform Owners and Administrators can change these settings.</p>
                )}
              </>
            )}
          </CcCard>
        </CcSection>

        <CcSection title="Service Status">
          <CcCard>
            <CcMetadataGrid dense>
              <CcMetadataItem label="Service Status">
                {serviceStatusConfigured === null ? (
                  "Loading…"
                ) : (
                  <CcBadge tone={serviceStatusConfigured ? "success" : "neutral"}>
                    {serviceStatusConfigured ? "Configured" : "Not configured"}
                  </CcBadge>
                )}
              </CcMetadataItem>
            </CcMetadataGrid>
            <p className="cc-page-meta">
              Managed under <Link href="/settings">Platform Settings</Link>.
            </p>
          </CcCard>
        </CcSection>

        <CcSection title="Knowledge Base">
          <CcCard>
            <CcBadge tone="neutral">Coming soon</CcBadge>
          </CcCard>
        </CcSection>

        <CcSection title="What consumer Support provides">
          <CcCard>
            <ul className="cc-support-behaviour-list">
              <li>Report a bug</li>
              <li>Contact Support</li>
              <li>Diagnostics</li>
              <li>My support requests</li>
              <li>Email updates</li>
            </ul>
          </CcCard>
        </CcSection>
      </CcPage>
    </PlatformShell>
  );
}
