"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Calendar,
  Check,
  Crown,
  Home as HomeIcon,
  ListChecks,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { BillingStatus, FamilyPricing, PlanComparison } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { planBadgeClass, statusBadgeClass, statusLabel } from "@/components/subscriptions-logic";
import {
  canShowPortalAction,
  canShowUpgradeOptions,
  checkoutBannerKind,
  hasFullFamilyAccess,
  intervalName,
  intervalSuffix,
  periodLabel,
  pollForFamilyBillingStatus,
  resolvePlanCardKind,
} from "@/components/billing-logic";
import { overLimitExplanation } from "@/components/calendar-entitlement-logic";
import { memberOverLimitExplanation } from "@/components/member-entitlement-logic";

// One small icon per comparison row key — purely decorative (the row label
// text already carries the meaning), keyed off PlanComparisonRow.key so a
// future row this map doesn't recognise still renders sensibly rather than
// crashing. See mykhaya.routers.billing.plan_comparison for the source of
// truth on which keys actually exist.
const COMPARISON_ROW_ICONS: Record<string, typeof Users> = {
  "home.max_members": Users,
  "calendar.max_categories": Calendar,
  "routines.personal.max_active": ListChecks,
  "routines.household.enabled": HomeIcon,
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

// The polished household Plan & Billing experience (Phase 4) — replaces
// Phase 3's minimal test surface at the same route. Reads a single
// backend-prepared BillingStatus (never infers Stripe semantics itself) and
// renders exactly one coherent card per commercial state. Public marketing
// pricing and the signup plan-selection flow remain out of scope — see
// docs/product/plans-and-pricing.md.
export default function PlanAndBillingSettings() {
  const { activeHomeId, loading: homeLoading } = useActiveHome();
  const searchParams = useSearchParams();
  const checkoutBanner = checkoutBannerKind(searchParams.get("checkout"));
  const checkoutSessionId = searchParams.get("session_id");

  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [pricingError, setPricingError] = useState(false);
  const [comparison, setComparison] = useState<PlanComparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmationTimedOut, setConfirmationTimedOut] = useState(false);

  const load = useCallback(async () => {
    if (!activeHomeId) return null;
    setError("");
    try {
      const billingStatus = await api.billingStatus(activeHomeId);
      setStatus(billingStatus);
      return billingStatus;
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load billing status.");
      return null;
    }
  }, [activeHomeId]);

  // One coherent initial load: billing status first (it decides which card
  // to show), then the two independent, lower-priority endpoints (pricing,
  // comparison) load in the background without blocking or re-flashing the
  // primary card.
  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .familyPricing()
      .then(setPricing)
      .catch(() => setPricingError(true));
    api
      .planComparison()
      .then(setComparison)
      .catch(() => undefined);
  }, []);

  // A browser return from Checkout never activates Family by itself (see
  // docs/architecture/commercial-entitlements.md#checkout-lifecycle). Poll
  // authoritative billing state while the webhook is being delivered.
  useEffect(() => {
    if (checkoutBanner !== "success") return;
    setConfirmationTimedOut(false);
    let cancelled = false;
    void (async () => {
      if (checkoutSessionId) {
        try {
          await api.confirmCheckoutSession(checkoutSessionId);
          await load();
        } catch (cause) {
          if (!cancelled && cause instanceof ApiError && cause.status !== 503) {
            setError("We could not confirm this checkout for the current Home.");
            setConfirmationTimedOut(true);
            return;
          }
        }
      }
      return pollForFamilyBillingStatus(load);
    })().then((result) => {
      if (!cancelled && result?.effective_plan !== "family") setConfirmationTimedOut(true);
    });
    return () => {
      cancelled = true;
    };
  }, [checkoutBanner, checkoutSessionId, load]);

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
      if (cause instanceof ApiError && cause.status === 409) {
        setError("This Home already has an active subscription.");
      } else if (cause instanceof ApiError && cause.status === 403) {
        setError("Only a Home Administrator can manage this Home's plan.");
      } else if (cause instanceof ApiError && cause.status === 503) {
        setError("Billing is not available right now. Please try again shortly.");
      } else {
        setError("Could not start checkout. Please try again.");
      }
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
      if (cause instanceof ApiError && cause.status === 503) {
        setError("Billing is not available right now. Please try again shortly.");
      } else {
        setError("Could not open the billing portal. Please try again.");
      }
      setBusy(false);
    }
  }

  const cardKind = status ? resolvePlanCardKind(status) : null;
  const stillConfirming =
    checkoutBanner === "success" && status?.effective_plan === "free" && !confirmationTimedOut;

  return (
    <SettingsPage title="Plan & Billing">
      <main className="standard-page">
        {checkoutBanner === "success" && (
          <p className="notice" role="status">
            {status?.effective_plan === "family"
              ? "Your Family subscription is active."
              : confirmationTimedOut
                ? "Your payment was completed, but we're still confirming your subscription. Please check again shortly."
                : "Payment received. We're confirming your subscription — this usually takes just a few seconds."}
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
          <p role="status">Loading your plan…</p>
        ) : (
          <div className="plan-card-stack">
            <section className="card plan-card">
              <div className="plan-card-header">
                <span className="plan-card-icon" aria-hidden="true">
                  <ShieldCheck size={22} />
                </span>
                <div className="plan-card-heading">
                  <h2>Current plan</h2>
                </div>
              </div>
              <div className="plan-card-body">
              {cardKind === "free" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("free")}`}>Free</strong>
                  </p>
                  <p>Your Home is currently using MyKhaya Free.</p>
                  <p>Upgrade to Family to unlock the full MyKhaya experience for your whole household.</p>
                </>
              )}

              {cardKind === "free_expired_complimentary" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("free")}`}>Free</strong>
                  </p>
                  <p>
                    Your complimentary Family access ended
                    {status.complimentary_expires_at
                      ? ` on ${formatDate(status.complimentary_expires_at)}`
                      : ""}
                    .
                  </p>
                  <p>Your existing information has not been deleted.</p>
                </>
              )}

              {cardKind === "free_ended_stripe" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("free")}`}>Free</strong>
                  </p>
                  <p>
                    Your Family subscription ended
                    {status.current_period_end ? ` on ${formatDate(status.current_period_end)}` : ""}.
                  </p>
                  <p>Your existing Home data has not been deleted.</p>
                </>
              )}

              {cardKind === "complimentary_no_expiry" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>Family</strong>{" "}
                    <span className="state-label state-soft">Complimentary access</span>
                  </p>
                  <p>No payment required. Access does not expire.</p>
                  <p>Family applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "complimentary_with_expiry" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>Family</strong>{" "}
                    <span className="state-label state-soft">Complimentary access</span>
                  </p>
                  <p>No payment required. Access until {formatDate(status.complimentary_expires_at)}.</p>
                  <p>Family applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "stripe_active" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>Family</strong>{" "}
                    <strong className={`state-label ${statusBadgeClass(status.status)}`}>
                      {statusLabel(status.status)}
                    </strong>
                  </p>
                  {status.billing_interval && status.price && (
                    <p>
                      {intervalName(status.billing_interval)} billing
                      <br />
                      {status.price.formatted_amount} / {status.billing_interval === "month" ? "month" : "year"}
                    </p>
                  )}
                  <p>
                    {periodLabel(false)}
                    <br />
                    {formatDate(status.current_period_end)}
                  </p>
                  <p>Family applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "stripe_past_due" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>Family</strong>{" "}
                    <strong className={`state-label ${statusBadgeClass(status.status)}`}>
                      Payment needs attention
                    </strong>
                  </p>
                  <p role="alert">We couldn&rsquo;t collect your latest payment.</p>
                  <p>
                    Your Family access is currently being maintained while you update your payment
                    method.
                  </p>
                </>
              )}

              {cardKind === "stripe_cancelling" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>Family</strong>{" "}
                    <strong className={`state-label ${statusBadgeClass(status.status)}`}>
                      Cancels on {formatDate(status.current_period_end)}
                    </strong>
                  </p>
                  <p>You&rsquo;ll keep Family access until then.</p>
                  <p>Family applies to everyone in this Home.</p>
                </>
              )}

              {stillConfirming && (
                <p className="quiet-state">
                  Still confirming your subscription — this page will update automatically shortly.
                </p>
              )}

              {canShowPortalAction(status) && (
                <button disabled={busy} onClick={openPortal}>
                  {cardKind === "stripe_past_due" ? "Update payment method" : "Manage billing"}
                </button>
              )}

              {overLimitExplanation(status.calendar_usage) && (
                <p className="notice" role="status">
                  {overLimitExplanation(status.calendar_usage)}
                </p>
              )}

              {memberOverLimitExplanation(status.member_usage) && (
                <p className="notice" role="status">
                  {memberOverLimitExplanation(status.member_usage)}
                </p>
              )}
              </div>

              {cardKind && hasFullFamilyAccess(cardKind) && (
                <p className="plan-card-footer">
                  <Check size={16} aria-hidden="true" />
                  All Family features included
                </p>
              )}
            </section>

            {!status.can_manage_billing && status.effective_plan === "free" && (
              <p className="quiet-state">A Home Administrator can manage the plan for this Home.</p>
            )}

            {canShowUpgradeOptions(status) && (
              <section>
                <h2>Upgrade to Family</h2>
                {pricingError ? (
                  <p className="notice error" role="alert">
                    Family pricing is temporarily unavailable. Please try again shortly.
                  </p>
                ) : !pricing ? (
                  <p role="status">Loading pricing…</p>
                ) : (
                  <div className="feature-card-grid">
                    {pricing.options.map((option) => (
                      <article className="card feature-card" key={option.interval}>
                        <div className="feature-card-heading">
                          <h3>Family {intervalName(option.interval)}</h3>
                          {option.interval === "year" && pricing.annual_is_best_value && (
                            <span className="release-badge core">Best value</span>
                          )}
                        </div>
                        <p>
                          <strong>{option.formatted_amount}</strong>
                          <span aria-hidden="true"> / {intervalSuffix(option.interval)}</span>
                          <span className="sr-only"> per {option.interval}</span>
                        </p>
                        {option.interval === "year" && pricing.annual_saving_formatted && (
                          <small>Save {pricing.annual_saving_formatted} per year</small>
                        )}
                        <button disabled={busy} onClick={() => startCheckout(option.interval)}>
                          Upgrade to Family
                        </button>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}

            {comparison && comparison.rows.length > 0 && (
              <section className="card plan-compare">
                <h2>Free vs Family</h2>
                <table className="plan-compare-table">
                  <caption className="sr-only">
                    What's included on the Free plan compared with Family
                  </caption>
                  <colgroup>
                    <col className="plan-compare-col-feature" />
                    <col className="plan-compare-col-free" />
                    <col className="plan-compare-col-family" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="sr-only">Feature</span>
                      </th>
                      <th scope="col">Free</th>
                      <th scope="col" className="plan-compare-family-heading">
                        <Crown size={14} aria-hidden="true" />
                        Family
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.rows.map((row) => {
                      const RowIcon = COMPARISON_ROW_ICONS[row.key];
                      return (
                        <tr key={row.key}>
                          <th scope="row">
                            <span className="plan-compare-row-feature">
                              {RowIcon && <RowIcon size={15} aria-hidden="true" />}
                              {row.label}
                            </span>
                          </th>
                          <td className="plan-compare-free-value">{row.free_display}</td>
                          <td className="plan-compare-family-value">{row.family_display}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            )}

            {cardKind && hasFullFamilyAccess(cardKind) && (
              <div className="plan-info-card">
                <HomeIcon size={22} aria-hidden="true" />
                <div>
                  <strong>Your Home currently has Family access.</strong>
                  <p>Enjoy all features together.</p>
                </div>
              </div>
            )}

            {status.provider === "stripe" && (
              <p className="quiet-state">
                Payments are securely managed by Stripe. Billing and invoices are available through
                Manage billing.
              </p>
            )}
          </div>
        )}
      </main>
    </SettingsPage>
  );
}
