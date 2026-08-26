"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { titleCase } from "@/components/platform-format";

type Template = {
  template_type: string;
  module: string;
  channel: string;
};

type UserRow = {
  id: string;
  email: string;
  display_name: string | null;
};

/** Sends through the real delivery pipeline (email via the configured SMTP
 *  transport, in-app via the real notify() fan-out) so what an admin sees
 *  here matches production behaviour — but every send is prefixed "[Test]"
 *  and uses a fresh idempotency key, and never touches auth/security state
 *  (no real password reset, session, or verification side effects). */
export default function NotificationTestCentrePage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateType, setTemplateType] = useState("");
  const [userQuery, setUserQuery] = useState("");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [recipientId, setRecipientId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setTemplates(await platformApi.get<Template[]>("/notification-templates"));
      } catch (cause) {
        setError((cause as Error).message);
      }
    })();
  }, []);

  const searchUsers = useCallback(async () => {
    setError("");
    try {
      const page = await platformApi.get<{ items: UserRow[] }>(
        `/users?q=${encodeURIComponent(userQuery)}&page=1&page_size=10`,
      );
      setUsers(page.items);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, [userQuery]);

  const active = templates.find((row) => row.template_type === templateType) ?? null;

  async function sendTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!templateType || !recipientId) return;
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      await platformApi.post(`/notification-templates/${templateType}/test-send`, {
        recipient_user_id: recipientId,
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage("Test notification sent.");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Notifications</p>
            <h1>Test Centre</h1>
          </div>
        </div>
        <NotificationsSubNav />
        <p>
          Sends a real test notification, clearly marked &ldquo;[Test]&rdquo;, to a chosen MyKhaya
          user through the actual delivery pipeline. This never performs a real security action —
          it does not reset a password, create a session, or trigger any other business effect.
        </p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}

        <form className="action-panel" onSubmit={sendTest}>
          <label>
            Template
            <select value={templateType} onChange={(event) => setTemplateType(event.target.value)} required>
              <option value="">Choose a template…</option>
              {templates.map((row) => (
                <option key={row.template_type} value={row.template_type}>
                  {titleCase(row.template_type.replaceAll(".", " "))} ({row.template_type})
                </option>
              ))}
            </select>
          </label>
          {active && (
            <p>
              <small>
                Module: {titleCase(active.module)} — Channel: {titleCase(active.channel)}
              </small>
            </p>
          )}

          <label>
            Find recipient
            <input
              value={userQuery}
              onChange={(event) => setUserQuery(event.target.value)}
              placeholder="Search by email or name"
            />
          </label>
          <button type="button" className="secondary" onClick={searchUsers}>
            Search
          </button>

          {users.length > 0 && (
            <label>
              Recipient
              <select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required>
                <option value="">Choose a user…</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name ?? user.email} ({user.email})
                  </option>
                ))}
              </select>
            </label>
          )}

          <label>
            Reason
            <input name="reason" minLength={10} maxLength={500} required />
          </label>

          <button disabled={busy || !templateType || !recipientId}>
            {busy ? "Sending…" : "Send test notification"}
          </button>
        </form>
      </main>
    </PlatformShell>
  );
}
