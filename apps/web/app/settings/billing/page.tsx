"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { BillingStatus, FamilyPricing } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import {
  planBadgeClass,
  planLabel,
  providerLabel,
  statusBadgeClass,
  statusLabel,
} from "@/components/subscriptions-logic";
import { checkoutBannerKind, intervalSuffix, periodLabel } from "@/components/billing-logic";

// A minimal test/development surface for Phase 3 — enough to start Checkout,
// open the Customer Portal, and see confirmation state. The polished
// household Plan & Billing experience is a later phase; see
// docs/product/plans-and-pricing.md.
export default function BillingSettings() {
  const { activeHomeId, loading: homeLoading } = useActiveHome();
  const searchParams = useSearchParams();
  const checkoutBanner = checkoutBannerKind(searchParams.get("checkout"));

  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!activeHomeId) return;
    setError("");
    try {
      const billingStatus = await api.billingStatus(activeHomeId);
      setStatus(billingStatus);
      if (billingStatus.stripe_billing_available) {
        setPricing(await api.familyPricing().catch(() => null));
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load billing status.");
    }
  }, [activeHomeId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function startCheckout(interval: "month" | "year") {
    if (!activeHomeId || busy) return;
    setBusy(true);
    setError("");
    try {
      const { checkout_url: checkoutUrl } = await api.createCheckoutSession(
        activeHomeId,
        interval,
      );
      window.location.href = checkoutUrl;
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start checkout.");
      setBusy(false);
    }
  }

  async function openPortal() {
    if (!activeHomeId || busy) return;
    setBusy(true);
    setError("");
    try {
      const { portal_url: portalUrl } = await api.createPortalSession(activeHomeId);
      window.location.href = portalUrl;
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not open the billing portal.");
      setBusy(false);
    }
  }

  return (
    <SettingsPage title="Billing">
      <main className="standard-page">
        {checkoutBanner === "success" && (
          <p className="notice" role="status">
            Payment received. We&rsquo;re confirming your subscription — this usually takes just
            a few seconds. Refresh this page shortly if it doesn&rsquo;t update automatically.
          </p>
        )}
        {checkoutBanner === "cancelled" && (
          <p className="notice" role="status">
            Checkout was cancelled — no payment was taken.
          </p>
        )}
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {homeLoading || !status ? (
          <p role="status">Loading billing status…</p>
        ) : (
          <>
            <section>
              <h2>Current plan</h2>
              <dl>
                <dt>Effective plan</dt>
                <dd>
                  <strong className={`state-label ${planBadgeClass(status.effective_plan)}`}>
                    {planLabel(status.effective_plan)}
                  </strong>
                </dd>
                {status.provider !== "free" && (
                  <>
                    <dt>Provider</dt>
                    <dd>{providerLabel(status.provider)}</dd>
                    <dt>Status</dt>
                    <dd>
                      <strong className={`state-label ${statusBadgeClass(status.status)}`}>
                        {statusLabel(status.status)}
                      </strong>
                    </dd>
                  </>
                )}
                {status.current_period_end && (
                  <>
                    <dt>{periodLabel(status.cancel_at_period_end)}</dt>
                    <dd>{new Date(status.current_period_end).toLocaleDateString()}</dd>
                  </>
                )}
              </dl>
            </section>

            {!status.can_manage_billing ? (
              <p className="quiet-state">Ask a Home Admin to manage this Home&rsquo;s billing.</p>
            ) : (
              <section className="action-panel">
                <h2>Manage billing</h2>
                {status.effective_plan === "free" ? (
                  status.stripe_billing_available && pricing ? (
                    <div className="platform-modal-actions">
                      {pricing.options.map((option) => (
                        <button
                          key={option.interval}
                          disabled={busy}
                          onClick={() => startCheckout(option.interval)}
                        >
                          Upgrade to Family — {option.formatted_amount}/
                          {intervalSuffix(option.interval)}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="quiet-state">Billing is not currently available.</p>
                  )
                ) : (
                  <p>This Home is on the Family plan.</p>
                )}
                {status.has_stripe_customer && (
                  <button className="secondary" disabled={busy} onClick={openPortal}>
                    Manage payment details
                  </button>
                )}
              </section>
            )}
          </>
        )}
      </main>
    </SettingsPage>
  );
}
