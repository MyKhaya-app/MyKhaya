"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcToolbar } from "@/components/control-centre/toolbar";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import {
  TICKET_APP_AREA_OPTIONS,
  TICKET_PRIORITY_OPTIONS,
  TICKET_SOURCE_OPTIONS,
  TICKET_STATUS_OPTIONS,
  TICKET_TYPE_OPTIONS,
  ticketAppAreaLabel,
  ticketPriorityLabel,
  ticketPriorityTone,
  ticketSourceLabel,
  ticketStatusLabel,
  ticketStatusTone,
  ticketTypeLabel,
} from "@/components/support-logic";

type TicketSummary = {
  id: string;
  reference: string;
  type: string;
  status: string;
  priority: string;
  subject: string;
  source: string;
  app_area: string | null;
  requester_display_name: string;
  requester_email: string;
  group_id: string | null;
  group_name: string | null;
  assigned_admin_id: string | null;
  assigned_admin_display_name: string | null;
  created_at: string;
  updated_at: string;
};

type TicketListResponse = {
  items: TicketSummary[];
  next_page: number | null;
};

type AdministratorOption = { id: string; display_name: string };

// Filters/search live in the URL (query params) rather than only component
// state — a reload or a shared link reproduces the same filtered view, and
// pagination (`page`) is just another param alongside them, so Next/Previous
// never silently drops an active filter.
const FILTER_KEYS = ["status", "type", "priority", "source", "app_area", "assigned_admin_id"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

function TicketsQueue() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [data, setData] = useState<TicketListResponse | null>(null);
  const [error, setError] = useState("");
  const [administrators, setAdministrators] = useState<AdministratorOption[]>([]);
  const [queryInput, setQueryInput] = useState(searchParams.get("query") ?? "");

  const page = Number(searchParams.get("page") ?? "1") || 1;
  const query = searchParams.get("query") ?? "";
  const filters = Object.fromEntries(
    FILTER_KEYS.map((key) => [key, searchParams.get(key) ?? ""]),
  ) as Record<FilterKey, string>;

  const setParams = useCallback(
    (updates: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      router.replace(`/support/tickets?${next.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  useEffect(() => {
    platformApi
      .get<AdministratorOption[]>("/administrators")
      .then(setAdministrators)
      .catch(() => setAdministrators([]));
  }, []);

  const searchParamsKey = searchParams.toString();

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page) });
    if (query.trim()) params.set("query", query.trim());
    for (const key of FILTER_KEYS) {
      if (filters[key]) params.set(key, filters[key]);
    }
    setData(null);
    setError("");
    platformApi
      .get<TicketListResponse>(`/support/tickets?${params.toString()}`)
      .then(setData)
      .catch((cause: Error) =>
        setError(cause instanceof ApiError ? cause.message : "Could not load support tickets."),
      );
    // `searchParamsKey` is the real dependency — it changes exactly when the
    // URL's query string does, which is also when `page`/`query`/`filters`
    // (all derived from it) change. Depending on it directly, rather than on
    // the derived values, avoids re-deriving a stable dependency array by
    // hand.
  }, [searchParamsKey]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setParams({ query: queryInput.trim() || null, page: "1" });
  }

  function setFilter(key: FilterKey, value: string) {
    setParams({ [key]: value || null, page: "1" });
  }

  const hasActiveFilters = Boolean(query || FILTER_KEYS.some((key) => filters[key]));

  function clearFilters() {
    setQueryInput("");
    const cleared: Record<string, string | null> = { query: null, page: "1" };
    for (const key of FILTER_KEYS) cleared[key] = null;
    setParams(cleared);
  }

  const rows = data?.items ?? [];
  const columns: CcTableColumn<TicketSummary>[] = [
    {
      key: "reference",
      header: "Reference",
      render: (row) => (
        <Link className="table-link" href={`/support/tickets/${row.id}`}>
          {row.reference}
        </Link>
      ),
    },
    { key: "type", header: "Type", render: (row) => ticketTypeLabel(row.type) },
    {
      key: "status",
      header: "Status",
      render: (row) => <CcBadge tone={ticketStatusTone(row.status)}>{ticketStatusLabel(row.status)}</CcBadge>,
    },
    {
      key: "priority",
      header: "Priority",
      render: (row) => (
        <CcBadge tone={ticketPriorityTone(row.priority)}>{ticketPriorityLabel(row.priority)}</CcBadge>
      ),
    },
    {
      key: "subject",
      header: "Subject",
      render: (row) => (
        <span className="cc-table-truncate" title={row.subject}>
          {row.subject}
        </span>
      ),
    },
    {
      key: "user",
      header: "User",
      render: (row) => (
        <span className="cc-table-truncate" title={row.requester_email}>
          {row.requester_display_name}
        </span>
      ),
    },
    { key: "home", header: "Home", render: (row) => row.group_name ?? "—" },
    { key: "app_area", header: "App area", render: (row) => ticketAppAreaLabel(row.app_area) },
    { key: "platform", header: "Platform", render: (row) => ticketSourceLabel(row.source) },
    { key: "created", header: "Created", render: (row) => readableDate(row.created_at) },
    {
      key: "assigned",
      header: "Assigned",
      render: (row) => row.assigned_admin_display_name ?? "Unassigned",
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide className="cc-support-tickets-queue">
        <CcPageHeader
          eyebrow="Support"
          title="Tickets"
          description="Bug reports, support requests and feedback submitted through the app."
        />
        <CcToolbar>
          <form className="cc-list-toolbar-form" onSubmit={submitSearch}>
            <label>
              Search
              <input
                value={queryInput}
                onChange={(event) => setQueryInput(event.target.value)}
                placeholder="Reference, subject, requester…"
              />
            </label>
            <label>
              Status
              <select value={filters.status} onChange={(event) => setFilter("status", event.target.value)}>
                <option value="">All</option>
                {TICKET_STATUS_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {ticketStatusLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Type
              <select value={filters.type} onChange={(event) => setFilter("type", event.target.value)}>
                <option value="">All</option>
                {TICKET_TYPE_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {ticketTypeLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Priority
              <select value={filters.priority} onChange={(event) => setFilter("priority", event.target.value)}>
                <option value="">All</option>
                {TICKET_PRIORITY_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {ticketPriorityLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Platform
              <select value={filters.source} onChange={(event) => setFilter("source", event.target.value)}>
                <option value="">All</option>
                {TICKET_SOURCE_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {ticketSourceLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              App area
              <select value={filters.app_area} onChange={(event) => setFilter("app_area", event.target.value)}>
                <option value="">All</option>
                {TICKET_APP_AREA_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {ticketAppAreaLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Assigned to
              <select
                value={filters.assigned_admin_id}
                onChange={(event) => setFilter("assigned_admin_id", event.target.value)}
              >
                <option value="">Anyone</option>
                {administrators.map((admin) => (
                  <option key={admin.id} value={admin.id}>
                    {admin.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="cc-action cc-action-primary">
              Search
            </button>
            {hasActiveFilters && (
              <button type="button" className="secondary" onClick={clearFilters}>
                Clear
              </button>
            )}
          </form>
        </CcToolbar>
        {error && <CcNotice tone="error">Unable to load tickets: {error}</CcNotice>}
        <CcTable
          columns={columns}
          rows={data ? rows : null}
          rowKey={(row) => row.id}
          emptyMessage="No tickets match these filters."
          caption="Support tickets table"
        />
        {data && (page > 1 || data.next_page) && (
          <nav className="cc-pagination" aria-label="Support ticket pages">
            <button
              type="button"
              className="secondary"
              disabled={page <= 1}
              onClick={() => setParams({ page: String(page - 1) })}
            >
              Previous
            </button>
            <span>Page {page}</span>
            <button
              type="button"
              className="secondary"
              disabled={!data.next_page}
              onClick={() => setParams({ page: String(data.next_page) })}
            >
              Next
            </button>
          </nav>
        )}
      </CcPage>
    </PlatformShell>
  );
}

export default function SupportTicketsPage() {
  return (
    <Suspense fallback={null}>
      <TicketsQueue />
    </Suspense>
  );
}
