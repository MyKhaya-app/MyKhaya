"use client";

import { FormEvent, use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard, CcColumns } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcEmptyState } from "@/components/control-centre/status-message";
import {
  TICKET_PRIORITY_OPTIONS,
  TICKET_STATUS_OPTIONS,
  ticketAppAreaLabel,
  ticketPriorityLabel,
  ticketPriorityTone,
  ticketSourceLabel,
  ticketStatusLabel,
  ticketStatusTone,
  ticketTypeLabel,
} from "@/components/support-logic";

type TicketMessage = {
  id: string;
  author_user_id: string | null;
  author_admin_id: string | null;
  author_display_name: string;
  message: string;
  visibility: "requester" | "internal";
  created_at: string;
};

type TicketAttachment = {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
};

type TicketDiagnostics = {
  app_version: string | null;
  build_number: string | null;
  platform: string | null;
  os_version: string | null;
  runtime: string | null;
  notification_permission: string | null;
  push_registration_state: string | null;
  api_connectivity: string | null;
  network_state: string | null;
  background_refresh_state: string | null;
  client_timestamp: string | null;
};

type TicketDetail = {
  id: string;
  reference: string;
  type: string;
  status: string;
  priority: string;
  subject: string;
  description: string;
  source: string;
  app_area: string | null;
  requester_user_id: string;
  requester_display_name: string;
  requester_email: string;
  group_id: string | null;
  group_name: string | null;
  assigned_admin_id: string | null;
  assigned_admin_display_name: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  messages: TicketMessage[];
  attachments: TicketAttachment[];
  diagnostics: TicketDiagnostics | null;
};

type AdministratorOption = { id: string; display_name: string };

const DIAGNOSTIC_FIELDS: { key: keyof TicketDiagnostics; label: string }[] = [
  { key: "app_version", label: "App version" },
  { key: "build_number", label: "Build" },
  { key: "platform", label: "Platform" },
  { key: "os_version", label: "OS" },
  { key: "runtime", label: "Runtime" },
  { key: "notification_permission", label: "Notification permission" },
  { key: "push_registration_state", label: "Push registration" },
  { key: "api_connectivity", label: "API connectivity" },
  { key: "network_state", label: "Network state" },
  { key: "background_refresh_state", label: "Background refresh" },
];

function attachmentUrl(ticketId: string, attachmentId: string): string {
  return `/api/v1/platform/support/tickets/${encodeURIComponent(ticketId)}/attachments/${encodeURIComponent(attachmentId)}`;
}

function isPreviewable(contentType: string): boolean {
  return contentType.startsWith("image/");
}

export default function SupportTicketDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<TicketDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [administrators, setAdministrators] = useState<AdministratorOption[]>([]);
  const [replyText, setReplyText] = useState("");
  const [replySubmitting, setReplySubmitting] = useState(false);
  const [savingField, setSavingField] = useState<"status" | "priority" | "assigned" | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<TicketDetail>(`/support/tickets/${encodeURIComponent(id)}`));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load this ticket.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Owner-only endpoint (see routers.platform.administrators) — a
    // support_operator/administrator viewer simply won't get options here
    // (the dropdown degrades to "Unassigned" only), not an error the page
    // needs to surface.
    platformApi
      .get<AdministratorOption[]>("/administrators")
      .then(setAdministrators)
      .catch(() => setAdministrators([]));
  }, []);

  async function updateTicket(body: Record<string, unknown>, field: "status" | "priority" | "assigned") {
    setSavingField(field);
    setError("");
    try {
      const updated = await platformApi.patch<TicketDetail>(
        `/support/tickets/${encodeURIComponent(id)}`,
        body,
      );
      setData(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not update this ticket.");
    } finally {
      setSavingField(null);
    }
  }

  async function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = replyText.trim();
    if (!trimmed) return;
    setReplySubmitting(true);
    setError("");
    try {
      await platformApi.post(`/support/tickets/${encodeURIComponent(id)}/messages`, {
        message: trimmed,
      });
      setReplyText("");
      setMessage("Reply added to the ticket.");
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add this reply.");
    } finally {
      setReplySubmitting(false);
    }
  }

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Support"
          title={data ? data.reference : "Ticket"}
          description={data?.subject}
          secondaryActions={
            <>
              <Link href="/support/tickets" className="secondary">
                Back to Tickets
              </Link>
              <button className="secondary" onClick={() => void load()}>
                Refresh
              </button>
            </>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}
        {!data && !error && <p role="status">Loading…</p>}
        {data && (
          <CcColumns ratio="2-1">
            <div>
              <CcSection title="Description">
                <CcCard>
                  <p className="cc-text-wrap">{data.description}</p>
                </CcCard>
              </CcSection>

              <CcSection title="Conversation">
                <CcCard>
                  {data.messages.length === 0 ? (
                    <CcEmptyState>No messages yet.</CcEmptyState>
                  ) : (
                    <div className="record-list cc-conversation">
                      {data.messages.map((entry) => (
                        <article key={entry.id}>
                          <strong>
                            {entry.author_display_name}
                            {entry.author_admin_id && " (MyKhaya team)"}
                          </strong>
                          <time dateTime={entry.created_at}>{readableDate(entry.created_at)}</time>
                          <p className="cc-text-wrap">{entry.message}</p>
                        </article>
                      ))}
                    </div>
                  )}
                  <form className="cc-support-reply-form" onSubmit={submitReply}>
                    <label>
                      Add a reply
                      <textarea
                        value={replyText}
                        onChange={(event) => setReplyText(event.target.value)}
                        rows={4}
                        maxLength={4000}
                        placeholder="Reply to the requester…"
                      />
                    </label>
                    <p className="cc-page-meta">
                      This reply will be saved to the ticket and emailed to the requester.
                      Email delivery will be enabled in a later phase.
                    </p>
                    <button
                      type="submit"
                      className="cc-action cc-action-primary"
                      disabled={replySubmitting || !replyText.trim()}
                    >
                      {replySubmitting ? "Sending…" : "Add reply"}
                    </button>
                  </form>
                </CcCard>
              </CcSection>

              <CcSection title="Attachments">
                <CcCard>
                  {data.attachments.length === 0 ? (
                    <CcEmptyState>No attachments.</CcEmptyState>
                  ) : (
                    <div className="cc-attachment-grid">
                      {data.attachments.map((attachment) => (
                        <a
                          key={attachment.id}
                          className="cc-attachment-tile"
                          href={attachmentUrl(data.id, attachment.id)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {isPreviewable(attachment.content_type) ? (
                            <img
                              src={attachmentUrl(data.id, attachment.id)}
                              alt={attachment.original_filename}
                              loading="lazy"
                              onError={(event) => {
                                event.currentTarget.style.display = "none";
                              }}
                            />
                          ) : (
                            <span className="cc-attachment-fallback">File</span>
                          )}
                          <span className="cc-attachment-name" title={attachment.original_filename}>
                            {attachment.original_filename}
                          </span>
                        </a>
                      ))}
                    </div>
                  )}
                </CcCard>
              </CcSection>

              {data.diagnostics && (
                <CcSection title="Diagnostics">
                  <CcCard>
                    <CcMetadataGrid dense>
                      {DIAGNOSTIC_FIELDS.map(({ key, label }) => (
                        <CcMetadataItem key={key} label={label}>
                          {data.diagnostics![key] ?? "—"}
                        </CcMetadataItem>
                      ))}
                      <CcMetadataItem label="Captured at">
                        {readableDate(data.diagnostics.client_timestamp)}
                      </CcMetadataItem>
                    </CcMetadataGrid>
                  </CcCard>
                </CcSection>
              )}
            </div>

            <div>
              <CcSection title="Ticket details">
                <CcCard>
                  <CcMetadataGrid dense>
                    <CcMetadataItem label="Status">
                      <select
                        value={data.status}
                        disabled={savingField === "status"}
                        onChange={(event) => updateTicket({ status: event.target.value }, "status")}
                      >
                        {TICKET_STATUS_OPTIONS.map((value) => (
                          <option key={value} value={value}>
                            {ticketStatusLabel(value)}
                          </option>
                        ))}
                      </select>
                      <div style={{ marginTop: "0.4rem" }}>
                        <CcBadge tone={ticketStatusTone(data.status)}>
                          {ticketStatusLabel(data.status)}
                        </CcBadge>
                      </div>
                    </CcMetadataItem>
                    <CcMetadataItem label="Priority">
                      <select
                        value={data.priority}
                        disabled={savingField === "priority"}
                        onChange={(event) => updateTicket({ priority: event.target.value }, "priority")}
                      >
                        {TICKET_PRIORITY_OPTIONS.map((value) => (
                          <option key={value} value={value}>
                            {ticketPriorityLabel(value)}
                          </option>
                        ))}
                      </select>
                      <div style={{ marginTop: "0.4rem" }}>
                        <CcBadge tone={ticketPriorityTone(data.priority)}>
                          {ticketPriorityLabel(data.priority)}
                        </CcBadge>
                      </div>
                    </CcMetadataItem>
                    <CcMetadataItem label="Type">{ticketTypeLabel(data.type)}</CcMetadataItem>
                    <CcMetadataItem label="Requester">
                      <span title={data.requester_email}>{data.requester_display_name}</span>
                    </CcMetadataItem>
                    <CcMetadataItem label="Home">{data.group_name ?? "—"}</CcMetadataItem>
                    <CcMetadataItem label="App area">{ticketAppAreaLabel(data.app_area)}</CcMetadataItem>
                    <CcMetadataItem label="Source">{ticketSourceLabel(data.source)}</CcMetadataItem>
                    <CcMetadataItem label="Assigned admin">
                      <select
                        value={data.assigned_admin_id ?? ""}
                        disabled={savingField === "assigned"}
                        onChange={(event) =>
                          updateTicket(
                            { assigned_admin_id: event.target.value || null },
                            "assigned",
                          )
                        }
                      >
                        <option value="">Unassigned</option>
                        {administrators.map((admin) => (
                          <option key={admin.id} value={admin.id}>
                            {admin.display_name}
                          </option>
                        ))}
                        {data.assigned_admin_id &&
                          !administrators.some((admin) => admin.id === data.assigned_admin_id) && (
                            <option value={data.assigned_admin_id}>
                              {data.assigned_admin_display_name ?? "Current assignee"}
                            </option>
                          )}
                      </select>
                    </CcMetadataItem>
                    <CcMetadataItem label="Created">{readableDate(data.created_at)}</CcMetadataItem>
                    <CcMetadataItem label="Updated">{readableDate(data.updated_at)}</CcMetadataItem>
                    {data.resolved_at && (
                      <CcMetadataItem label="Resolved">{readableDate(data.resolved_at)}</CcMetadataItem>
                    )}
                  </CcMetadataGrid>
                </CcCard>
              </CcSection>
            </div>
          </CcColumns>
        )}
      </CcPage>
    </PlatformShell>
  );
}
