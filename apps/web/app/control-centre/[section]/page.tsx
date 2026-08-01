"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";

const allowed: Record<string, string> = {
  users: "Users", homes: "Homes", health: "Health and diagnostics", jobs: "Jobs and scheduler",
  settings: "Global settings",
  security: "Security events", audit: "Administrative audit", administrators: "Administrators",
  incidents: "Public status management",
};

function flatten(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const object = payload as Record<string, unknown>;
    for (const key of ["items", "services", "settings"]) {
      if (Array.isArray(object[key])) return object[key];
    }
  }
  return payload ? [payload] : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string") return /^\d{4}-\d{2}-\d{2}T/.test(value) ? readableDate(value) : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "Unavailable";
}

export default function PlatformSection({ params }: { params: Promise<{ section: string }> }) {
  const { section } = use(params);
  const title = allowed[section];
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState("");

  async function load() {
    if (title) setPayload(await platformApi.get(`/${section}`));
  }

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [section, title]);

  const rows = flatten(payload);
  const columns = Array.from(
    new Set(rows.flatMap((row) => (row && typeof row === "object" ? Object.keys(row) : []))),
  ).slice(0, 8);

  if (!title) return <p>Not found</p>;
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Control Centre</p><h1>{title}</h1></div></div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!payload && !error ? <p role="status">Loading {title.toLowerCase()}…</p> : rows.length === 0 ? <p className="platform-empty">No records are available.</p> :
      <div className="table-scroll" tabIndex={0} aria-label={`${title} table`}><table><thead><tr>{columns.map((column) => <th scope="col" key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => { const value = (row as Record<string, unknown>)[column]; return <td key={column}>{column === "id" && (section === "users" || section === "homes") ? <Link className="table-link" href={`/${section}/${String(value)}`}>{String(value)}</Link> : displayValue(value)}</td>; })}</tr>)}</tbody></table></div>}
  </main></PlatformShell>;
}
