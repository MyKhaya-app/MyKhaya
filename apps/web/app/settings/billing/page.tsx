"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Calendar,
  BarChart3,
  Car,
  Check,
  Crown,
  Home as HomeIcon,
  ListChecks,
  Sprout,
  Star,
  Tag,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { BillingStatus, FamilyPricing, PlanComparison, SubscriptionPlanValue } from "@mykhaya/shared-types";
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
  planAction,
  periodLabel,
  pollForFamilyBillingStatus,
  resolvePlanCardKind,
} from "@/components/billing-logic";
import { overLimitExplanation } from "@/components/calendar-entitlement-logic";
import { memberOverLimitExplanation } from "@/components/member-entitlement-logic";
import { canStartUltimateCheckout } from "@/components/family-pricing-logic";

// One small icon per comparison row key — purely decorative (the row label
// text already carries the meaning), keyed off PlanComparisonRow.key so a
// future row this map doesn't recognise still renders sensibly rather than
// crashing. See mykhaya.routers.billing.plan_comparison for the source of
// truth on which keys actually exist.
const COMPARISON_ROW_ICONS: Record<string, typeof Users> = {
  "home.max_members": Users,
  "calendar.max_categories": Calendar,
  "calendar.max_tags": Tag,
  "routines.personal.max_active": ListChecks,
  "routines.household.enabled": HomeIcon,
  "budget.enabled": BarChart3,
  "driveway.enabled": Car,
  "premium.future": Star,
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function firstPrice(pricing: FamilyPricing | null, plan: "family" | "ultimate") {
  const options = plan === "ultimate" ? pricing?.ultimate_options : pricing?.options;
  return options?.[0] ?? null;
}

function comparisonValue(value: string) {
  if (value === "Included") return <Check className="plan-value-check" aria-label="Included" />;
  if (value === "Not included") return <span className="plan-value-dash" aria-label="Not included">—</span>;
  if (value === "Whole household") return "Household";
  return value;
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
  const [manageOpen, setManageOpen] = useState(false);
  const [confirmationTimedOut, setConfirmationTimedOut] = useState(false);
  const checkoutPlan = useRef<"family" | "ultimate">("family");

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
      return pollForFamilyBillingStatus(load, { targetPlan: checkoutPlan.current });
    })().then((result) => {
      if (
        !cancelled &&
        result?.effective_plan !== checkoutPlan.current
      ) {
        setConfirmationTimedOut(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [checkoutBanner, checkoutSessionId, load]);

  async function startCheckout(
    interval: "month" | "year",
    plan: SubscriptionPlanValue = "family",
  ) {
    if (!activeHomeId || busy) return;
    checkoutPlan.current = plan === "ultimate" ? "ultimate" : "family";
    setBusy(true);
    setError("");
    try {
      const { checkout_url: checkoutUrl } = await api.createCheckoutSession(
        activeHomeId,
        interval,
        plan,
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

  function openManagePlan() {
    if (status?.can_manage_billing && status.provider === "stripe") setManageOpen(true);
  }

  const cardKind = status ? resolvePlanCardKind(status) : null;
  const planLabel =
    status?.effective_plan === "ultimate" || status?.stored_plan === "ultimate"
      ? "Ultimate"
      : "Family";
  const restoreOption = pricing?.options[0];
  const familyPrice = status?.effective_plan === "family" && status.price
    ? status.price
    : firstPrice(pricing, "family");
  const ultimatePrice = status?.effective_plan === "ultimate" && status.price
    ? status.price
    : firstPrice(pricing, "ultimate");
  const familyInterval = status?.effective_plan === "family" && status.billing_interval
    ? status.billing_interval
    : firstPrice(pricing, "family")?.interval;
  const ultimateInterval = status?.effective_plan === "ultimate" && status.billing_interval
    ? status.billing_interval
    : firstPrice(pricing, "ultimate")?.interval;
  const stillConfirming =
    checkoutBanner === "success" && status?.effective_plan === "free" && !confirmationTimedOut;

  return (
    <SettingsPage
      title="Plan & Billing"
      description="Manage this Home's plan, payment and retention status."
    >
      <main className="standard-page module-page">
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
                    <strong className={`state-label ${planBadgeClass("family")}`}>{planLabel}</strong>{" "}
                    <span className="state-label state-soft">Complimentary access</span>
                  </p>
                  <p>No payment required. Access does not expire.</p>
                  <p>{planLabel} applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "complimentary_with_expiry" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>{planLabel}</strong>{" "}
                    <span className="state-label state-soft">Complimentary access</span>
                  </p>
                  <p>No payment required. Access until {formatDate(status.complimentary_expires_at)}.</p>
                  <p>{planLabel} applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "stripe_active" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>{planLabel}</strong>{" "}
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
                  <p>{planLabel} applies to everyone in this Home.</p>
                </>
              )}

              {cardKind === "stripe_past_due" && (
                <>
                  <p>
                    <strong className={`state-label ${planBadgeClass("family")}`}>{planLabel}</strong>{" "}
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
                  <p>You&rsquo;ll keep {planLabel} access until then.</p>
                  <p>{planLabel} applies to everyone in this Home.</p>
                  <div className="notice" role="status">
                    <strong>Your Home will move to MyKhaya Free when Family ends.</strong>
                    <p>
                      Free supports one person per Home. Your Home Admin will remain connected;
                      additional adult members will lose connectivity here and fall back to their
                      own MyKhaya plan. Their accounts and Home data will not be deleted.
                    </p>
                    {status.affected_adult_members?.length ? (
                      <p>Affected members: {status.affected_adult_members.join(", ")}.</p>
                    ) : null}
                    <p>
                      Sponsored Family access from this Home will end. Independently shared
                      calendars remain separate, and Family data is not purged in this phase.
                    </p>
                  </div>
                </>
              )}

              {(status.retention_state === "retained_free" ||
                status.retention_state === "purge_pending") &&
                status.retention_deadline && (
                  <div className="notice" role="status">
                    <strong>Family data retained until {formatDate(status.retention_deadline)}</strong>
                    <p>
                      Your personal calendar remains available. Family-only data is unavailable
                      while this Home is Free, but remains retained during this 90-day window.
                      Renew Family before the date above to restore it; after that, eligible data
                      is permanently removed and cannot be recovered.
                    </p>
                    {restoreOption && (
                      <button
                        disabled={busy}
                        onClick={() => startCheckout(restoreOption.interval)}
                      >
                        Restore with MyKhaya Family
                      </button>
                    )}
                  </div>
                )}

              {status.retention_state === "purged" && status.retention_deadline && (
                <div className="notice" role="status">
                  <strong>Family data retention ended on {formatDate(status.retention_deadline)}</strong>
                  <p>
                    Eligible Family-only data was permanently removed. Your Home, account and
                    personal calendar remain available.
                  </p>
                </div>
              )}

              {stillConfirming && (
                <p className="quiet-state">
                  Still confirming your subscription — this page will update automatically shortly.
                </p>
              )}

              {canShowPortalAction(status) && (
                <button disabled={busy} onClick={openManagePlan}>
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

            {canShowUpgradeOptions(status) && pricing?.ultimate_options?.length ? (
              <section>
                <h2>Upgrade to Ultimate</h2>
                <p>Everything in Family, plus Budget, Driveway and future premium modules.</p>
                {!canStartUltimateCheckout(pricing) ? (
                  <p className="notice" role="status">
                    New Ultimate sign-ups are temporarily paused.
                  </p>
                ) : (
                  <div className="feature-card-grid">
                    {pricing.ultimate_options.map((option) => (
                      <article className="card feature-card" key={`ultimate-${option.interval}`}>
                        <div className="feature-card-heading">
                          <h3>Ultimate {intervalName(option.interval)}</h3>
                          {option.interval === "year" && pricing.ultimate_annual_is_best_value && (
                            <span className="release-badge core">Best value</span>
                          )}
                        </div>
                        <p>
                          <strong>{option.formatted_amount}</strong> / {intervalSuffix(option.interval)}
                        </p>
                        {option.interval === "year" && pricing.ultimate_annual_saving_formatted && (
                          <small>Save {pricing.ultimate_annual_saving_formatted} per year</small>
                        )}
                        <button
                          disabled={busy}
                          onClick={() => startCheckout(option.interval, "ultimate")}
                        >
                          Upgrade to Ultimate
                        </button>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            ) : null}

            <section className="card plan-compare plan-compare-redesign">
              <h2>Compare plans</h2>
              <p className="plan-compare-intro">
                Find the plan that&rsquo;s right for your Home. Upgrade anytime, and keep your data.
              </p>
              <div className="plan-option-grid">
                <article className={`plan-option-card${status.effective_plan === "free" ? " is-current" : ""}`}>
                  <div className="plan-option-title"><Sprout aria-hidden="true" /><h3>Free</h3></div>
                  <p className="plan-option-description">Great for getting started</p>
                  <strong className="plan-option-price">£0</strong><span className="plan-option-cadence">forever</span>
                  <button className={`plan-option-action ${planAction(status.effective_plan, "free").toLowerCase().replace(" ", "-")}`} disabled={status.effective_plan === "free" || busy || (!canShowUpgradeOptions(status) && !canShowPortalAction(status))} onClick={() => { if (canShowPortalAction(status)) void openPortal(); }}>
                    {planAction(status.effective_plan, "free")}
                  </button>
                </article>
                <article className={`plan-option-card${status.effective_plan === "family" ? " is-current" : ""}`}>
                  <div className="plan-option-title"><Crown aria-hidden="true" /><h3>Family</h3></div>
                  <p className="plan-option-description">The complete family experience</p>
                  {familyPrice ? <><strong className="plan-option-price">{familyPrice.formatted_amount}</strong><span className="plan-option-cadence">per {familyInterval}</span></> : <span className="plan-option-cadence">Complimentary access</span>}
                  <button className={`plan-option-action ${planAction(status.effective_plan, "family").toLowerCase().replace(" ", "-")}`} disabled={busy || (status.effective_plan === "family" ? true : !canShowUpgradeOptions(status) && !canShowPortalAction(status))} onClick={() => { if (status.effective_plan === "family") return; if (canShowPortalAction(status)) void openPortal(); else { const option = firstPrice(pricing, "family"); if (option) void startCheckout(option.interval); } }}>
                    {planAction(status.effective_plan, "family")}
                  </button>
                </article>
                <article className={`plan-option-card${status.effective_plan === "ultimate" ? " is-current" : ""}`}>
                  <div className="plan-option-title"><Star aria-hidden="true" /><h3>Ultimate</h3></div>
                  <p className="plan-option-description">Unlock powerful premium modules</p>
                  {ultimatePrice ? <><strong className="plan-option-price">{ultimatePrice.formatted_amount}</strong><span className="plan-option-cadence">per {ultimateInterval}</span></> : <span className="plan-option-cadence">Pricing unavailable</span>}
                  <button className={`plan-option-action ${planAction(status.effective_plan, "ultimate").toLowerCase().replace(" ", "-")}`} disabled={busy || (status.effective_plan === "ultimate" ? true : (!canShowUpgradeOptions(status) && !canShowPortalAction(status)) || !pricing?.ultimate_options?.length || !canStartUltimateCheckout(pricing))} onClick={() => { if (status.effective_plan === "ultimate") return; if (canShowPortalAction(status)) void openPortal(); else { const option = firstPrice(pricing, "ultimate"); if (option) void startCheckout(option.interval, "ultimate"); } }}>
                    {planAction(status.effective_plan, "ultimate")}
                  </button>
                </article>
              </div>
            </section>

            {comparison && comparison.rows.length > 0 && (
              <section className="card plan-compare comparison-table-card">
                <h2>Compare plans</h2>
                <table className="plan-compare-table">
                  <caption className="sr-only">
                    What's included on the Free, Family and Ultimate plans
                  </caption>
                  <colgroup>
                    <col className="plan-compare-col-feature" />
                    <col className="plan-compare-col-free" />
                    <col className="plan-compare-col-family" />
                    <col className="plan-compare-col-family" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Features</th>
                      <th scope="col"><span className="plan-compare-heading"><Sprout size={18} aria-hidden="true" /><span>Free</span></span></th>
                      <th scope="col" className="plan-compare-family-heading">
                        <span className="plan-compare-heading"><Crown size={14} aria-hidden="true" /><span>Family</span></span>
                      </th>
                      <th scope="col" className="plan-compare-family-heading"><span className="plan-compare-heading"><Star size={14} aria-hidden="true" /><span>Ultimate</span></span></th>
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
                          <td className="plan-compare-free-value">{comparisonValue(row.free_display)}</td>
                          <td className="plan-compare-family-value">{comparisonValue(row.family_display)}</td>
                          <td className="plan-compare-family-value">{comparisonValue(row.ultimate_display)}</td>
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
                  <strong>Your Home currently has {planLabel} access.</strong>
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
      {manageOpen && status && (
        <div className="billing-manage-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setManageOpen(false); }}>
          <section className="billing-manage-sheet" role="dialog" aria-modal="true" aria-labelledby="billing-manage-title">
            <div className="billing-manage-heading">
              <div>
                <p className="eyebrow">Manage your home</p>
                <h2 id="billing-manage-title">Manage plan</h2>
              </div>
              <button className="billing-manage-close" aria-label="Close manage plan" onClick={() => setManageOpen(false)}>×</button>
            </div>
            <div className="billing-manage-summary">
              <strong>{planLabel}</strong>
              <span>{statusLabel(status.status)}</span>
              {status.price && status.billing_interval && <span>{status.price.formatted_amount} · {intervalName(status.billing_interval)}</span>}
            </div>
            {status.cancel_at_period_end && status.current_period_end ? (
              <div className="notice" role="status">
                <strong>Your {planLabel} access ends on {formatDate(status.current_period_end)}.</strong>
                <p>Your paid access remains active until then. Keep your subscription or undo the cancellation in the billing provider.</p>
              </div>
            ) : status.current_period_end && status.price ? (
              <div className="billing-upcoming-card">
                <span>Next renewal</span>
                <strong>{formatDate(status.current_period_end)}</strong>
                <small>{status.price.formatted_amount} · {intervalName(status.billing_interval ?? "month")}</small>
              </div>
            ) : null}
            <p className="quiet-state">Payment methods, invoices, receipts and cancellation controls are securely managed by Stripe.</p>
            <button disabled={busy} onClick={() => { setManageOpen(false); void openPortal(); }}>Open billing portal</button>
          </section>
        </div>
      )}
    </SettingsPage>
  );
}
