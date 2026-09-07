"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FileText, Radio } from "lucide-react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcActionBar } from "@/components/control-centre/action-bar";

type Template = {
  template_type: string;
  module: string;
  channel: string;
  is_override: boolean;
  enabled: boolean;
  security_critical: boolean;
};

type Health = {
  overall: "healthy" | "degraded" | "unhealthy";
  smtp: { configured: boolean; status: string };
  push: { configured: boolean; status: string };
  failures_today: number;
  deliveries_today: number;
};

/** The PCC Notifications module's landing page — a summary derived entirely
 *  from data the existing registry/communications endpoints already
 *  provide (see GET /notification-templates and GET /communications/health)
 *  rather than any new statistics endpoint, so there's nothing here that
 *  could ever disagree with the Templates/Channels screens reading the
 *  same source. */
export default function NotificationsOverviewPage() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [templateRows, healthRow] = await Promise.all([
        platformApi.get<Template[]>("/notification-templates"),
        platformApi.get<Health>("/communications/health").catch(() => null),
      ]);
      setTemplates(templateRows);
      setHealth(healthRow);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const customised = templates?.filter((row) => row.is_override).length ?? 0;
  const usingDefaults = templates ? templates.length - customised : 0;
  const enabled = templates?.filter((row) => row.enabled).length ?? 0;
  const disabled = templates ? templates.length - enabled : 0;

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Notifications"
          title="Overview"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        <NotificationsSubNav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {!templates ? (
          <CcLoadingState label="Loading…" />
        ) : (
          <>
            <section>
              <h2>Templates</h2>
              <CcMetadataGrid>
                <CcMetadataItem label="Registered types">{templates.length}</CcMetadataItem>
                <CcMetadataItem label="Customised">{customised}</CcMetadataItem>
                <CcMetadataItem label="Using built-in default">{usingDefaults}</CcMetadataItem>
                <CcMetadataItem label="Enabled">{enabled}</CcMetadataItem>
                <CcMetadataItem label="Disabled">{disabled}</CcMetadataItem>
              </CcMetadataGrid>
            </section>

            {health && (
              <section>
                <h2>Channel health</h2>
                <CcMetadataGrid>
                  <CcMetadataItem label={`Email ${health.smtp.configured ? "configured" : "not configured"}`}>
                    <CcBadge tone={health.smtp.configured ? "success" : "neutral"}>
                      {health.smtp.configured ? "Configured" : "Not configured"}
                    </CcBadge>
                  </CcMetadataItem>
                  <CcMetadataItem label={`Push ${health.push.configured ? "configured" : "not configured"}`}>
                    <CcBadge tone={health.push.configured ? "success" : "neutral"}>
                      {health.push.configured ? "Configured" : "Not configured"}
                    </CcBadge>
                  </CcMetadataItem>
                  <CcMetadataItem label="Deliveries today">{health.deliveries_today}</CcMetadataItem>
                  <CcMetadataItem label="Failures today">{health.failures_today}</CcMetadataItem>
                </CcMetadataGrid>
                {health.failures_today > 0 && (
                  <CcNotice tone="error">
                    {health.failures_today} delivery failure{health.failures_today === 1 ? "" : "s"} today —{" "}
                    <Link href="/notifications/delivery-logs">view delivery logs</Link>.
                  </CcNotice>
                )}
              </section>
            )}

            <CcCard title="Shortcuts">
              <CcActionBar
                actions={[
                  { key: "templates", label: "Browse templates", icon: FileText, href: "/notifications/templates" },
                  { key: "test-centre", label: "Send a test notification", icon: Radio, href: "/notifications/test-centre" },
                  { key: "delivery-logs", label: "View delivery failures", href: "/notifications/delivery-logs" },
                ]}
              />
            </CcCard>
          </>
        )}
      </CcPage>
    </PlatformShell>
  );
}
