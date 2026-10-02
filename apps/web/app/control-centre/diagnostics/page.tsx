"use client";

import { FormEvent, useCallback, useState } from "react";
import { Search } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

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

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

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
      setError(safeError(cause, "The diagnostics search failed."));
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

  const columns: CcTableColumn<DiagnosticsEntry>[] = [
    { key: "when", header: "When", render: (row) => readableDate(row.occurred_at) },
    { key: "type", header: "Type", render: (row) => row.label },
    { key: "channel", header: "Channel", render: (row) => titleCase(row.channel) },
    { key: "status", header: "Status", render: (row) => titleCase(row.status) },
    { key: "recipient", header: "Recipient", render: (row) => row.recipient_email ?? "—" },
    { key: "retries", header: "Retries", render: (row) => row.retry_count },
    { key: "failure", header: "Failure reason", render: (row) => row.sanitised_failure_reason ?? "—" },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Communications"
          title="Diagnostics"
          description={`Why did this one fail? Filter by status, channel, type or recipient.`}
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}

        <CcCard title="Search deliveries" icon={Search}>
          <form onSubmit={onSearch}>
            <CcField label="Status">
              <select name="status" defaultValue="">
                <option value="">Any</option>
                <option value="queued">Queued</option>
                <option value="sent">Sent</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </CcField>
            <CcField label="Channel">
              <select name="channel" defaultValue="">
                <option value="">Any</option>
                <option value="email">Email</option>
                <option value="push">Push</option>
                <option value="in_app">In-app</option>
              </select>
            </CcField>
            <CcField label="Notification type">
              <input name="notification_type" placeholder="e.g. event_reminder" />
            </CcField>
            <CcField label="Recipient email">
              <input name="recipient_email" type="email" />
            </CcField>
            <CcActionBar
              actions={[
                {
                  key: "search",
                  label: loading ? "Searching…" : "Search",
                  variant: "primary",
                  type: "submit",
                  disabled: loading,
                },
              ]}
            />
          </form>
        </CcCard>

        <CcCard title="Results">
          <CcTable
            columns={columns}
            rows={searched ? items : []}
            rowKey={(row) => row.id}
            emptyMessage={searched ? "No deliveries match those filters." : "Run a search to see results."}
            caption="Diagnostics results"
          />
        </CcCard>

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
      </CcPage>
    </PlatformShell>
  );
}
