"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import type { ManagedDemoHome } from "@/components/platform-types";

const formatDate = (value: string | null) => value ? new Date(value).toLocaleString() : "No expiry";
const typeLabel = (value: ManagedDemoHome["fixture_type"]) => value === "apple_review" ? "Apple Review" : value === "demo" ? "Family Demo" : "QA Test";
const safeError = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

export default function ManagedDemoHomeDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const [home, setHome] = useState<ManagedDemoHome | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [expiry, setExpiry] = useState("");

  async function load() {
    setLoading(true);
    try {
      const rows = await platformApi.get<ManagedDemoHome[]>("/demo-test-homes");
      const found = rows.find(row => row.id === id) ?? null;
      setHome(found);
      setExpiry(found?.expires_at ? new Date(found.expires_at).toISOString().slice(0, 16) : "");
      if (!found) setError("Managed Demo/Test Home not found.");
    } catch (error) { setError(safeError(error, "Unable to load this managed Demo/Test Home.")); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [id]);

  async function mutate(action: "enable" | "disable" | "refresh") {
    if (!home) return;
    const prompts = {
      enable: `Enable ${home.display_name}?`,
      disable: "Disable this Demo/Test account? The Home and its data will be retained, but the managed account will no longer be able to sign in.",
      refresh: "Refreshing this Demo/Test Home will reset it to the template state and remove changes made during testing.",
    };
    if (!window.confirm(prompts[action])) return;
    setBusy(action); setError("");
    try {
      const body = action === "refresh" ? { reason: "PCC managed Demo/Test Home refresh", confirmed: true } : {};
      await platformApi.post(`/demo-test-homes/${id}/${action}`, body);
      setMessage(action === "refresh" ? "Demo/Test Home refreshed." : `Demo/Test Home ${action}d.`);
      await load();
    } catch (error) { setError(safeError(error, `Unable to ${action} this Demo/Test Home.`)); }
    finally { setBusy(""); }
  }

  async function resetPassword(event: React.FormEvent) {
    event.preventDefault();
    if (password.length < 12 || password !== confirmPassword) { setError("Passwords must match and be at least 12 characters."); return; }
    if (!window.confirm(`Reset password for ${home?.account_email ?? "this managed account"}?`)) return;
    setBusy("password"); setError("");
    try { await platformApi.post(`/demo-test-homes/${id}/password`, { password }); setPassword(""); setConfirmPassword(""); setPasswordOpen(false); setMessage("Password reset successfully."); }
    catch (error) { setError(safeError(error, "Unable to reset the managed account password.")); }
    finally { setBusy(""); }
  }

  async function saveExpiry(event: React.FormEvent) {
    event.preventDefault(); setBusy("expiry"); setError("");
    try { await platformApi.patch(`/demo-test-homes/${id}/expiry`, { expires_at: expiry ? new Date(expiry).toISOString() : null }); setMessage("Expiry updated."); await load(); }
    catch (error) { setError(safeError(error, "Unable to update expiry.")); }
    finally { setBusy(""); }
  }

  async function remove() {
    if (!home || !window.confirm(`Delete this Demo/Test Home? ${home.display_name} and its fixture-owned data will be permanently removed. This cannot be undone.`)) return;
    setBusy("delete"); setError("");
    try { await platformApi.delete(`/demo-test-homes/${id}`, { reason: `Delete managed Demo/Test Home ${home.display_name}`, confirmed: true }); router.push("/demo-test-homes"); }
    catch (error) { setError(safeError(error, "Unable to delete this managed Demo/Test Home.")); setBusy(""); }
  }

  const statusText = useMemo(() => home?.status === "expired" ? `Expired${home.expires_at ? `: ${formatDate(home.expires_at)}` : ""}` : home?.status ?? "", [home]);
  return <PlatformShell><main className="platform-page"><p><a href="/demo-test-homes">← Demo &amp; Test Homes</a></p>{loading ? <p>Loading managed Home…</p> : !home ? <p role="alert">{error}</p> : <><div className="platform-heading"><div><p>Operations</p><h1>{home.display_name}</h1></div><strong>{statusText}</strong></div>{message && <p className="notice" role="status">{message}</p>}{error && <p className="notice" role="alert">{error}</p>}<section className="platform-card"><h2>Details</h2><dl><dt>Template</dt><dd>{typeLabel(home.fixture_type)}</dd><dt>Owner account</dt><dd>{home.account_email}</dd><dt>Verification</dt><dd>{home.email_verified ? "Verified" : "Unverified"}</dd><dt>Family access</dt><dd>{home.access}</dd><dt>Template version</dt><dd>{home.template_version}</dd><dt>Created</dt><dd>{formatDate(home.created_at)}</dd><dt>Created by</dt><dd>{home.created_by ?? "CLI / system"}</dd><dt>Last refreshed</dt><dd>{formatDate(home.refreshed_at)}</dd><dt>Disabled</dt><dd>{formatDate(home.disabled_at)}</dd><dt>Fixture key</dt><dd>{home.fixture_key}</dd></dl></section><section className="platform-card"><h2>Lifecycle</h2><p>{home.expires_at ? `${home.status === "expired" ? "Expired" : "Expires"}: ${formatDate(home.expires_at)}` : "No expiry"}</p><form onSubmit={saveExpiry}><label>Set or change expiry<input type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)} /></label><button disabled={busy === "expiry"}>{busy === "expiry" ? "Saving…" : "Save expiry"}</button><button type="button" className="secondary" disabled={busy === "expiry" || !home.expires_at} onClick={() => setExpiry("")}>Remove expiry</button></form><div><button disabled={Boolean(busy) || home.status === "enabled"} onClick={() => void mutate("enable")}>Enable</button>{home.status === "enabled" && <button className="danger" disabled={Boolean(busy)} onClick={() => void mutate("disable")}>Disable</button>}<button disabled={Boolean(busy)} onClick={() => void mutate("refresh")}>Refresh / Reset</button><button className="secondary" disabled={Boolean(busy)} onClick={() => setPasswordOpen(value => !value)}>Reset Password</button><button className="danger" disabled={Boolean(busy)} onClick={() => void remove()}>Delete</button></div></section>{passwordOpen && <section className="platform-card"><h2>Reset password for {home.account_email}</h2><form onSubmit={resetPassword}><label>New password<input type="password" autoComplete="new-password" minLength={12} value={password} onChange={event => setPassword(event.target.value)} /></label><label>Confirm password<input type="password" autoComplete="new-password" minLength={12} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} /></label><button disabled={busy === "password"}>{busy === "password" ? "Resetting…" : "Reset password"}</button></form></section>}</>}</main></PlatformShell>;
}
