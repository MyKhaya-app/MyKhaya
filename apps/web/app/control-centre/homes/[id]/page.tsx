"use client";

import { FormEvent, use, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";

type HomeDetail = { id: string; name: string; active: boolean; created_at: string; members: { user_id: string; display_name: string; email: string; role: string }[]; pending_invitations: { id: string; email: string; role: string; expires_at: string }[]; feature_overrides: { feature: string; enabled: boolean }[]; notes: { id: string; body: string; created_at: string }[] };
const features = ["calendar", "tasks", "shopping", "meals", "plans", "wish_lists", "notifications", "external_sharing"];

export default function PlatformHomeDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params); const [data, setData] = useState<HomeDetail | null>(null); const [message, setMessage] = useState(""); const [reason, setReason] = useState("");
  const load = () => platformApi.get<HomeDetail>(`/homes/${encodeURIComponent(id)}`).then(setData).catch((error: Error) => setMessage(error.message));
  useEffect(() => {
    void platformApi
      .get<HomeDetail>(`/homes/${encodeURIComponent(id)}`)
      .then(setData)
      .catch((error: Error) => setMessage(error.message));
  }, [id]);
  async function stateAction(action: string) { try { const result = await platformApi.post<{ message: string }>(`/homes/${encodeURIComponent(id)}/${action}`, { reason, confirmed: true }); setMessage(result.message); await load(); } catch (error) { setMessage((error as Error).message); } }
  async function setFeature(feature: string, enabled: boolean) { try { await platformApi.put(`/homes/${encodeURIComponent(id)}/feature-flags/${feature}`, { enabled, reason, confirmed: true }); setMessage(`${feature.replaceAll("_", " ")} override updated.`); await load(); } catch (error) { setMessage((error as Error).message); } }
  async function addNote(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); await platformApi.post(`/homes/${encodeURIComponent(id)}/notes`, { body: form.get("note") }); event.currentTarget.reset(); setMessage("Administrative note added."); await load(); }
  return <PlatformShell><main className="platform-page"><div className="platform-heading"><div><p>Home metadata</p><h1>{data?.name ?? "Home"}</h1></div><span>{data?.active ? "Active" : "Suspended"}</span></div>{message && <p className="notice" role="status">{message}</p>}{data && <>
    <section className="action-panel"><h2>Controlled Home actions</h2><label>Reason for this action<input value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={500} required /></label><div>{data.active ? <button className="danger" disabled={reason.length < 10} onClick={() => stateAction("suspend")}>Suspend Home</button> : <button disabled={reason.length < 10} onClick={() => stateAction("reactivate")}>Reactivate Home</button>}</div><small>Home content is not available in this interface.</small></section>
    <section><h2>Memberships</h2><div className="record-list">{data.members.map(member => <article key={member.user_id}><strong>{member.display_name}</strong><span>{member.email} · {member.role.replaceAll("_", " ")}</span></article>)}</div></section>
    <section><h2>Pending invitations</h2><div className="record-list">{data.pending_invitations.map(invitation => <article key={invitation.id}><strong>{invitation.email}</strong><span>{invitation.role.replaceAll("_", " ")} · expires {new Date(invitation.expires_at).toLocaleDateString()}</span></article>)}</div></section>
    <section><h2>Feature availability</h2><div className="flag-list">{features.map(feature => { const current = data.feature_overrides.find(item => item.feature === feature)?.enabled; return <article key={feature}><span>{feature.replaceAll("_", " ")}</span><button disabled={reason.length < 10} onClick={() => setFeature(feature, !current)}>{current ? `Disable ${feature.replaceAll("_", " ")}` : `Enable ${feature.replaceAll("_", " ")}`}</button></article>; })}</div></section>
    <section><h2>Administrative notes</h2><form className="note-form" onSubmit={addNote}><label>New internal note<textarea name="note" minLength={2} maxLength={1000} required /></label><button>Add administrative note</button></form><div className="record-list">{data.notes.map(note => <article key={note.id}><p>{note.body}</p><time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time></article>)}</div></section>
  </>}</main></PlatformShell>;
}
