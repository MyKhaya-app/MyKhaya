"use client";

import { use, useCallback, useEffect, useState } from "react";
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
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard, CcColumns } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge, toneFromStateClass } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcConfirmDialog } from "@/components/control-centre/dialog";

const ENTITLEMENT_LABELS: Record<string, string> = {
  "lists.enabled": "Lists",
  "chores.enabled": "Chores",
  "notes.enabled": "Notes",
  "wishlists.enabled": "Wishlists",
};

const LIMIT_LABELS: Record<string, string> = {
  "calendar.max_calendars": "Calendar maximum",
};

type EntitlementRow = { key: string; label: string; value: string; warning?: boolean };

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

  const entitlementRows: EntitlementRow[] = data
    ? [
        ...Object.entries(data.entitlements.limits).map(([key, value]) => ({
          key,
          label: LIMIT_LABELS[key] ?? key,
          value: value === null ? "Unlimited" : String(value),
        })),
        ...Object.entries(data.entitlements.booleans).map(([key, value]) => ({
          key,
          label: ENTITLEMENT_LABELS[key] ?? key,
          value: value ? "Enabled" : "Not available",
        })),
        {
          key: "calendar_usage",
          label: "Current calendars",
          value: String(data.calendar_usage.count),
          warning: data.calendar_usage.over_limit,
        },
      ]
    : [];

  const entitlementColumns: CcTableColumn<EntitlementRow>[] = [
    { key: "entitlement", header: "Entitlement", render: (row) => row.label },
    {
      key: "value",
      header: "Value",
      render: (row) => (
        <>
          {row.value}
          {row.warning && (
            <>
              {" "}
              <CcBadge tone="warning">Over plan limit</CcBadge>
            </>
          )}
        </>
      ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Commercial detail"
          title={data?.name ?? "Home"}
          meta={
            data && (
              <>
                <span>
                  Home ID <code>{data.id}</code>
                </span>
                <span>Created {readableDate(data.created_at)}</span>
                <span>{data.member_count} members</span>
              </>
            )
          }
          secondaryActions={
            <>
              <Link href="/subscriptions" className="secondary">
                Back to Subscriptions
              </Link>
              <button className="secondary" onClick={() => void load()}>
                Refresh
              </button>
            </>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}
        {!data ? (
          <p role="status">Loading…</p>
        ) : (
          <CcColumns ratio="2-1">
            <div>
              <CcSection title="Home">
                <CcCard>
                  <CcMetadataGrid dense>
                    <CcMetadataItem label="Home ID">
                      <code>{data.id}</code>
                    </CcMetadataItem>
                    <CcMetadataItem label="Created">{readableDate(data.created_at)}</CcMetadataItem>
                    <CcMetadataItem label="Members">{data.member_count}</CcMetadataItem>
                  </CcMetadataGrid>
                  {data.administrators.length > 0 && (
                    <div className="record-list" style={{ marginTop: "0.9rem" }}>
                      {data.administrators.map((admin) => (
                        <article key={admin.user_id}>
                          <strong>{admin.display_name}</strong>
                          <span>{admin.email}</span>
                        </article>
                      ))}
                    </div>
                  )}
                </CcCard>
              </CcSection>

              <CcSection title="Commercial state">
                <CcCard>
                  <CcMetadataGrid>
                    <CcMetadataItem label="Stored plan">
                      <CcBadge tone={toneFromStateClass(planBadgeClass(data.subscription.plan))}>
                        {planLabel(data.subscription.plan)}
                      </CcBadge>
                    </CcMetadataItem>
                    <CcMetadataItem label="Effective plan">
                      <CcBadge
                        tone={toneFromStateClass(planBadgeClass(data.subscription.effective_plan))}
                      >
                        {planLabel(data.subscription.effective_plan)}
                      </CcBadge>
                    </CcMetadataItem>
                    <CcMetadataItem label="Provider">
                      <CcBadge tone={toneFromStateClass(providerBadgeClass(data.subscription.provider))}>
                        {providerLabel(data.subscription.provider)}
                      </CcBadge>
                    </CcMetadataItem>
                    <CcMetadataItem label="Status">
                      <CcBadge tone={toneFromStateClass(statusBadgeClass(data.subscription.status))}>
                        {statusLabel(data.subscription.status)}
                      </CcBadge>
                    </CcMetadataItem>
                    {data.subscription.complimentary_reason && (
                      <CcMetadataItem label="Complimentary reason">
                        {data.subscription.complimentary_reason}
                      </CcMetadataItem>
                    )}
                    {data.subscription.complimentary_granted_by_display_name && (
                      <CcMetadataItem label="Granted by">
                        {data.subscription.complimentary_granted_by_display_name}
                      </CcMetadataItem>
                    )}
                    {data.subscription.complimentary_granted_at && (
                      <CcMetadataItem label="Granted">
                        {readableDate(data.subscription.complimentary_granted_at)}
                      </CcMetadataItem>
                    )}
                    {data.subscription.complimentary_expires_at && (
                      <CcMetadataItem label="Complimentary expiry">
                        {readableDate(data.subscription.complimentary_expires_at)}
                      </CcMetadataItem>
                    )}
                    {data.subscription.billing_interval && (
                      <CcMetadataItem label="Billing interval">
                        {data.subscription.billing_interval === "month" ? "Monthly" : "Annual"}
                      </CcMetadataItem>
                    )}
                    {data.stripe_price && (
                      <CcMetadataItem label="Current price">
                        {data.stripe_price.formatted_amount} / {data.subscription.billing_interval}
                      </CcMetadataItem>
                    )}
                    {data.subscription.external_customer_id && (
                      <CcMetadataItem label="External customer ID">
                        <code>{data.subscription.external_customer_id}</code>
                      </CcMetadataItem>
                    )}
                    {data.subscription.external_subscription_id && (
                      <CcMetadataItem label="External subscription ID">
                        <code>{data.subscription.external_subscription_id}</code>
                      </CcMetadataItem>
                    )}
                    {data.stripe_price && (
                      <CcMetadataItem label="Stripe price ID">
                        <code>{data.subscription.external_price_id}</code>
                      </CcMetadataItem>
                    )}
                    {data.subscription.complimentary_note && (
                      <CcMetadataItem label="Internal note (Platform Admin only)" span>
                        {data.subscription.complimentary_note}
                      </CcMetadataItem>
                    )}
                    {hasEffectiveDivergence(data.subscription.plan, data.subscription.effective_plan) && (
                      <CcMetadataItem label="Why effective differs from stored" span>
                        {data.subscription.effective_status_reason}
                      </CcMetadataItem>
                    )}
                  </CcMetadataGrid>
                  {(data.stripe_dashboard_customer_url || data.stripe_dashboard_subscription_url) && (
                    <div className="platform-modal-actions" style={{ justifyContent: "flex-start" }}>
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
                </CcCard>
              </CcSection>

              <CcSection title={`Entitlements (${planLabel(data.entitlements.plan)})`}>
                <CcTable
                  columns={entitlementColumns}
                  rows={entitlementRows}
                  rowKey={(row) => row.key}
                  caption="Entitlements"
                />
              </CcSection>

              <CcSection title="Commercial event history">
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
              </CcSection>

              {data.subscription.provider === "stripe" && (
                <CcSection
                  title="Recent Stripe webhook events"
                  description={
                    'Support diagnostics for "I paid but I\'m still on Free" — did Stripe\'s webhook actually arrive for this Home.'
                  }
                >
                  {data.recent_webhook_events.length === 0 ? (
                    <p className="quiet-state">No webhook events recorded yet for this Home.</p>
                  ) : (
                    <div className="record-list">
                      {data.recent_webhook_events.map((event) => (
                        <article key={event.id}>
                          <strong>{event.event_type}</strong>{" "}
                          <CcBadge tone={event.outcome === "processed" ? "success" : "neutral"}>
                            {event.outcome}
                          </CcBadge>
                          <time dateTime={event.received_at}>{readableDate(event.received_at)}</time>
                        </article>
                      ))}
                    </div>
                  )}
                </CcSection>
              )}
            </div>

            <div>
              <CcSection title="Complimentary access">
                <CcCard>
                  {data.subscription.provider === "stripe" && data.subscription.status !== "cancelled" ? (
                    <CcNotice tone="error">
                      This Home has an active Stripe subscription. Complimentary access cannot be
                      granted while it is still billing — the Stripe subscription must be cancelled
                      first (via the Customer Portal or Stripe directly).
                    </CcNotice>
                  ) : data.subscription.provider === "complimentary" ? (
                    <>
                      <p>This Home currently has complimentary Family access.</p>
                      <div className="platform-modal-actions" style={{ justifyContent: "flex-start" }}>
                        <button className="secondary" onClick={() => setShowGrantForm(true)}>
                          Extend / update
                        </button>
                      </div>
                      <div className="cc-section-danger" style={{ marginTop: "1rem" }}>
                        <p style={{ marginTop: 0 }}>
                          Removing complimentary access returns this Home to Free immediately.
                        </p>
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
                </CcCard>
              </CcSection>

              {data.subscription.provider === "stripe" && (
                <CcSection title="Stripe">
                  <CcCard>
                    <p>
                      This Home&rsquo;s commercial state is driven by Stripe. Provider, plan and
                      status cannot be edited directly here — reconciliation re-fetches Stripe&rsquo;s
                      own current subscription state and re-applies it through the same logic
                      webhooks use.
                    </p>
                    <button className="secondary" onClick={() => setShowReconcileForm(true)}>
                      Reconcile with Stripe
                    </button>
                  </CcCard>
                </CcSection>
              )}
            </div>
          </CcColumns>
        )}
      </CcPage>

      <CcConfirmDialog
        open={showGrantForm}
        onClose={() => setShowGrantForm(false)}
        title="Grant complimentary Family access"
        description="This gives the Home Family-plan entitlements without payment — for beta testers, friends and family, or internal use. It never touches Stripe."
        confirmLabel="Grant complimentary access"
        onConfirm={grantComplimentary}
        extraFields={
          <>
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
          </>
        }
      />

      <CcConfirmDialog
        open={showRevokeForm}
        onClose={() => setShowRevokeForm(false)}
        title="Remove complimentary access"
        description={
          <>
            This Home will return to its Free plan entitlements.
            <br />
            Existing Home data will not be deleted.
            <br />
            Features or resources above Free-plan limits may become restricted in a later phase.
          </>
        }
        confirmLabel="Remove complimentary access"
        variant="destructive"
        onConfirm={revokeComplimentary}
      />

      <CcConfirmDialog
        open={showReconcileForm}
        onClose={() => setShowReconcileForm(false)}
        title="Reconcile with Stripe"
        description="Re-fetches this Home's subscription directly from Stripe and re-applies it through the same logic webhooks use. Use this if the Home's state here looks out of date compared to Stripe."
        confirmLabel="Reconcile"
        onConfirm={reconcileStripe}
      />

      {modal}
    </PlatformShell>
  );
}
