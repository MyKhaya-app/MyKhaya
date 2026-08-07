"use client";

import { FormEvent, useCallback, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, titleCase } from "@/components/platform-format";

type DiagnosticsEntry = {
  id: string;
  occurred_at: string;
  notification_type: string;
  label: string;
  channel: string;
  status: string;
  recipient_email: string | null;
  sanitised_failure_reason: string | null;
  retry_count: number;
  idempotency_key: string;
};

export default function DiagnosticsPage() {
  const [items, setItems] = useState<DiagnosticsEntry[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [lastParams, setLastParams] = useState<URLSearchParams>(new URLSearchParams());

  const search = useCallback(async (params: URLSearchParams, page: number, append: boolean) => {
    setLoading(true);
    setError("");
    try {
      params.set("page", String(page));
      const response = await platformApi.get<{
        items: DiagnosticsEntry[];
        next_page: number | null;
      }>(`/communications/diagnostics?${params.toString()}`);
      setItems((current) => (append ? [...current, ...response.items] : response.items));
      setNextPage(response.next_page);
      setSearched(true);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  function buildParams(form: FormData): URLSearchParams {
    const params = new URLSearchParams();
    const status = form.get("status") as string;
    const channel = form.get("channel") as string;
    const notificationType = (form.get("notification_type") as string)?.trim();
    const recipientEmail = (form.get("recipient_email") as string)?.trim();
    if (status) params.set("status", status);
    if (channel) params.set("channel", channel);
    if (notificationType) params.set("notification_type", notificationType);
    if (recipientEmail) params.set("recipient_email", recipientEmail);
    return params;
  }

  async function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = buildParams(new FormData(event.currentTarget));
    setLastParams(params);
    await search(params, 1, false);
  }

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Communications</p>
            <h1>Diagnostics</h1>
          </div>
        </div>
        <p>Why did this one fail? Filter by status, channel, type or recipient.</p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        <form className="action-panel" onSubmit={onSearch}>
          <label>
            Status
            <select name="status" defaultValue="">
              <option value="">Any</option>
              <option value="queued">Queued</option>
              <option value="sent">Sent</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <label>
            Channel
            <select name="channel" defaultValue="">
              <option value="">Any</option>
              <option value="email">Email</option>
              <option value="push">Push</option>
              <option value="in_app">In-app</option>
            </select>
          </label>
          <label>
            Notification type
            <input name="notification_type" placeholder="e.g. event_reminder" />
          </label>
          <label>
            Recipient email
            <input name="recipient_email" type="email" />
          </label>
          <button disabled={loading}>{loading ? "Searching…" : "Search"}</button>
        </form>

        {searched && items.length === 0 && !loading && (
          <p className="quiet-state">No deliveries match those filters.</p>
        )}

        {items.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>Recipient</th>
                  <th>Retries</th>
                  <th>Failure reason</th>
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => (
                  <tr key={entry.id}>
                    <td>{readableDate(entry.occurred_at)}</td>
                    <td>{entry.label}</td>
                    <td>{titleCase(entry.channel)}</td>
                    <td>{titleCase(entry.status)}</td>
                    <td>{entry.recipient_email ?? "—"}</td>
                    <td>{entry.retry_count}</td>
                    <td>{entry.sanitised_failure_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {nextPage && (
          <button
            className="secondary"
            onClick={() => {
              const params = new URLSearchParams(lastParams);
              void search(params, nextPage, true);
            }}
            disabled={loading}
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </main>
    </PlatformShell>
  );
}
