"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { titleCase } from "@/components/platform-format";

const lifecycle = ["hidden", "internal", "beta", "early_access", "released", "deprecated"] as const;
type ModuleState = { key: string; name: string; description: string; category: string; dependencies: string[]; enabled: boolean; release_state: string };

export default function ModulesPage() {
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { enabled: boolean; release_state: string }>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      const rows = await platformApi.get<ModuleState[]>("/modules");
      setModules(rows);
      setDrafts(Object.fromEntries(rows.map((row) => [row.key, { enabled: row.enabled, release_state: row.release_state }])));
    } catch (cause) { setError((cause as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function save(module: ModuleState) {
    const draft = drafts[module.key];
    if (!draft || !window.confirm(`Apply the lifecycle change to ${module.name}?`)) return;
    setError(""); setMessage("");
    try {
      await platformApi.put(`/modules/${encodeURIComponent(module.key)}`, { ...draft, reason, confirmed: true });
      setMessage(`${module.name} was updated and the change was audited.`);
      await load();
    } catch (cause) { setError((cause as Error).message); }
  }
  return <PlatformShell><main className="platform-page">
    <div className="platform-heading"><div><p>Platform lifecycle controls</p><h1>Modules & Features</h1></div></div>
    {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    <section className="action-panel module-reason"><label>Reason for lifecycle changes<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={500} required /></label><small>Every change requires recent authentication, explicit confirmation and is recorded in the administrative audit.</small></section>
    {!modules.length && !error ? <p role="status">Loading module lifecycle state…</p> : <section className="module-list">{modules.map((module) => {
      const draft = drafts[module.key] ?? { enabled: module.enabled, release_state: module.release_state };
      const changed = draft.enabled !== module.enabled || draft.release_state !== module.release_state;
      return <article key={module.key}><div className="module-copy"><div><span>{module.category}</span><h2>{module.name}</h2></div><p>{module.description}</p>{module.dependencies.length > 0 && <small>Depends on {module.dependencies.map(titleCase).join(", ")}</small>}</div><div className="module-controls"><label>Lifecycle<select value={draft.release_state} onChange={(event) => setDrafts((current) => ({ ...current, [module.key]: { ...draft, release_state: event.target.value } }))}>{lifecycle.map((state) => <option value={state} key={state}>{titleCase(state)}</option>)}</select></label><label className="module-toggle"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDrafts((current) => ({ ...current, [module.key]: { ...draft, enabled: event.target.checked } }))} />Enabled globally</label><button disabled={!changed || reason.trim().length < 10} onClick={() => save(module)}>Apply change</button></div></article>;
    })}</section>}
  </main></PlatformShell>;
}
