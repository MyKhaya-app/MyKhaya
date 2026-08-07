"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";

type TimelineEntry = {
  id: string;
  occurred_at: string;
  notification_type: string;
  label: string;
  channel: string;
  status: string;
  friendly_status: string;
  recipient_display_name: string | null;
  retry_count: number;
};

function statusEmoji(status: string) {
  if (status === "sent") return "✅";
  if (status === "failed") return "⚠️";
  if (status === "cancelled") return "🚫";
  return "⏳";
}

function timeOf(value: string) {
  return new Intl.DateTimeFormat("en-GB", { timeStyle: "short" }).format(new Date(value));
}

function dayOf(value: string) {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(new Date(value));
}

export default function TimelinePage() {
  const [items, setItems] = useState<TimelineEntry[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (targetPage: number, append: boolean) => {
    setLoading(true);
    setError("");
    try {
      const response = await platformApi.get<{ items: TimelineEntry[]; next_page: number | null }>(
        `/communications/timeline?page=${targetPage}`,
      );
      setItems((current) => (append ? [...current, ...response.items] : response.items));
      setNextPage(response.next_page);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(1, false);
  }, [load]);

  let lastDay = "";

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Communications</p>
            <h1>Timeline</h1>
          </div>
          <button className="secondary" onClick={() => load(1, false)}>
            Refresh
          </button>
        </div>
        <p>What actually happened, told chronologically — for "why", see Diagnostics.</p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {items.length === 0 && !loading ? (
          <p className="quiet-state">Nothing has been sent yet.</p>
        ) : (
          <ol className="timeline-list">
            {items.map((entry) => {
              const day = dayOf(entry.occurred_at);
              const showDay = day !== lastDay;
              lastDay = day;
              return (
                <li key={entry.id} className="timeline-entry">
                  {showDay && <div className="timeline-day">{day}</div>}
                  <div className="timeline-row">
                    <span className="timeline-time">{timeOf(entry.occurred_at)}</span>
                    <span className="timeline-icon" aria-hidden="true">
                      {statusEmoji(entry.status)}
                    </span>
                    <span className="timeline-copy">
                      <strong>{entry.label}</strong>
                      <span>
                        {entry.friendly_status}
                        {entry.recipient_display_name && ` · ${entry.recipient_display_name}`}
                      </span>
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {nextPage && (
          <button className="secondary" onClick={() => load(nextPage, true)} disabled={loading}>
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </main>
    </PlatformShell>
  );
}
