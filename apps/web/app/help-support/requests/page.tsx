"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type SupportTicketSummaryResponse } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { relativeTimeFromNow, ticketStatusConsumerTone, ticketStatusLabel } from "@/components/support-logic";

type ListState = {
  tickets: SupportTicketSummaryResponse[] | null;
  error: string | null;
};

function useMySupportRequests(): ListState {
  const [state, setState] = useState<ListState>({ tickets: null, error: null });

  useEffect(() => {
    api
      .listSupportTickets()
      .then((response) => setState({ tickets: response.items, error: null }))
      .catch((cause) =>
        setState({
          tickets: null,
          error:
            cause instanceof ApiError
              ? cause.message
              : "Support requests are temporarily unavailable. Please try again later.",
        }),
      );
  }, []);

  return state;
}

export default function MySupportRequests() {
  const { tickets, error } = useMySupportRequests();

  return (
    <SettingsPage
      title="My support requests"
      description="View your open and previous conversations with the MyKhaya support team."
      backLink={{ href: "/help-support", label: "Help & Support" }}
    >
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : tickets === null ? (
        <p role="status">Loading…</p>
      ) : tickets.length === 0 ? (
        <section className="card details" aria-live="polite">
          <h2>No support requests yet.</h2>
          <p className="muted">If you need help, you can report a bug or contact support.</p>
          <div className="support-requests-empty-actions">
            <Link className="button" href="/help-support/report-bug">
              Report a bug
            </Link>
            <Link className="secondary" href="/help-support/contact-support">
              Contact support
            </Link>
          </div>
        </section>
      ) : (
        <div className="card-stack">
          {tickets.map((ticket) => (
            <Link className="card support-request-card" href={`/help-support/requests/${ticket.id}`} key={ticket.id}>
              <div>
                <p className="support-request-reference">{ticket.reference}</p>
                <h2>{ticket.subject}</h2>
                <p
                  className={`support-status-pill support-status-${ticketStatusConsumerTone(ticket.status)}`}
                >
                  {ticketStatusLabel(ticket.status)}
                </p>
                <p className="muted support-request-updated">
                  Updated {relativeTimeFromNow(ticket.updated_at)}
                </p>
              </div>
              <span aria-hidden="true">›</span>
            </Link>
          ))}
        </div>
      )}
    </SettingsPage>
  );
}
