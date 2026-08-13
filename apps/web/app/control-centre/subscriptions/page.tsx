"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import type { SubscriptionListResponse, SubscriptionSummary } from "@/components/platform-types";
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

const PAGE_SIZE = 25;

export default function SubscriptionsPage() {
  const [summary, setSummary] = useState<SubscriptionSummary | null>(null);
  const [listing, setListing] = useState<SubscriptionListResponse | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [effective, setEffective] = useState("");
  const [provider, setProvider] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setError("");
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (q.trim()) params.set("q", q.trim());
    if (effective) params.set("effective", effective);
    if (provider) params.set("provider", provider);
    if (statusFilter) params.set("status", statusFilter);
    try {
      const [summaryResult, listResult] = await Promise.all([
        platformApi.get<SubscriptionSummary>("/subscriptions/summary"),
        platformApi.get<SubscriptionListResponse>(`/subscriptions?${params.toString()}`),
      ]);
      setSummary(summaryResult);
      setListing(listResult);
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

  const totalPages = listing ? Math.max(1, Math.ceil(listing.total / listing.page_size)) : 1;

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Commercial state</p>
            <h1>Subscriptions</h1>
          </div>
          <button className="secondary" onClick={() => void load()}>
            Refresh
          </button>
        </div>
        <p className="scope-note">
          Every Home&rsquo;s stored commercial state and its currently resolved (effective) plan —
          these can differ, for example once complimentary access expires. Stripe integration is
          not part of this phase; the only administrator actions here are granting and revoking
          complimentary Family access.
        </p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {!summary ? (
          <p role="status">Loading summary…</p>
        ) : (
          <div className="overview-grid">
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

        <section className="action-panel">
          <h2>Search and filter</h2>
          <form onSubmit={applyFilters}>
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
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
              >
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
        </section>

        {!listing ? (
          <p role="status">Loading subscriptions…</p>
        ) : listing.items.length === 0 ? (
          <p className="quiet-state">No Homes match these filters.</p>
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Home</th>
                    <th>Effective plan</th>
                    <th>Stored plan</th>
                    <th>Provider</th>
                    <th>Status</th>
                    <th>Complimentary expiry</th>
                    <th>Members</th>
                    <th>Last commercial change</th>
                  </tr>
                </thead>
                <tbody>
                  {listing.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link href={`/subscriptions/${item.id}`}>{item.name}</Link>
                      </td>
                      <td>
                        <strong className={`state-label ${planBadgeClass(item.effective_plan)}`}>
                          {planLabel(item.effective_plan)}
                        </strong>
                        {hasEffectiveDivergence(item.stored_plan, item.effective_plan) && (
                          <div>
                            <small>{item.effective_status_reason}</small>
                          </div>
                        )}
                      </td>
                      <td>{planLabel(item.stored_plan)}</td>
                      <td>
                        <strong className={`state-label ${providerBadgeClass(item.provider)}`}>
                          {providerLabel(item.provider)}
                        </strong>
                      </td>
                      <td>
                        <strong className={`state-label ${statusBadgeClass(item.status)}`}>
                          {statusLabel(item.status)}
                        </strong>
                      </td>
                      <td>
                        {item.complimentary_expires_at ? (
                          <span>
                            {readableDate(item.complimentary_expires_at)}
                            {isExpired(item.complimentary_expires_at) && " (expired)"}
                            {isExpiringSoon(item.complimentary_expires_at) && " (expiring soon)"}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{item.member_count}</td>
                      <td>
                        {item.last_commercial_change
                          ? readableDate(item.last_commercial_change)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
          </>
        )}
      </main>
    </PlatformShell>
  );
}
