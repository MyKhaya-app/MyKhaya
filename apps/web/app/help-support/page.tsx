"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Bug, ExternalLink, FileText, LifeBuoy, MessageCircle } from "lucide-react";
import { api, type SupportTicketSummaryResponse } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { openExternalUrl } from "@/components/open-external-url";
import type { ServiceState } from "@/components/platform-types";
import {
  relativeTimeFromNow,
  ticketStatusConsumerTone,
  ticketStatusLabel,
} from "@/components/support-logic";
import { hubStatusMessage } from "./help-support-logic";

type StatusSummary = { overall: ServiceState; overall_message: string };

type PublicConfigPayload = {
  service_status_url?: string | null;
  support_enabled?: boolean;
  status_overall?: ServiceState;
  status_overall_message?: string;
};

// Both the "View current platform status" link target and the compact
// status summary below come from the one unauthenticated, non-host-gated
// GET /api/v1/config/public — never mykhaya.routers.status's GET /status,
// which is deliberately host-gated to the dedicated status subdomain
// (enforce_status_host) and unreachable from this app's own origin. The
// summary is the exact same overall-severity computation as the full
// Status page (mykhaya.status_aggregation.overall_public_state), just
// surfaced from somewhere this page can actually call — never internal
// health (DB/SMTP/Stripe/worker), never the full service/incident list.

function useHelpSupportRequests(): SupportTicketSummaryResponse[] | null {
  const [tickets, setTickets] = useState<SupportTicketSummaryResponse[] | null>(null);

  useEffect(() => {
    api.listSupportTickets().then((response) => setTickets(response.items)).catch(() => setTickets([]));
  }, []);

  return tickets;
}

function HelpServiceStatusCard({
  serviceStatusUrl,
  summary,
  failed,
}: {
  serviceStatusUrl: string | null;
  summary: StatusSummary | null;
  failed: boolean;
}) {
  const operational = summary?.overall === "operational";
  return (
    <section className="card help-service-card" aria-live="polite">
      <div className="help-card-heading">
        <h2>Service status</h2>
        <span aria-hidden="true">›</span>
      </div>
      {failed ? (
        <p className="help-service-message">Status information is temporarily unavailable.</p>
      ) : summary ? (
        <p className={`help-status-line help-status-${summary.overall}`}>
          <span className="help-status-dot" aria-hidden="true" />
          {hubStatusMessage(summary.overall, summary.overall_message)}
        </p>
      ) : (
        <p className="help-service-message">Checking…</p>
      )}
      {summary && (
        <p className="help-service-description">
          {operational ? "All MyKhaya services are running normally." : summary.overall_message}
        </p>
      )}
      <div className="help-card-divider" />
      {serviceStatusUrl ? (
        <a
          className="help-status-link"
          href={serviceStatusUrl}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => {
            event.preventDefault();
            void openExternalUrl(serviceStatusUrl);
          }}
        >
          <ExternalLink size={22} aria-hidden="true" />
          <span>View platform status</span>
          <span aria-hidden="true">›</span>
        </a>
      ) : (
        <span className="help-status-link help-status-link-disabled" aria-disabled="true">
          <ExternalLink size={22} aria-hidden="true" />
          <span>Platform status page not available right now</span>
        </span>
      )}
    </section>
  );
}

export default function HelpSupport() {
  const [supportEnabled, setSupportEnabled] = useState<boolean | null>(null);
  const [serviceStatusUrl, setServiceStatusUrl] = useState<string | null>(null);
  const [summary, setSummary] = useState<StatusSummary | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const requests = useHelpSupportRequests();

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("config unavailable");
        return response.json() as Promise<PublicConfigPayload>;
      })
      .then((payload) => {
        setSupportEnabled(payload.support_enabled === true);
        setServiceStatusUrl(payload.service_status_url ?? null);
        if (payload.status_overall && payload.status_overall_message) {
          setSummary({ overall: payload.status_overall, overall_message: payload.status_overall_message });
        } else {
          setStatusFailed(true);
        }
      })
      .catch(() => {
        setSupportEnabled(false);
        setStatusFailed(true);
      });
  }, []);

  const reportBug = supportEnabled === false ? (
    <span className="help-action-tile help-action-disabled" aria-disabled="true">
      <Bug size={24} aria-hidden="true" />
      <strong>Report a bug</strong>
      <span>Temporarily unavailable</span>
    </span>
  ) : (
    <Link className="help-action-tile" href="/help-support/report-bug">
      <Bug size={24} aria-hidden="true" />
      <strong>Report a bug</strong>
      <span>Report an issue</span>
    </Link>
  );

  return (
    <SettingsPage title="Help & Support" description="Get help, report issues, and check your app health." className="help-support-page">
      <div className="help-action-grid">
        {reportBug}
        <Link className="help-action-tile" href="/help-support/contact-support">
          <MessageCircle size={24} aria-hidden="true" />
          <strong>Contact support</strong>
          <span>Get in touch with our team</span>
          <span className="help-action-chevron" aria-hidden="true">›</span>
        </Link>
        <Link className="help-action-tile" href="/help-support/diagnostics">
          <Activity size={24} aria-hidden="true" />
          <strong>Run diagnostics</strong>
          <span>Check your app for issues</span>
          <span className="help-action-chevron" aria-hidden="true">›</span>
        </Link>
      </div>

      <section className="card help-requests-card">
        <div className="help-card-heading">
          <div>
            <h2>My support requests</h2>
            <p>View your open and previous support requests.</p>
          </div>
          <Link href="/help-support/requests" className="help-view-all">View all <span aria-hidden="true">›</span></Link>
        </div>
        {requests === null ? (
          <p role="status" className="help-empty-state">Loading support requests…</p>
        ) : requests.length === 0 ? (
          <p className="help-empty-state">No support requests yet.</p>
        ) : (
          <div className="help-request-preview">
            {requests.slice(0, 3).map((ticket) => (
              <Link className="help-request-row" href={`/help-support/requests/${ticket.id}`} key={ticket.id}>
                <span className="help-request-icon" aria-hidden="true"><FileText size={20} /></span>
                <span className="help-request-copy">
                  <strong>{ticket.subject}</strong>
                  <span>{ticket.reference} · {relativeTimeFromNow(ticket.created_at)}</span>
                </span>
                <span className={`support-status-pill support-status-${ticketStatusConsumerTone(ticket.status)}`}>{ticketStatusLabel(ticket.status)}</span>
                <span aria-hidden="true">›</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <HelpServiceStatusCard serviceStatusUrl={serviceStatusUrl} summary={summary} failed={statusFailed} />

      <section className="card help-contact-card">
        <span className="help-contact-icon" aria-hidden="true"><LifeBuoy size={28} /></span>
        <div>
          <h2>Need more help?</h2>
          <p>If you&apos;re experiencing an urgent issue or need personalised support, get in touch with our team.</p>
        </div>
        <Link className="button help-contact-button" href="/help-support/contact-support">Contact support</Link>
      </section>
    </SettingsPage>
  );
}
