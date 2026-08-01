"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";

const allowed: Record<string, string> = {
  users: "Users", homes: "Homes", health: "Health and diagnostics", jobs: "Jobs and scheduler",
  mail: "Email", settings: "Global settings", "feature-flags": "Feature flags",
  security: "Security events", audit: "Administrative audit", administrators: "Administrators",
  incidents: "Public status management",
};

function flatten(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const object = payload as Record<string, unknown>;
    if (Array.isArray(object.items)) return object.items;
    if (Array.isArray(object.services)) return object.services;
    if (Array.isArray(object.settings)) return object.settings;
  }
  return payload ? [payload] : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Unknown";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return "Unknown";
}

export default function PlatformSection({ params }: { params: Promise<{ section: string }> }) {
  const { section } = use(params); const title = allowed[section];
  const [payload, setPayload] = useState<unknown>(null); const [error, setError] = useState("");
  useEffect(() => { if (title) platformApi.get(`/${section}`).then(setPayload).catch((e: Error) => setError(e.message)); }, [section, title]);
  const rows = flatten(payload); const columns = Array.from(new Set(rows.flatMap(row => row && typeof row === "object" ? Object.keys(row) : []))).slice(0, 8);
  if (!title) return <p>Not found</p>;
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Control Centre</p><h1>{title}</h1></div><span>Bounded operational view</span></div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!payload && !error ? <p role="status">Loading {title.toLowerCase()}…</p> : rows.length === 0 ? <p className="platform-empty">No records are available.</p> :
      <div className="table-scroll" tabIndex={0} aria-label={`${title} table`}><table><thead><tr>{columns.map(column => <th scope="col" key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(column => { const value = (row as Record<string, unknown>)[column]; return <td key={column}>{column === "id" && (section === "users" || section === "homes") ? <Link className="table-link" href={`/${section}/${String(value)}`}>{String(value)}</Link> : displayValue(value)}</td>; })}</tr>)}</tbody></table></div>}
  </main></PlatformShell>;
}
