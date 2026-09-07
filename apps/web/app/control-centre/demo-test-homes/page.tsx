"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import type { ManagedDemoHome, ManagedDemoHomeCreateRequest } from "@/components/platform-types";

const labels = { apple_review: "Apple Review", demo: "Family Demo", qa_test: "QA Test" } as const;

export default function DemoTestHomesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<ManagedDemoHome[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const load = async () => { try { setRows(await platformApi.get<ManagedDemoHome[]>("/demo-test-homes")); setError(""); } catch { setError("Unable to load managed Demo/Test Homes."); } };
  useEffect(() => { void load(); }, []);
  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setFormError("");
    if (password.length < 12 || password !== confirm) { setFormError("Passwords must match and be at least 12 characters."); return; }
    const data = new FormData(event.currentTarget);
    const field = (name: string) => { const value = data.get(name); return typeof value === "string" ? value : ""; };
    const request: ManagedDemoHomeCreateRequest = { fixture_key: field("fixture_key"), display_name: field("display_name"), fixture_type: field("fixture_type") as ManagedDemoHomeCreateRequest["fixture_type"], email: field("email"), password, expires_at: field("expires_at") ? new Date(field("expires_at")).toISOString() : null, enabled: data.get("enabled") === "on" };
    setBusy(true);
    try { const created = await platformApi.post<ManagedDemoHome>("/demo-test-homes", request); setPassword(""); setConfirm(""); router.push(`/control-centre/demo-test-homes/${created.id}`); }
    catch { setFormError("Unable to create the managed Home. Check the details and try again."); }
    finally { setBusy(false); }
  }
  return <PlatformShell><main className="platform-page"><div className="platform-heading"><div><p>Operations</p><h1>Demo &amp; Test Homes</h1></div><button onClick={() => setOpen(value => !value)}>+ Create Demo/Test Home</button></div>{error && <p className="notice" role="alert">{error}</p>}{open && <form className="platform-card" onSubmit={create}><h2>Create Demo/Test Home</h2><p>Demo/Test accounts created here are provisioned as verified managed accounts and do not require email verification.</p><label>Template<select name="fixture_type" defaultValue="apple_review"><option value="apple_review">Apple Review</option><option value="demo">Family Demo</option></select></label><label>Fixture key<input name="fixture_key" required pattern="[a-z0-9][a-z0-9-]+" /></label><label>Home name<input name="display_name" required /></label><label>Account email<input name="email" type="email" required /></label><label>New password<input name="password" type="password" autoComplete="new-password" minLength={12} value={password} onChange={event => setPassword(event.target.value)} required /></label><label>Confirm password<input name="confirm_password" type="password" autoComplete="new-password" minLength={12} value={confirm} onChange={event => setConfirm(event.target.value)} required /></label><label>Expiry<input name="expires_at" type="datetime-local" /></label><label><input name="enabled" type="checkbox" defaultChecked /> Enabled</label>{formError && <p role="alert">{formError}</p>}<button disabled={busy}>{busy ? "Creating…" : "Create"}</button><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button></form>}<section className="platform-card"><button className="secondary" onClick={() => void load()}>Refresh list</button>{rows.length === 0 ? <p className="platform-empty">No managed Demo/Test Homes.</p> : <div className="platform-table-wrap"><table><thead><tr><th>Home</th><th>Template</th><th>Account</th><th>Status</th><th>Verification</th><th>Access</th><th>Version</th><th>Refreshed</th><th>Expiry</th><th /></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><a href={`/control-centre/demo-test-homes/${row.id}`}>{row.display_name}</a><br /><small>{row.fixture_key}</small></td><td>{labels[row.fixture_type]}</td><td>{row.account_email}</td><td>{row.status}</td><td>{row.email_verified ? "Verified" : "Unverified"}</td><td>{row.access}</td><td>{row.template_version}</td><td>{row.refreshed_at ? new Date(row.refreshed_at).toLocaleString() : "Never"}</td><td>{row.expires_at ? new Date(row.expires_at).toLocaleString() : "No expiry"}</td><td><button className="secondary" onClick={() => router.push(`/control-centre/demo-test-homes/${row.id}`)}>View</button></td></tr>)}</tbody></table></div>}</section></main></PlatformShell>;
}
