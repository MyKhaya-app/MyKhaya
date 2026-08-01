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
    for (const key of ["items", "services", "settings"]) {
      if (Array.isArray(object[key])) return object[key];
    }
  }
  return payload ? [payload] : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Unknown";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "Unknown";
}

export default function PlatformSection({ params }: { params: Promise<{ section: string }> }) {
  const { section } = use(params);
  const title = allowed[section];
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");

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

  async function updateFlag(key: string, enabled: boolean) {
    if (!window.confirm(`${enabled ? "Enable" : "Disable"} ${key.replaceAll("_", " ")} globally?`)) return;
    setError(""); setMessage("");
    try {
      await platformApi.put(`/feature-flags/${encodeURIComponent(key)}`, {
        enabled, reason, confirmed: true,
      });
      setMessage(`${key.replaceAll("_", " ")} updated.`);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  if (!title) return <p>Not found</p>;
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Control Centre</p><h1>{title}</h1></div><span>Bounded operational view</span></div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {section === "feature-flags" && <section className="action-panel"><h2>Global feature controls</h2><label>Reason for this change<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={500} required /></label><div>{rows.map((row) => { const flag = row as { key: string; enabled: boolean }; return <button key={flag.key} disabled={reason.length < 10} onClick={() => updateFlag(flag.key, !flag.enabled)}>{flag.enabled ? "Disable" : "Enable"} {flag.key.replaceAll("_", " ")}</button>; })}</div><small>Changes require recent authentication, confirmation and an audit reason.</small></section>}
    {!payload && !error ? <p role="status">Loading {title.toLowerCase()}…</p> : rows.length === 0 ? <p className="platform-empty">No records are available.</p> :
      <div className="table-scroll" tabIndex={0} aria-label={`${title} table`}><table><thead><tr>{columns.map((column) => <th scope="col" key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => { const value = (row as Record<string, unknown>)[column]; return <td key={column}>{column === "id" && (section === "users" || section === "homes") ? <Link className="table-link" href={`/${section}/${String(value)}`}>{String(value)}</Link> : displayValue(value)}</td>; })}</tr>)}</tbody></table></div>}
  </main></PlatformShell>;
}
