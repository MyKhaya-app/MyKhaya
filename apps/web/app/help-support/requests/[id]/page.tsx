"use client";

import { FormEvent, use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type SupportTicketResponse } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import {
  isActiveTicketStatus,
  ticketStatusConsumerTone,
  ticketStatusLabel,
} from "@/components/support-logic";

function readableDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export default function SupportRequestDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [ticket, setTicket] = useState<SupportTicketResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [replyError, setReplyError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .getSupportTicket(id)
      .then(setTicket)
      .catch((cause) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : "Support requests are temporarily unavailable. Please try again later.",
        ),
      );
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = reply.trim();
    if (!trimmed || sending || !ticket) return;
    setSending(true);
    setReplyError(null);
    try {
      await api.addSupportTicketMessage(ticket.id, { message: trimmed });
      setReply("");
      load();
    } catch (cause) {
      // The typed text is deliberately preserved on failure — nothing the
      // requester wrote is ever silently lost.
      setReplyError(
        cause instanceof ApiError ? cause.message : "Couldn’t send your reply. Please try again.",
      );
    } finally {
      setSending(false);
    }
  }

  if (error) {
    return (
      <SettingsPage title="Support request" description="View your conversation with the MyKhaya support team." backLink={{ href: "/help-support", label: "Help & Support" }}>
        <p className="notice error" role="alert">
          {error}
        </p>
      </SettingsPage>
    );
  }

  if (!ticket) {
    return (
      <SettingsPage title="Support request" description="View your conversation with the MyKhaya support team." backLink={{ href: "/help-support", label: "Help & Support" }}>
        <p role="status">Loading…</p>
      </SettingsPage>
    );
  }

  const active = isActiveTicketStatus(ticket.status);

  return (
    <SettingsPage title={ticket.reference} description={ticket.subject} backLink={{ href: "/help-support/requests", label: "My support requests" }}>
      <div className="card-stack">
        <section className="card details">
          <p
            className={`support-status-pill support-status-${ticketStatusConsumerTone(ticket.status)}`}
          >
            {ticketStatusLabel(ticket.status)}
          </p>
          <p className="muted support-request-created">Created {readableDate(ticket.created_at)}</p>
          <h2>Original request</h2>
          <p className="text-wrap-anywhere">{ticket.description}</p>
        </section>

        <section className="card details">
          <h2>Conversation</h2>
          {ticket.messages.length === 0 ? (
            <p className="quiet-state">No replies yet.</p>
          ) : (
            <div className="support-conversation">
              {ticket.messages.map((message) => (
                <article className="support-message" key={message.id}>
                  <strong>{message.author === "admin" ? "MyKhaya Support" : "You"}</strong>
                  <time dateTime={message.created_at}>{readableDate(message.created_at)}</time>
                  <p className="text-wrap-anywhere">{message.message}</p>
                </article>
              ))}
            </div>
          )}

          {active ? (
            <form className="support-reply-form" onSubmit={submitReply}>
              {replyError && (
                <p className="notice error" role="alert">
                  {replyError}
                </p>
              )}
              <label>
                Add a reply
                <textarea
                  value={reply}
                  onChange={(event) => setReply(event.target.value)}
                  maxLength={4000}
                  rows={4}
                />
              </label>
              <button className="button" type="submit" disabled={sending || !reply.trim()}>
                {sending ? "Sending…" : "Send reply"}
              </button>
            </form>
          ) : (
            <section className="card details support-conversation-closed" aria-live="polite">
              <p className="muted">
                {ticket.status === "resolved"
                  ? "This request has been resolved."
                  : "This conversation is closed."}
              </p>
              <Link className="button" href="/help-support/contact-support">
                Contact support again
              </Link>
            </section>
          )}
        </section>
      </div>
    </SettingsPage>
  );
}
