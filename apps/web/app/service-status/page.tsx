"use client";

import { useEffect, useState } from "react";
import type { IncidentLifecycleState, ServiceState } from "@/components/platform-types";
import { formatDuration, lifecycleStateLabel, serviceStateLabel } from "@/components/status-incidents-logic";

type StatusService = { key: string; name: string; state: ServiceState };
type StatusIncidentServiceEntry = { key: string; name: string; impact: ServiceState };
type StatusIncidentUpdateEntry = {
  lifecycle_state: IncidentLifecycleState;
  message: string;
  occurred_at: string;
};
type StatusIncident = {
  id: string;
  title: string;
  lifecycle_state: IncidentLifecycleState;
  services: StatusIncidentServiceEntry[];
  started_at: string;
  resolved_at: string | null;
  updates: StatusIncidentUpdateEntry[];
};
type ResolvedStatusIncident = StatusIncident & { duration_seconds: number | null };
type StatusPayload = {
  overall: ServiceState;
  overall_message: string;
  last_updated: string;
  services: StatusService[];
  current_incidents: StatusIncident[];
  recent_incidents: ResolvedStatusIncident[];
};

// Resolved incidents grouped by the calendar date they were resolved on
// (browser-local), newest first within each group (the API already orders
// recent_incidents by start date descending).
function groupByResolvedDate(
  incidents: ResolvedStatusIncident[],
): { heading: string; incidents: ResolvedStatusIncident[] }[] {
  const order: string[] = [];
  const groups = new Map<string, ResolvedStatusIncident[]>();
  for (const incident of incidents) {
    const heading = incident.resolved_at
      ? new Date(incident.resolved_at).toLocaleDateString("en-GB", {
          day: "numeric",
          month: "long",
          year: "numeric",
        })
      : "Date unavailable";
    if (!groups.has(heading)) {
      groups.set(heading, []);
      order.push(heading);
    }
    groups.get(heading)!.push(incident);
  }
  return order.map((heading) => ({ heading, incidents: groups.get(heading)! }));
}

function IncidentTimeline({ updates }: { updates: StatusIncidentUpdateEntry[] }) {
  if (updates.length === 0) return null;
  return (
    <div className="incident-timeline">
      {updates.map((update, index) => (
        <div className="incident-timeline-entry" key={index}>
          <strong>
            {new Date(update.occurred_at).toLocaleString()} — {lifecycleStateLabel(update.lifecycle_state)}
          </strong>
          <p>{update.message}</p>
        </div>
      ))}
    </div>
  );
}

function AffectedServices({ services }: { services: StatusIncidentServiceEntry[] }) {
  return (
    <div className="incident-services">
      {services.map((service) => (
        <span key={service.key}>
          {service.name} — {serviceStateLabel(service.impact)}
        </span>
      ))}
    </div>
  );
}

function IncidentCard({ incident }: { incident: StatusIncident }) {
  return (
    <article className="incident">
      <h3>{incident.title}</h3>
      <div className="incident-meta">
        <span className={`incident-state ${incident.lifecycle_state}`}>
          {lifecycleStateLabel(incident.lifecycle_state)}
        </span>
        <time dateTime={incident.started_at}>
          Started {new Date(incident.started_at).toLocaleString()}
        </time>
      </div>
      <AffectedServices services={incident.services} />
      <IncidentTimeline updates={incident.updates} />
    </article>
  );
}

function HistoryEntry({ incident }: { incident: ResolvedStatusIncident }) {
  return (
    <details className="history">
      <summary>
        <strong>{incident.title}</strong>
        <span>
          {incident.resolved_at
            ? `Resolved after ${formatDuration(incident.started_at, incident.resolved_at)}`
            : "Resolved"}
        </span>
      </summary>
      <div className="history-body">
        <AffectedServices services={incident.services} />
        <p>
          Started {new Date(incident.started_at).toLocaleString()}
          {incident.resolved_at && <> · Resolved {new Date(incident.resolved_at).toLocaleString()}</>}
        </p>
        <IncidentTimeline updates={incident.updates} />
      </div>
    </details>
  );
}

export default function ServiceStatus() {
  const [data, setData] = useState<StatusPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v1/status", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Status information is temporarily unavailable.");
        return response.json() as Promise<StatusPayload>;
      })
      .then(setData)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  return (
    <main className="status-page">
      <header>
        <strong>MyKhaya</strong>
        <span>Service status</span>
      </header>
      <section className="status-content">
        <p className="status-kicker">MyKhaya service availability</p>
        <h1>System status</h1>

        {error ? (
          <div className="status-banner unknown" role="status">
            <strong>Status unavailable</strong>
            <span>{error}</span>
          </div>
        ) : !data ? (
          <p role="status">Checking service status…</p>
        ) : (
          <>
            <div className={`status-banner ${data.overall}`} role="status">
              <strong>{data.overall_message}</strong>
              <span>
                Last updated{" "}
                <time dateTime={data.last_updated}>{new Date(data.last_updated).toLocaleString()}</time>
              </span>
            </div>

            <section>
              <h2>Services</h2>
              <div className="service-list">
                {data.services.map((service) => (
                  <article key={service.key}>
                    <span>{service.name}</span>
                    <strong className={service.state}>
                      <i aria-hidden="true" />
                      {serviceStateLabel(service.state)}
                    </strong>
                  </article>
                ))}
              </div>
            </section>

            <section>
              <h2>Current incidents</h2>
              {data.current_incidents.length ? (
                data.current_incidents.map((incident) => (
                  <IncidentCard key={incident.id} incident={incident} />
                ))
              ) : (
                <p className="status-clear">No current incidents.</p>
              )}
            </section>

            <section>
              <h2>Recent history</h2>
              {data.recent_incidents.length ? (
                groupByResolvedDate(data.recent_incidents).map((group) => (
                  <div className="history-group" key={group.heading}>
                    <p className="history-group-heading">{group.heading}</p>
                    {group.incidents.map((incident) => (
                      <HistoryEntry key={incident.id} incident={incident} />
                    ))}
                  </div>
                ))
              ) : (
                <p className="status-clear">No incidents reported in the last 90 days.</p>
              )}
            </section>
          </>
        )}
      </section>
      <footer>Only customer-facing service information is published here.</footer>
    </main>
  );
}
