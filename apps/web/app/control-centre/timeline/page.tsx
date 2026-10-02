"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcEmptyState, CcLoadingState } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcToggle } from "@/components/control-centre/toggle";

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

function statusToneFor(status: string): CcBadgeTone {
  return statusTone[status] ?? "warning";
}

function timeOf(value: string) {
  return new Intl.DateTimeFormat("en-GB", { timeStyle: "short" }).format(new Date(value));
}

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function TimelinePage() {
  const [items, setItems] = useState<TimelineEntry[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

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

  useEffect(() => {
    if (!live) return;
    const interval = window.setInterval(() => void load(1, false), 15_000);
    return () => window.clearInterval(interval);
  }, [live, load]);

  const filteredItems = items.filter((entry) => {
    const haystack = `${entry.label} ${entry.notification_type} ${entry.channel} ${entry.recipient_display_name ?? ""}`.toLowerCase();
    return (!search.trim() || haystack.includes(search.trim().toLowerCase())) &&
      (typeFilter === "all" || entry.notification_type === typeFilter) &&
      (statusFilter === "all" || entry.status === statusFilter);
  });
  const timelineColumns: CcTableColumn<TimelineEntry>[] = [
    { key: "time", header: "Time", render: (entry) => <time dateTime={entry.occurred_at}>{timeOf(entry.occurred_at)}</time> },
    { key: "event", header: "Event", render: (entry) => <strong>{entry.label}</strong> },
    { key: "status", header: "Status", render: (entry) => <CcBadge tone={statusToneFor(entry.status)}>{entry.friendly_status}</CcBadge> },
    { key: "user-home", header: "User / Home", render: (entry) => entry.recipient_display_name ?? "System" },
    { key: "source", header: "Source / Module", render: (entry) => `${entry.channel} · ${entry.notification_type}` },
    { key: "actions", header: "Actions", render: () => "—" },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Communications"
          title="Timeline"
          description={`What actually happened, told chronologically — for "why", see Diagnostics.`}
          secondaryActions={
            <div className="cc-action-bar">
              <CcToggle label={live ? "Live" : "Paused"} name="timeline-live" defaultChecked={live} onChange={(event) => setLive(event.target.checked)} />
              <button className="secondary" onClick={() => void load(1, false)}>
                Refresh
              </button>
            </div>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {loading && items.length === 0 ? (
          <CcLoadingState label="Loading timeline…" />
        ) : items.length === 0 ? (
          <CcEmptyState>Nothing has been sent yet.</CcEmptyState>
        ) : (
          <>
            <div className="cc-toolbar">
              <input aria-label="Search timeline" placeholder="Search event, user or module" value={search} onChange={(event) => setSearch(event.target.value)} />
              <select aria-label="Timeline type filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                <option value="all">All types</option>
                {Array.from(new Set(items.map((entry) => entry.notification_type))).map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
              <select aria-label="Timeline status filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All statuses</option>
                {Array.from(new Set(items.map((entry) => entry.status))).map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </div>
            <CcTable columns={timelineColumns} rows={filteredItems} rowKey={(entry) => entry.id} emptyMessage="No timeline events match these filters." caption="Communications timeline" />
          </>
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
