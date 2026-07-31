"use client";
import { FormEvent, useEffect, useState } from "react";
import type { Home, Member } from "@mykhaya/shared-types";
import { api, ApiError } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
export default function People() {
  const [home, setHome] = useState<Home | null>(null),
    [members, setMembers] = useState<Member[]>([]),
    [open, setOpen] = useState(false),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    api.homes().then((h) => {
      const first = h[0];
      if (first) {
        setHome(first);
        api.members(first.id).then(setMembers);
      }
    });
  }, []);
  async function invite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!home) return;
    const d = new FormData(e.currentTarget);
    try {
      await api.post("/invitations", {
        group_id: home.id,
        email: d.get("email"),
        role: d.get("role"),
      });
      setMessage("Invitation sent. They’ll receive a secure link shortly.");
      setError("");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t send that invitation.",
      );
    }
  }
  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{home?.name}</p>
            <h1>People</h1>
            <p>Everyone who shares this Home, together in one place.</p>
          </div>
          <button onClick={() => setOpen(!open)}>＋ Invite someone</button>
        </div>
        {open && (
          <section className="card invite-card">
            <h2>Invite someone you trust</h2>
            <form onSubmit={invite}>
              <label>
                Email
                <input name="email" type="email" required />
              </label>
              <label>
                Role
                <select name="role" defaultValue="adult_member">
                  <option value="adult_member">Adult member</option>
                  <option value="administrator">Administrator</option>
                  <option value="member">Member</option>
                  <option value="guest">Guest</option>
                </select>
              </label>
              <button>Send invitation</button>
            </form>
            <FormStatus message={message} error={error} />
          </section>
        )}
        <section className="people-grid">
          {members.map((member) => (
            <article className="card person" key={member.user_id}>
              <i>{member.display_name[0]}</i>
              <div>
                <h2>{member.display_name}</h2>
                <p>{member.email}</p>
                <span>{member.role.replace("_", " ")}</span>
              </div>
            </article>
          ))}
        </section>
      </main>
    </AppShell>
  );
}
