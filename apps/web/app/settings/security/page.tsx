"use client";
import { useEffect, useState } from "react";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
type Session = {
  id: string;
  user_agent: string;
  last_seen_at: string;
  current: boolean;
};
export default function Security() {
  const [sessions, setSessions] = useState<Session[]>([]);
  useEffect(() => {
    fetch("/api/v1/auth/sessions", {
      credentials: "include",
      cache: "no-store",
    })
      .then((r) => r.json())
      .then(setSessions)
      .catch(() => undefined);
  }, []);
  async function revoke(id: string) {
    await api.delete(`/auth/sessions/${id}`);
    setSessions((v) => v.filter((s) => s.id !== id));
  }
  return (
    <SettingsPage title="Security">
      <section className="card details">
        <h2>Signed-in devices</h2>
        {sessions.map((s) => (
          <div className="session" key={s.id}>
            <div>
              <strong>{s.user_agent}</strong>
              <small>
                {s.current
                  ? "This device"
                  : `Last seen ${new Date(s.last_seen_at).toLocaleDateString()}`}
              </small>
            </div>
            {!s.current && (
              <button className="secondary" onClick={() => revoke(s.id)}>
                Sign out
              </button>
            )}
          </div>
        ))}
      </section>
    </SettingsPage>
  );
}
