"use client";

import { FormEvent, use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate } from "@/components/platform-format";
import type { SubscriptionDetail } from "@/components/platform-types";
import {
  complimentaryReasonPresets,
  eventTypeLabel,
  hasEffectiveDivergence,
  planBadgeClass,
  planLabel,
  providerBadgeClass,
  providerLabel,
  statusBadgeClass,
  statusLabel,
} from "@/components/subscriptions-logic";

const ENTITLEMENT_LABELS: Record<string, string> = {
  "lists.enabled": "Lists",
  "chores.enabled": "Chores",
  "notes.enabled": "Notes",
  "wishlists.enabled": "Wishlists",
};

const LIMIT_LABELS: Record<string, string> = {
  "calendar.max_calendars": "Calendar maximum",
};

export default function SubscriptionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [data, setData] = useState<SubscriptionDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showGrantForm, setShowGrantForm] = useState(false);
  const [showRevokeForm, setShowRevokeForm] = useState(false);
  const [showReconcileForm, setShowReconcileForm] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(
        await platformApi.get<SubscriptionDetail>(`/subscriptions/${encodeURIComponent(id)}`),
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load this Home.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const grantComplimentary = guarded(async (formData: FormData) => {
    setError("");
    const presetReason = formData.get("reason_preset") as string;
    const customReason = (formData.get("reason_custom") as string) || "";
    const complimentaryReason =
      presetReason === "Other" ? customReason.trim() : presetReason || customReason.trim();
    const expiryChoice = formData.get("expiry_choice") as string;
    const expiryDate = formData.get("expiry_date") as string;
    try {
      await platformApi.put(`/homes/${encodeURIComponent(id)}/subscription/complimentary`, {
        complimentary_reason: complimentaryReason,
        complimentary_note: (formData.get("note") as string) || null,
        expires_at: expiryChoice === "specific" && expiryDate ? expiryDate : null,
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Complimentary Family access granted.");
      setShowGrantForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(
        cause instanceof ApiError ? cause.message : "Complimentary access could not be granted.",
      );
    }
  });

  const reconcileStripe = guarded(async (formData: FormData) => {
    setError("");
    try {
      await platformApi.post(`/homes/${encodeURIComponent(id)}/subscription/reconcile-stripe`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Reconciled with Stripe's current subscription state.");
      setShowReconcileForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not reconcile with Stripe.");
    }
  });

  const revokeComplimentary = guarded(async (formData: FormData) => {
    setError("");
    try {
      await platformApi.delete(`/homes/${encodeURIComponent(id)}/subscription/complimentary`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Complimentary access removed — this Home is now on the Free plan.");
      setShowRevokeForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(
        cause instanceof ApiError ? cause.message : "Complimentary access could not be removed.",
      );
    }
  });

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Commercial detail</p>
            <h1>{data?.name ?? "Home"}</h1>
          </div>
          <div className="platform-modal-actions">
            <Link href="/subscriptions" className="secondary">
              Back to Subscriptions
            </Link>
            <button className="secondary" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </div>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}
        {!data ? (
          <p role="status">Loading…</p>
        ) : (
          <>
            <section>
              <h2>Home information</h2>
              <dl>
                <dt>Home ID</dt>
                <dd>
                  <code>{data.id}</code>
                </dd>
                <dt>Created</dt>
                <dd>{readableDate(data.created_at)}</dd>
                <dt>Members</dt>
                <dd>{data.member_count}</dd>
              </dl>
              {data.administrators.length > 0 && (
                <div className="record-list">
                  {data.administrators.map((admin) => (
                    <article key={admin.user_id}>
                      <strong>{admin.display_name}</strong>
                      <span>{admin.email}</span>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section>
              <h2>Stored commercial state</h2>
              <dl>
                <dt>Plan</dt>
                <dd>
                  <strong className={`state-label ${planBadgeClass(data.subscription.plan)}`}>
                    {planLabel(data.subscription.plan)}
                  </strong>
                </dd>
                <dt>Provider</dt>
                <dd>
                  <strong
                    className={`state-label ${providerBadgeClass(data.subscription.provider)}`}
                  >
                    {providerLabel(data.subscription.provider)}
                  </strong>
                </dd>
                <dt>Status</dt>
                <dd>
                  <strong className={`state-label ${statusBadgeClass(data.subscription.status)}`}>
                    {statusLabel(data.subscription.status)}
                  </strong>
                </dd>
                {data.subscription.complimentary_reason && (
                  <>
                    <dt>Complimentary reason</dt>
                    <dd>{data.subscription.complimentary_reason}</dd>
                  </>
                )}
                {data.subscription.complimentary_note && (
                  <>
                    <dt>Internal note (Platform Admin only)</dt>
                    <dd>{data.subscription.complimentary_note}</dd>
                  </>
                )}
                {data.subscription.complimentary_granted_by_display_name && (
                  <>
                    <dt>Granted by</dt>
                    <dd>{data.subscription.complimentary_granted_by_display_name}</dd>
                  </>
                )}
                {data.subscription.complimentary_granted_at && (
                  <>
                    <dt>Granted</dt>
                    <dd>{readableDate(data.subscription.complimentary_granted_at)}</dd>
                  </>
                )}
                {data.subscription.complimentary_expires_at && (
                  <>
                    <dt>Complimentary expiry</dt>
                    <dd>{readableDate(data.subscription.complimentary_expires_at)}</dd>
                  </>
                )}
                {data.subscription.external_customer_id && (
                  <>
                    <dt>External customer ID</dt>
                    <dd>
                      <code>{data.subscription.external_customer_id}</code>
                    </dd>
                  </>
                )}
                {data.subscription.external_subscription_id && (
                  <>
                    <dt>External subscription ID</dt>
                    <dd>
                      <code>{data.subscription.external_subscription_id}</code>
                    </dd>
                  </>
                )}
                {data.subscription.billing_interval && (
                  <>
                    <dt>Billing interval</dt>
                    <dd>{data.subscription.billing_interval === "month" ? "Monthly" : "Annual"}</dd>
                  </>
                )}
                {data.stripe_price && (
                  <>
                    <dt>Current price</dt>
                    <dd>
                      {data.stripe_price.formatted_amount} / {data.subscription.billing_interval}{" "}
                      <small>
                        (<code>{data.subscription.external_price_id}</code>)
                      </small>
                    </dd>
                  </>
                )}
              </dl>
              {(data.stripe_dashboard_customer_url || data.stripe_dashboard_subscription_url) && (
                <div className="platform-modal-actions">
                  {data.stripe_dashboard_customer_url && (
                    <a
                      className="secondary"
                      href={data.stripe_dashboard_customer_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Customer in Stripe
                    </a>
                  )}
                  {data.stripe_dashboard_subscription_url && (
                    <a
                      className="secondary"
                      href={data.stripe_dashboard_subscription_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Subscription in Stripe
                    </a>
                  )}
                </div>
              )}
            </section>

            <section>
              <h2>Effective commercial state</h2>
              <dl>
                <dt>Effective plan</dt>
                <dd>
                  <strong
                    className={`state-label ${planBadgeClass(data.subscription.effective_plan)}`}
                  >
                    {planLabel(data.subscription.effective_plan)}
                  </strong>
                </dd>
                {hasEffectiveDivergence(
                  data.subscription.plan,
                  data.subscription.effective_plan,
                ) && (
                  <>
                    <dt>Reason</dt>
                    <dd>{data.subscription.effective_status_reason}</dd>
                  </>
                )}
              </dl>
            </section>

            {data.subscription.provider === "stripe" && (
              <section className="action-panel">
                <h2>Stripe</h2>
                <p>
                  This Home&rsquo;s commercial state is driven by Stripe. Provider, plan and
                  status cannot be edited directly here — reconciliation re-fetches Stripe&rsquo;s
                  own current subscription state and re-applies it through the same logic
                  webhooks use.
                </p>
                <button className="secondary" onClick={() => setShowReconcileForm(true)}>
                  Reconcile with Stripe
                </button>
              </section>
            )}

            <section className="action-panel">
              <h2>Complimentary access</h2>
              {data.subscription.provider === "stripe" &&
              data.subscription.status !== "cancelled" ? (
                <p className="notice error" role="alert">
                  This Home has an active Stripe subscription. Complimentary access cannot be
                  granted while it is still billing — the Stripe subscription must be cancelled
                  first (via the Customer Portal or Stripe directly).
                </p>
              ) : data.subscription.provider === "complimentary" ? (
                <>
                  <p>This Home currently has complimentary Family access.</p>
                  <div className="platform-modal-actions">
                    <button className="secondary" onClick={() => setShowGrantForm(true)}>
                      Extend / update complimentary access
                    </button>
                    <button className="danger" onClick={() => setShowRevokeForm(true)}>
                      Remove complimentary access
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p>This Home does not currently have complimentary access.</p>
                  <button onClick={() => setShowGrantForm(true)}>
                    Grant complimentary Family access
                  </button>
                </>
              )}
            </section>

            <section>
              <h2>Entitlements ({planLabel(data.entitlements.plan)})</h2>
              <dl>
                {Object.entries(data.entitlements.limits).map(([key, value]) => (
                  <div key={key}>
                    <dt>{LIMIT_LABELS[key] ?? key}</dt>
                    <dd>{value === null ? "Unlimited" : value}</dd>
                  </div>
                ))}
                {Object.entries(data.entitlements.booleans).map(([key, value]) => (
                  <div key={key}>
                    <dt>{ENTITLEMENT_LABELS[key] ?? key}</dt>
                    <dd>{value ? "Enabled" : "Not available"}</dd>
                  </div>
                ))}
                <div>
                  <dt>Current calendars</dt>
                  <dd>
                    {data.calendar_usage.count}
                    {data.calendar_usage.over_limit && (
                      <>
                        {" "}
                        <strong className="state-label state-warning">Over plan limit</strong>
                      </>
                    )}
                  </dd>
                </div>
              </dl>
            </section>

            <section>
              <h2>Commercial event history</h2>
              {data.history.length === 0 ? (
                <p className="quiet-state">No commercial events recorded yet.</p>
              ) : (
                <div className="record-list">
                  {data.history.map((event) => (
                    <article key={event.id}>
                      <strong>{eventTypeLabel(event.event_type)}</strong>
                      <time dateTime={event.created_at}>{readableDate(event.created_at)}</time>
                      {event.reason && <p>Reason: {event.reason}</p>}
                      {event.actor_display_name && <p>By: {event.actor_display_name}</p>}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {showGrantForm && (
        <div
          className="platform-modal-backdrop"
          role="presentation"
          onClick={() => setShowGrantForm(false)}
        >
          <div
            className="platform-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="grant-complimentary-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="grant-complimentary-title">Grant complimentary Family access</h2>
            <p>
              This gives the Home Family-plan entitlements without payment — for beta testers,
              friends and family, or internal use. It never touches Stripe.
            </p>
            <form
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                void grantComplimentary(new FormData(event.currentTarget));
              }}
            >
              <label>
                Reason
                <select name="reason_preset" defaultValue="">
                  <option value="">Choose a reason…</option>
                  {complimentaryReasonPresets().map((preset) => (
                    <option key={preset} value={preset}>
                      {preset}
                    </option>
                  ))}
                  <option value="Other">Other (specify below)</option>
                </select>
              </label>
              <label>
                Custom reason (used if &ldquo;Other&rdquo; is selected, or on its own)
                <input name="reason_custom" type="text" maxLength={200} />
              </label>
              <label>
                Internal note (optional, visible only to Platform Administrators)
                <textarea name="note" maxLength={1000} />
              </label>
              <fieldset>
                <legend>Expiry</legend>
                <label>
                  <input type="radio" name="expiry_choice" value="never" defaultChecked />
                  Never
                </label>
                <label>
                  <input type="radio" name="expiry_choice" value="specific" />
                  Specific date/time
                </label>
                <label>
                  <input type="datetime-local" name="expiry_date" />
                </label>
              </fieldset>
              <label>
                Reason for this administrative action (at least 10 characters)
                <input name="audit_reason" type="text" required minLength={10} maxLength={500} />
              </label>
              <div className="platform-modal-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowGrantForm(false)}
                >
                  Cancel
                </button>
                <button type="submit">Grant complimentary access</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {showRevokeForm && (
        <div
          className="platform-modal-backdrop"
          role="presentation"
          onClick={() => setShowRevokeForm(false)}
        >
          <div
            className="platform-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="revoke-complimentary-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="revoke-complimentary-title">Remove complimentary access</h2>
            <p>
              This Home will return to its Free plan entitlements.
              <br />
              Existing Home data will not be deleted.
              <br />
              Features or resources above Free-plan limits may become restricted in a later
              phase.
            </p>
            <form
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                void revokeComplimentary(new FormData(event.currentTarget));
              }}
            >
              <label>
                Reason for this administrative action (at least 10 characters)
                <input name="audit_reason" type="text" required minLength={10} maxLength={500} />
              </label>
              <div className="platform-modal-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowRevokeForm(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="danger">
                  Remove complimentary access
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {showReconcileForm && (
        <div
          className="platform-modal-backdrop"
          role="presentation"
          onClick={() => setShowReconcileForm(false)}
        >
          <div
            className="platform-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reconcile-stripe-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="reconcile-stripe-title">Reconcile with Stripe</h2>
            <p>
              Re-fetches this Home&rsquo;s subscription directly from Stripe and re-applies it
              through the same logic webhooks use. Use this if the Home&rsquo;s state here looks
              out of date compared to Stripe.
            </p>
            <form
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                void reconcileStripe(new FormData(event.currentTarget));
              }}
            >
              <label>
                Reason for this administrative action (at least 10 characters)
                <input name="audit_reason" type="text" required minLength={10} maxLength={500} />
              </label>
              <div className="platform-modal-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowReconcileForm(false)}
                >
                  Cancel
                </button>
                <button type="submit">Reconcile</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {modal}
    </PlatformShell>
  );
}
