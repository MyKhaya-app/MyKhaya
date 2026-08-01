"use client";

import { FormEvent, use, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";

type UserDetail = { id: string; email: string; display_name: string; verified: boolean; active: boolean; created_at: string; last_login_at: string | null; homes: { id: string; name: string; role: string }[]; sessions: { id: string; user_agent: string; last_seen_at: string; expires_at: string }[]; notes: { id: string; body: string; created_at: string }[] };

export default function PlatformUserDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params); const [data, setData] = useState<UserDetail | null>(null); const [message, setMessage] = useState(""); const [reason, setReason] = useState("");
  const load = () => platformApi.get<UserDetail>(`/users/${encodeURIComponent(id)}`).then(setData).catch((error: Error) => setMessage(error.message));
  useEffect(() => {
    void platformApi
      .get<UserDetail>(`/users/${encodeURIComponent(id)}`)
      .then(setData)
      .catch((error: Error) => setMessage(error.message));
  }, [id]);
  async function action(name: string) { setMessage(""); try { const result = await platformApi.post<{ message: string }>(`/users/${encodeURIComponent(id)}/${name}`, { reason, confirmed: true }); setMessage(result.message); await load(); } catch (error) { setMessage((error as Error).message); } }
  async function addNote(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); await platformApi.post(`/users/${encodeURIComponent(id)}/notes`, { body: form.get("note") }); event.currentTarget.reset(); setMessage("Administrative note added."); await load(); }
  return <PlatformShell><main className="platform-page"><div className="platform-heading"><div><p>User account</p><h1>{data?.display_name ?? "User"}</h1></div><span>{data?.email}</span></div>{message && <p className="notice" role="status">{message}</p>}{data && <>
    <section className="record-card"><h2>Account metadata</h2><dl><div><dt>Status</dt><dd>{data.active ? "Active" : "Suspended"}</dd></div><div><dt>Email verification</dt><dd>{data.verified ? "Verified" : "Unverified"}</dd></div><div><dt>Created</dt><dd>{new Date(data.created_at).toLocaleString()}</dd></div><div><dt>Last login</dt><dd>{data.last_login_at ? new Date(data.last_login_at).toLocaleString() : "Unknown"}</dd></div></dl></section>
    <section className="action-panel"><h2>Controlled account actions</h2><label>Reason for this action<input value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={500} required /></label><div>{data.active ? <button className="danger" disabled={reason.length < 10} onClick={() => action("suspend")}>Suspend user</button> : <button disabled={reason.length < 10} onClick={() => action("reactivate")}>Reactivate user</button>}<button disabled={reason.length < 10} onClick={() => action("revoke-sessions")}>Revoke all sessions</button>{!data.verified && <button disabled={reason.length < 10} onClick={() => action("resend-verification")}>Resend verification email</button>}<button disabled={reason.length < 10} onClick={() => action("send-password-reset")}>Send password-reset email</button></div><small>These actions require a recent operator authentication and are audited.</small></section>
    <section><h2>Homes and memberships</h2><div className="record-list">{data.homes.map(home => <article key={home.id}><strong>{home.name}</strong><span>{home.role.replaceAll("_", " ")}</span></article>)}</div></section>
    <section><h2>Active sessions</h2><div className="record-list">{data.sessions.map(session => <article key={session.id}><strong>{session.user_agent}</strong><span>Last seen {new Date(session.last_seen_at).toLocaleString()}</span></article>)}</div></section>
    <section><h2>Administrative notes</h2><form className="note-form" onSubmit={addNote}><label>New internal note<textarea name="note" minLength={2} maxLength={1000} required /></label><button>Add administrative note</button></form><div className="record-list">{data.notes.map(note => <article key={note.id}><p>{note.body}</p><time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time></article>)}</div></section>
  </>}</main></PlatformShell>;
}
