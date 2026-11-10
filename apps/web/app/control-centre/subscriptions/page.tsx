"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import type {
  StripeWebhookHealth,
  StripeWebhookIpSecurity,
  SubscriptionListResponse,
  SubscriptionSummary,
} from "@/components/platform-types";
import {
  hasEffectiveDivergence,
  isExpired,
  isExpiringSoon,
  planBadgeClass,
  planLabel,
  providerBadgeClass,
  providerLabel,
  statusBadgeClass,
  statusLabel,
} from "@/components/subscriptions-logic";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge, toneFromStateClass } from "@/components/control-centre/badge";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcSection } from "@/components/control-centre/section";

const PAGE_SIZE = 25;

export default function SubscriptionsPage() {
  const [summary, setSummary] = useState<SubscriptionSummary | null>(null);
  const [webhookHealth, setWebhookHealth] = useState<StripeWebhookHealth | null>(null);
  const [webhookSecurity, setWebhookSecurity] = useState<StripeWebhookIpSecurity | null>(null);
  const [listing, setListing] = useState<SubscriptionListResponse | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [effective, setEffective] = useState("");
  const [provider, setProvider] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [securityBusy, setSecurityBusy] = useState(false);
  const [securityMessage, setSecurityMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (q.trim()) params.set("q", q.trim());
    if (effective) params.set("effective", effective);
    if (provider) params.set("provider", provider);
    if (statusFilter) params.set("status", statusFilter);
    try {
      const [summaryResult, listResult, webhookResult, securityResult] = await Promise.all([
        platformApi.get<SubscriptionSummary>("/subscriptions/summary"),
        platformApi.get<SubscriptionListResponse>(`/subscriptions?${params.toString()}`),
        platformApi.get<StripeWebhookHealth>("/subscriptions/webhook-health"),
        platformApi.get<StripeWebhookIpSecurity>("/subscriptions/webhook-security"),
      ]);
      setSummary(summaryResult);
      setListing(listResult);
      setWebhookHealth(webhookResult);
      setWebhookSecurity(securityResult);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load subscriptions.");
    }
  }, [page, q, effective, provider, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  function applyFilters(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    void load();
  }

  async function updateWebhookSecurity(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!webhookSecurity || securityBusy) return;
    setSecurityBusy(true);
    setError("");
    setSecurityMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.patch<StripeWebhookIpSecurity>("/subscriptions/webhook-security", {
        mode: form.get("webhook_security_mode"),
        reason: form.get("webhook_security_reason"),
        confirmed: true,
      });
      setWebhookSecurity(result);
      setSecurityMessage("Stripe webhook IP security settings saved.");
      event.currentTarget.reset();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save webhook security settings.");
    } finally {
      setSecurityBusy(false);
    }
  }

  async function refreshWebhookSecurity() {
    if (securityBusy) return;
    setSecurityBusy(true);
    setError("");
    setSecurityMessage("");
    try {
      const result = await platformApi.post<StripeWebhookIpSecurity>("/subscriptions/webhook-security/refresh", {
        reason: "Manual Stripe webhook IP feed refresh from PCC.",
        confirmed: true,
      });
      setWebhookSecurity(result);
      setSecurityMessage("Stripe webhook IP feed refreshed successfully.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not refresh the Stripe webhook IP feed.");
    } finally {
      setSecurityBusy(false);
    }
  }

  const totalPages = listing ? Math.max(1, Math.ceil(listing.total / listing.page_size)) : 1;

  const columns: CcTableColumn<SubscriptionListResponse["items"][number]>[] = [
    {
      key: "home",
      header: "Home",
      render: (item) => <Link href={`/subscriptions/${item.id}`}>{item.name}</Link>,
    },
    {
      key: "effective",
      header: "Effective plan",
      render: (item) => (
        <>
          <CcBadge tone={toneFromStateClass(planBadgeClass(item.effective_plan))}>
            {planLabel(item.effective_plan)}
          </CcBadge>
          {hasEffectiveDivergence(item.stored_plan, item.effective_plan) && (
            <div>
              <small>{item.effective_status_reason}</small>
            </div>
          )}
        </>
      ),
    },
    { key: "stored", header: "Stored plan", render: (item) => planLabel(item.stored_plan) },
    {
      key: "provider",
      header: "Provider",
      render: (item) => (
        <CcBadge tone={toneFromStateClass(providerBadgeClass(item.provider))}>
          {providerLabel(item.provider)}
        </CcBadge>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (item) => (
        <CcBadge tone={toneFromStateClass(statusBadgeClass(item.status))}>
          {statusLabel(item.status)}
        </CcBadge>
      ),
    },
    {
      key: "expiry",
      header: "Complimentary expiry",
      render: (item) =>
        item.complimentary_expires_at ? (
          <span>
            {readableDate(item.complimentary_expires_at)}
            {isExpired(item.complimentary_expires_at) && " (expired)"}
            {isExpiringSoon(item.complimentary_expires_at) && " (expiring soon)"}
          </span>
        ) : (
          "—"
        ),
    },
    { key: "members", header: "Members", render: (item) => item.member_count },
    {
      key: "change",
      header: "Last commercial change",
      render: (item) => (item.last_commercial_change ? readableDate(item.last_commercial_change) : "—"),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Commercial state"
          title="Subscriptions"
          description="Every Home's stored commercial state and its currently resolved (effective) plan — these can differ, for example once complimentary access expires. Stripe integration is configured on the Payments page; the administrator actions here are granting and revoking complimentary Family access."
          secondaryActions={
            <button className="secondary" onClick={() => void load()}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}

        {!summary ? (
          <p role="status">Loading summary…</p>
        ) : (
          <div className="overview-grid compact-metrics">
            <section className="overview-panel">
              <h2>Total Homes</h2>
              <p className="stat-number">{summary.total_homes}</p>
            </section>
            <section className="overview-panel">
              <h2>Free</h2>
              <p className="stat-number">{summary.free}</p>
              <small>Effective plan</small>
            </section>
            <section className="overview-panel">
              <h2>Family</h2>
              <p className="stat-number">{summary.family}</p>
              <small>Effective plan</small>
            </section>
            <section className="overview-panel">
              <h2>Complimentary</h2>
              <p className="stat-number">{summary.complimentary}</p>
              <small>Provider, regardless of expiry</small>
            </section>
            <section className="overview-panel">
              <h2>Expired complimentary</h2>
              <p className="stat-number">{summary.complimentary_expired}</p>
              <small>Now effectively Free</small>
            </section>
            <section className="overview-panel">
              <h2>Past due</h2>
              <p className="stat-number">{summary.past_due}</p>
            </section>
            <section className="overview-panel">
              <h2>Cancelled</h2>
              <p className="stat-number">{summary.cancelled}</p>
            </section>
            <section className="overview-panel">
              <h2>Paid Stripe Homes</h2>
              <p className="stat-number">{summary.stripe_total}</p>
              <small>Ever linked to Stripe, any status</small>
            </section>
            <section className="overview-panel">
              <h2>Active paid Family</h2>
              <p className="stat-number">{summary.stripe_active_family}</p>
            </section>
            <section className="overview-panel">
              <h2>Monthly subscribers</h2>
              <p className="stat-number">{summary.stripe_monthly}</p>
            </section>
            <section className="overview-panel">
              <h2>Annual subscribers</h2>
              <p className="stat-number">{summary.stripe_annual}</p>
            </section>
            <section className="overview-panel">
              <h2>Cancelling</h2>
              <p className="stat-number">{summary.stripe_cancelling}</p>
              <small>Cancels at period end</small>
            </section>
          </div>
        )}

        {webhookHealth && (
          <CcSection
            title="Stripe"
            actions={
              <Link href="/payments" className="secondary">
                Manage Stripe settings
              </Link>
            }
          >
            <dl className="overview-grid compact-metrics">
              <div>
                <dt>Mode</dt>
                <dd>
                  <CcBadge tone={webhookHealth.mode === "live" ? "danger" : "info"}>
                    {webhookHealth.mode === "live" ? "Live" : "Test"}
                  </CcBadge>
                </dd>
              </div>
              <div>
                <dt>Configuration source</dt>
                <dd>{webhookHealth.source}</dd>
              </div>
              <div>
                <dt>Webhooks</dt>
                <dd>
                  <CcBadge tone={toneFromStateClass(`state-${webhookHealth.state}`)}>
                    {webhookHealth.configured ? webhookHealth.state : "not configured"}
                  </CcBadge>
                </dd>
              </div>
              <div>
                <dt>Last webhook</dt>
                <dd>
                  {webhookHealth.last_event_at ? readableDate(webhookHealth.last_event_at) : "None received"}
                </dd>
              </div>
              <div>
                <dt>Paid Homes</dt>
                <dd>{webhookHealth.paid_homes}</dd>
              </div>
            </dl>
          </CcSection>
        )}

        {webhookSecurity && (
          <CcSection title="Stripe Webhook Security" actions={<button type="button" className="secondary" onClick={() => void refreshWebhookSecurity()} disabled={securityBusy}>Refresh IP feed</button>}>
            {securityMessage && <CcNotice tone="success">{securityMessage}</CcNotice>}
            {(webhookSecurity.last_sync_error || webhookSecurity.stale || webhookSecurity.blocked_requests_24h >= 3 || !webhookSecurity.proxy_trust_configured || (webhookSecurity.mode === "enforcement" && !webhookSecurity.last_successful_sync_at)) && (
              <CcNotice tone="warning">
                {webhookSecurity.last_sync_error ?? (webhookSecurity.stale ? "The Stripe IP list is stale; refresh it before enabling enforcement." : (webhookSecurity.blocked_requests_24h >= 3 ? "Repeated webhook requests were blocked in the last 24 hours; review proxy trust and Stripe delivery logs." : (!webhookSecurity.proxy_trust_configured ? "Trusted proxy CIDRs are not configured; enforcement is not safe." : "The Stripe IP list has not completed a successful sync." )))}
              </CcNotice>
            )}
            <dl className="overview-grid compact-metrics">
              <div><dt>Mode</dt><dd><CcBadge tone={webhookSecurity.mode === "enforcement" ? "danger" : "info"}>{webhookSecurity.mode === "enforcement" ? "Enforcement" : "Monitoring only"}</CcBadge></dd></div>
              <div><dt>Trusted IPs</dt><dd>{webhookSecurity.trusted_ips.length}</dd></div>
              <div><dt>Last successful update</dt><dd>{webhookSecurity.last_successful_sync_at ? readableDate(webhookSecurity.last_successful_sync_at) : "Never"}</dd></div>
              <div><dt>Blocked requests</dt><dd>{webhookSecurity.blocked_request_count} total / {webhookSecurity.blocked_requests_24h} in 24h</dd></div>
            </dl>
            <p><small>{webhookSecurity.source_ip_method}. Stripe signature verification remains mandatory after the IP policy.</small></p>
            <details>
              <summary>View trusted Stripe webhook IPs</summary>
              <p>{webhookSecurity.trusted_ips.length ? webhookSecurity.trusted_ips.join(", ") : "No last-known-good IP list is available."}</p>
            </details>
            <form onSubmit={updateWebhookSecurity} className="cc-toolbar">
              <label>
                Policy mode
                <select name="webhook_security_mode" defaultValue={webhookSecurity.mode}>
                  <option value="monitoring">Monitoring only</option>
                  <option value="enforcement">Enforcement</option>
                </select>
              </label>
              <label>
                Reason for change
                <input name="webhook_security_reason" minLength={10} maxLength={500} required />
              </label>
              <button type="submit" disabled={securityBusy}>{securityBusy ? "Saving…" : "Save mode"}</button>
            </form>
          </CcSection>
        )}

        <CcSection title="Search and filter">
          <form onSubmit={applyFilters} className="cc-toolbar">
            <label>
              Home name
              <input
                type="text"
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="Search by Home name…"
                maxLength={100}
              />
            </label>
            <label>
              Effective plan
              <select value={effective} onChange={(event) => setEffective(event.target.value)}>
                <option value="">Any</option>
                <option value="free">Free</option>
                <option value="family">Family</option>
              </select>
            </label>
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                <option value="">Any</option>
                <option value="free">Free</option>
                <option value="complimentary">Complimentary</option>
                <option value="stripe">Stripe</option>
              </select>
            </label>
            <label>
              Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">Any</option>
                <option value="active">Active</option>
                <option value="trialing">Trialing</option>
                <option value="past_due">Past due</option>
                <option value="cancel_at_period_end">Cancels at period end</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
            <button type="submit">Apply filters</button>
          </form>
        </CcSection>

        <CcTable
          columns={columns}
          rows={listing?.items ?? null}
          rowKey={(item) => item.id}
          emptyMessage="No Homes match these filters."
          caption="Subscriptions"
        />
        {listing && listing.items.length > 0 && (
          <div className="platform-modal-actions">
            <button
              type="button"
              className="secondary"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </button>
            <span>
              Page {listing.page} of {totalPages} ({listing.total} Homes)
            </span>
            <button
              type="button"
              className="secondary"
              disabled={page >= totalPages}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            >
              Next
            </button>
          </div>
        )}
      </CcPage>
    </PlatformShell>
  );
}
