"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime, titleCase } from "@/components/platform-format";

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

function overallEmoji(overall: Health["overall"]) {
  if (overall === "healthy") return "🟢";
  if (overall === "degraded") return "🟡";
  return "🔴";
}

function serviceEmoji(status: ServiceStatus["status"]) {
  if (status === "running") return "🟢";
  if (status === "stale") return "🟡";
  return "🔴";
}

function transportEmoji(status: TransportStatus["status"]) {
  return status === "connected" ? "🟢" : "⚪";
}

export default function CommunicationsHealthPage() {
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
    const interval = setInterval(() => void load(), 30_000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Communications</p>
            <h1>
              {health && `${overallEmoji(health.overall)} `}
              {health ? titleCase(health.overall) : "Loading…"}
            </h1>
          </div>
          <button className="secondary" onClick={load}>
            Refresh
          </button>
        </div>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {!health ? (
          <p role="status">Loading communications health…</p>
        ) : (
          <div className="overview-grid">
            <section className="overview-panel">
              <h2>Worker</h2>
              <p>
                {serviceEmoji(health.worker.status)} {titleCase(health.worker.status)}
              </p>
              <small>{health.worker.detail}</small>
              {health.worker.last_heartbeat && (
                <p>
                  <small>Last heartbeat {relativeTime(health.worker.last_heartbeat)}</small>
                </p>
              )}
            </section>
            <section className="overview-panel">
              <h2>Scheduler</h2>
              <p>
                {serviceEmoji(health.scheduler.status)} {titleCase(health.scheduler.status)}
              </p>
              <small>{health.scheduler.detail}</small>
              {health.scheduler.last_heartbeat && (
                <p>
                  <small>Last heartbeat {relativeTime(health.scheduler.last_heartbeat)}</small>
                </p>
              )}
            </section>
            <section className="overview-panel">
              <h2>SMTP</h2>
              <p>
                {transportEmoji(health.smtp.status)}{" "}
                {health.smtp.configured ? "Connected" : "Not configured"}
              </p>
            </section>
            <section className="overview-panel">
              <h2>Push</h2>
              <p>
                {transportEmoji(health.push.status)}{" "}
                {health.push.configured ? "Connected" : "Not configured"}
              </p>
            </section>
            <section className="overview-panel">
              <h2>Queued</h2>
              <p>{health.queue_status === "healthy" ? "🟢 Healthy" : "🟡 Warning"}</p>
              <p className="stat-number">{health.queue_depth}</p>
              <small>
                {health.queue_reason ?? "Outbox events not yet processed, across every topic."}
              </small>
            </section>
            <section className="overview-panel">
              <h2>Average latency</h2>
              <p className="stat-number">
                {health.average_latency_seconds !== null
                  ? `${health.average_latency_seconds}s`
                  : "—"}
              </p>
              <small>Scheduled → delivered, for today's successful sends.</small>
            </section>
            <section className="overview-panel">
              <h2>Deliveries today</h2>
              <p className="stat-number">{health.deliveries_today}</p>
            </section>
            <section className="overview-panel">
              <h2>Failures today</h2>
              <p className="stat-number">{health.failures_today}</p>
            </section>
            <section className="overview-panel">
              <h2>Retries today</h2>
              <p className="stat-number">{health.retries_today}</p>
            </section>
          </div>
        )}
      </main>
    </PlatformShell>
  );
}
