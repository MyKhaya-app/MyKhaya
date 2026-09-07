"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { NotificationsSubNav } from "@/components/notifications-subnav";
import { titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";

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
  const { guarded, modal } = useReauthGuard();

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

  // POST /notification-templates/{type}/test-send is guarded server-side
  // with require_recent_auth() (apps/api/mykhaya/routers/platform.py) — a
  // 403 transparently opens PlatformReauthModal and retries the same send
  // once verified.
  // FormData is read synchronously from the event here, before guarded()
  // is entered — a reauth retry replays the wrapped callback after the
  // operator re-authenticates, by which point React has already detached
  // event.currentTarget from the original submit event, so reading the
  // form inside the guarded callback would crash on retry.
  const sendTest = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!templateType || !recipientId) return;
      const form = new FormData(event.currentTarget);
      return guarded(async () => {
        setBusy(true);
        setError("");
        setMessage("");
        try {
          await platformApi.post(`/notification-templates/${templateType}/test-send`, {
            recipient_user_id: recipientId,
            reason: form.get("reason"),
            confirmed: true,
          });
          setMessage("Test notification sent.");
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError((cause as Error).message);
        } finally {
          setBusy(false);
        }
      })();
    },
    [templateType, recipientId, guarded],
  );

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader eyebrow="Notifications" title="Test Centre" />
        <NotificationsSubNav />
        <p>
          Sends a real test notification, clearly marked &ldquo;[Test]&rdquo;, to a chosen MyKhaya
          user through the actual delivery pipeline. This never performs a real security action —
          it does not reset a password, create a session, or trigger any other business effect.
        </p>
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        <CcCard>
          <form onSubmit={sendTest}>
            <CcField label="Template">
              <select value={templateType} onChange={(event) => setTemplateType(event.target.value)} required>
                <option value="">Choose a template…</option>
                {templates.map((row) => (
                  <option key={row.template_type} value={row.template_type}>
                    {titleCase(row.template_type.replaceAll(".", " "))} ({row.template_type})
                  </option>
                ))}
              </select>
            </CcField>
            {active && (
              <p className="cc-technical-value">
                Module: {titleCase(active.module)} — Channel: {titleCase(active.channel)}
              </p>
            )}

            <CcField label="Find recipient">
              <input value={userQuery} onChange={(event) => setUserQuery(event.target.value)} placeholder="Search by email or name" />
            </CcField>
            <CcActionBar actions={[{ key: "search", label: "Search", onClick: () => void searchUsers() }]} />

            {users.length > 0 && (
              <CcField label="Recipient">
                <select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required>
                  <option value="">Choose a user…</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.display_name ?? user.email} ({user.email})
                    </option>
                  ))}
                </select>
              </CcField>
            )}

            <CcField label="Reason">
              <input name="reason" minLength={10} maxLength={500} required />
            </CcField>

            <CcActionBar
              actions={[
                {
                  key: "send",
                  label: busy ? "Sending…" : "Send test notification",
                  variant: "primary",
                  type: "submit",
                  disabled: busy || !templateType || !recipientId,
                },
              ]}
            />
          </form>
        </CcCard>
      </CcPage>
      {modal}
    </PlatformShell>
  );
}
