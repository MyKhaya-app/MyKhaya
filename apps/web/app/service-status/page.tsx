"use client";

import { useEffect, useState } from "react";

type StatusPayload = { overall: string; last_updated: string; services: { key: string; name: string; state: string }[]; current_incidents: { id: string; title: string; message: string; state: string; started_at: string }[]; recent_incidents: { id: string; title: string; state: string; started_at: string; resolved_at: string }[] };
const label = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, match => match.toUpperCase());

export default function ServiceStatus() {
  const [data, setData] = useState<StatusPayload | null>(null); const [error, setError] = useState("");
  useEffect(() => { fetch("/api/v1/status", { cache: "no-store" }).then(async response => { if (!response.ok) throw new Error("Status information is temporarily unavailable."); return response.json() as Promise<StatusPayload>; }).then(setData).catch((reason: Error) => setError(reason.message)); }, []);
  return <main className="status-page"><header><strong>MyKhaya</strong><span>Service status</span></header><section className="status-content">
    <p className="status-kicker">MyKhaya service availability</p><h1>System status</h1>
    {error ? <div className="status-banner unknown" role="status"><strong>Status unavailable</strong><span>{error}</span></div> : !data ? <p role="status">Checking service status…</p> : <>
      <div className={`status-banner ${data.overall}`}><strong>{label(data.overall)}</strong><span>Last updated <time dateTime={data.last_updated}>{new Date(data.last_updated).toLocaleString()}</time></span></div>
      <section><h2>Services</h2><div className="service-list">{data.services.map(service => <article key={service.key}><span>{service.name}</span><strong className={service.state}><i aria-hidden="true" />{label(service.state)}</strong></article>)}</div></section>
      <section><h2>Current incidents</h2>{data.current_incidents.length ? data.current_incidents.map(incident => <article className="incident" key={incident.id}><h3>{incident.title}</h3><p>{incident.message}</p><time dateTime={incident.started_at}>{new Date(incident.started_at).toLocaleString()}</time></article>) : <p className="status-clear">No current incidents.</p>}</section>
      <section><h2>Recent history</h2>{data.recent_incidents.length ? data.recent_incidents.map(incident => <article className="history" key={incident.id}><strong>{incident.title}</strong><span>{label(incident.state)}</span></article>) : <p className="status-clear">No incidents reported in the last 90 days.</p>}</section>
    </>}
  </section><footer>Only customer-facing service information is published here.</footer></main>;
}
