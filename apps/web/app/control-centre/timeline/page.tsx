"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcEmptyState, CcLoadingState } from "@/components/control-centre/status-message";

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

const statusTone: Record<string, CcBadgeTone> = {
  sent: "success",
  failed: "danger",
  cancelled: "neutral",
  queued: "warning",
};

const statusIcon: Record<string, typeof CheckCircle2> = {
  sent: CheckCircle2,
  failed: XCircle,
  cancelled: XCircle,
};

function statusToneFor(status: string): CcBadgeTone {
  return statusTone[status] ?? "warning";
}

function timeOf(value: string) {
  return new Intl.DateTimeFormat("en-GB", { timeStyle: "short" }).format(new Date(value));
}

function dayOf(value: string) {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(new Date(value));
}

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
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
      setError(safeError(cause, "The timeline could not be loaded."));
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
      <CcPage>
        <CcPageHeader
          eyebrow="Communications"
          title="Timeline"
          description={`What actually happened, told chronologically — for "why", see Diagnostics.`}
          secondaryActions={
            <button className="secondary" onClick={() => load(1, false)}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {loading && items.length === 0 ? (
          <CcLoadingState label="Loading timeline…" />
        ) : items.length === 0 ? (
          <CcEmptyState>Nothing has been sent yet.</CcEmptyState>
        ) : (
          <ol className="timeline-list">
            {items.map((entry) => {
              const day = dayOf(entry.occurred_at);
              const showDay = day !== lastDay;
              lastDay = day;
              const Icon = statusIcon[entry.status] ?? Clock;
              return (
                <li key={entry.id} className="timeline-entry">
                  {showDay && <div className="timeline-day">{day}</div>}
                  <div className="timeline-row">
                    <span className="timeline-time">{timeOf(entry.occurred_at)}</span>
                    <span className="timeline-icon" aria-hidden="true">
                      <Icon size={16} strokeWidth={2} />
                    </span>
                    <span className="timeline-copy">
                      <strong>{entry.label}</strong>
                      <span>
                        <CcBadge tone={statusToneFor(entry.status)}>{entry.friendly_status}</CcBadge>
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
      </CcPage>
    </PlatformShell>
  );
}
