"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Clock3, Mail as MailIcon, Server, Timer } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcBadge, toneFromStateClass, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";

type ServiceStatus = {
  status: "running" | "stale" | "unavailable";
  last_heartbeat: string | null;
  detail: string;
};

type TransportStatus = {
  configured: boolean;
  status: "connected" | "not_configured";
};

type Health = {
  overall: "healthy" | "degraded" | "unhealthy";
  worker: ServiceStatus;
  scheduler: ServiceStatus;
  smtp: TransportStatus;
  push: TransportStatus;
  queue_depth: number;
  queue_status: "healthy" | "warning";
  queue_reason: string | null;
  average_latency_seconds: number | null;
  deliveries_today: number;
  failures_today: number;
  retries_today: number;
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

function overallTone(overall: Health["overall"]): CcBadgeTone {
  return toneFromStateClass(`state-${overall}`);
}

function serviceTone(status: ServiceStatus["status"]): CcBadgeTone {
  return toneFromStateClass(`state-${status === "running" ? "healthy" : status}`);
}

export default function CommunicationsHealthPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setHealth(await platformApi.get<Health>("/communications/health"));
    } catch (cause) {
      setError(safeError(cause, "Could not load communications health."));
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), 30_000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Communications"
          title="Health"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {!health ? (
          <CcLoadingState label="Loading communications health…" />
        ) : (
          <>
            <CcStatusCard tone={overallTone(health.overall)} status={titleCase(health.overall)} />

            <CcCard
              title="Worker"
              icon={Activity}
              actions={<CcBadge tone={serviceTone(health.worker.status)}>{titleCase(health.worker.status)}</CcBadge>}
            >
              <p>{health.worker.detail}</p>
              {health.worker.last_heartbeat && (
                <p className="cc-technical-value">Last heartbeat {relativeTime(health.worker.last_heartbeat)}</p>
              )}
            </CcCard>

            <CcCard
              title="Scheduler"
              icon={Clock3}
              actions={<CcBadge tone={serviceTone(health.scheduler.status)}>{titleCase(health.scheduler.status)}</CcBadge>}
            >
              <p>{health.scheduler.detail}</p>
              {health.scheduler.last_heartbeat && (
                <p className="cc-technical-value">Last heartbeat {relativeTime(health.scheduler.last_heartbeat)}</p>
              )}
            </CcCard>

            <CcCard title="Transports" icon={Server}>
              <CcMetadataGrid columns="fixed-2">
                <CcMetadataItem label="SMTP">
                  <CcBadge tone={health.smtp.configured ? "success" : "neutral"}>
                    {health.smtp.configured ? "Connected" : "Not configured"}
                  </CcBadge>
                </CcMetadataItem>
                <CcMetadataItem label="Push">
                  <CcBadge tone={health.push.configured ? "success" : "neutral"}>
                    {health.push.configured ? "Connected" : "Not configured"}
                  </CcBadge>
                </CcMetadataItem>
              </CcMetadataGrid>
            </CcCard>

            <CcCard
              title="Queue"
              icon={MailIcon}
              actions={<CcBadge tone={health.queue_status === "healthy" ? "success" : "warning"}>{titleCase(health.queue_status)}</CcBadge>}
            >
              <p className="cc-stat-number">{health.queue_depth}</p>
              <p>{health.queue_reason ?? "Outbox events not yet processed, across every topic."}</p>
            </CcCard>

            <CcCard title="Today" icon={Timer}>
              <CcMetadataGrid>
                <CcMetadataItem label="Average latency">
                  {health.average_latency_seconds !== null ? `${health.average_latency_seconds}s` : "—"}
                </CcMetadataItem>
                <CcMetadataItem label="Deliveries today">{health.deliveries_today}</CcMetadataItem>
                <CcMetadataItem label="Failures today">{health.failures_today}</CcMetadataItem>
                <CcMetadataItem label="Retries today">{health.retries_today}</CcMetadataItem>
              </CcMetadataGrid>
            </CcCard>
          </>
        )}
      </CcPage>
    </PlatformShell>
  );
}
