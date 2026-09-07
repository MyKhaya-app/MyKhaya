"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Radio } from "lucide-react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

type ServiceStatus = { configured: boolean; status: string };

type Health = {
  overall: "healthy" | "degraded" | "unhealthy";
  smtp: ServiceStatus;
  push: ServiceStatus;
  deliveries_today: number;
  failures_today: number;
};

type ChannelRow = {
  key: string;
  channel: string;
  configured: boolean;
  detail: React.ReactNode;
};

/** Channel status only — this reads the same GET /communications/health
 *  endpoint as the existing /communications page rather than duplicating
 *  provider config lookups, and never renders secrets/keys/tokens. Actual
 *  SMTP/push provider configuration stays where it already lives (Email /
 *  Push pages) — this screen links out to those rather than re-implementing
 *  them. */
export default function NotificationChannelsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setHealth(await platformApi.get<Health>("/communications/health"));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rows: ChannelRow[] = health
    ? [
        {
          key: "email",
          channel: "Email",
          configured: health.smtp.configured,
          detail: (
            <>
              {health.smtp.status} — see <Link href="/mail">Email</Link>
            </>
          ),
        },
        {
          key: "push",
          channel: "Push",
          configured: health.push.configured,
          detail: (
            <>
              {health.push.status} — see <Link href="/push">Push</Link>
            </>
          ),
        },
        {
          key: "in_app",
          channel: "In-app",
          configured: true,
          detail: "Always available — delivered directly into the household app.",
        },
        {
          key: "briefing",
          channel: "Daily briefing",
          configured: true,
          detail: (
            <>
              Wording managed on the <Link href="/notifications/briefing">Daily Briefing</Link> screen; delivered via the channels above.
            </>
          ),
        },
      ]
    : [];

  const columns: CcTableColumn<ChannelRow>[] = [
    { key: "channel", header: "Channel", render: (row) => row.channel },
    {
      key: "status",
      header: "Status",
      render: (row) => <CcBadge tone={row.configured ? "success" : "neutral"}>{row.configured ? "Configured" : "Not configured"}</CcBadge>,
    },
    { key: "detail", header: "Configuration", render: (row) => row.detail },
  ];

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Notifications"
          title="Channels"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        <NotificationsSubNav />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {!health ? (
          <CcLoadingState label="Loading…" />
        ) : (
          <CcTable columns={columns} rows={rows} rowKey={(row) => row.key} caption="Channel status" />
        )}

        <CcCard title="Today" icon={Radio}>
          <CcMetadataGrid columns="fixed-2">
            <CcMetadataItem label="Deliveries today">{health?.deliveries_today ?? "—"}</CcMetadataItem>
            <CcMetadataItem label="Failures today">{health?.failures_today ?? "—"}</CcMetadataItem>
          </CcMetadataGrid>
          {health && health.failures_today > 0 && (
            <CcNotice tone="error">
              See <Link href="/notifications/delivery-logs">delivery logs</Link> for failure detail.
            </CcNotice>
          )}
        </CcCard>
      </CcPage>
    </PlatformShell>
  );
}
