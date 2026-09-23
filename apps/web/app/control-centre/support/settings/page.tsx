"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";

type ModuleSummary = { key: string; enabled: boolean };
type PlatformSetting = { key: string; state: "configured" | "default" | "unset"; value: unknown };
type SupportSettings = { support_notification_email: string | null };

type State = {
  supportEnabled: boolean | null;
  serviceStatusConfigured: boolean | null;
  supportNotificationEmail: string | null | undefined; // undefined = not loaded yet
  error: string | null;
};

function useSupportSettingsSummary(): State {
  const [state, setState] = useState<State>({
    supportEnabled: null,
    serviceStatusConfigured: null,
    supportNotificationEmail: undefined,
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

  return state;
}

export default function SupportSettingsPage() {
  const { supportEnabled, serviceStatusConfigured, supportNotificationEmail, error } =
    useSupportSettingsSummary();

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
