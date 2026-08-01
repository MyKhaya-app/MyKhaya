"use client";

import { useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";

type Overview = {
  users: Record<string, number>; homes: Record<string, number>;
  security: Record<string, number>; operations: Record<string, number>;
  system: Record<string, string | null>;
};

export default function PlatformOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { platformApi.get<Overview>("/overview").then(setData).catch((e: Error) => setError(e.message)); }, []);
  return (
    <PlatformShell><main className="platform-page">
      <div className="platform-heading"><div><p>Operational overview</p><h1>Overview</h1></div><span>Metadata only · no household content</span></div>
      {error && <p className="notice error" role="alert">{error}</p>}
      {!data ? <p role="status">Loading platform state…</p> : <>
        <section aria-labelledby="users-heading"><h2 id="users-heading">Users</h2><div className="metric-grid">{Object.entries(data.users).map(([key, value]) => <article key={key}><strong>{value}</strong><span>{key.replaceAll("_", " ")}</span></article>)}</div></section>
        <section aria-labelledby="homes-heading"><h2 id="homes-heading">Homes</h2><div className="metric-grid">{Object.entries(data.homes).map(([key, value]) => <article key={key}><strong>{value}</strong><span>{key.replaceAll("_", " ")}</span></article>)}</div></section>
        <div className="platform-columns"><section><h2>Security summary</h2><dl>{Object.entries(data.security).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl></section><section><h2>Operational state</h2><dl>{Object.entries(data.operations).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl></section></div>
        <section><h2>System information</h2><dl className="system-list">{Object.entries(data.system).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value ?? "Unknown"}</dd></div>)}</dl></section>
      </>}
    </main></PlatformShell>
  );
}
