"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime, titleCase } from "@/components/platform-format";
import type {
  StripeCheckoutInspection,
  StripeConfiguration,
  StripeModeSettings,
  StripeTestConnectionResponse,
} from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge, toneFromStateClass, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcCard, CcSection } from "@/components/control-centre/section";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import {
  AlertTriangle,
  BookOpen,
  CreditCard,
  Database,
  FileKey2,
  Info,
  Link2,
  Settings2,
  ShieldCheck,
  UsersRound,
  Wrench,
} from "lucide-react";

type SecretField = "test_secret_key" | "test_webhook_secret" | "live_secret_key" | "live_webhook_secret";

const SECRET_FIELD_LABELS: Record<SecretField, string> = {
  test_secret_key: "Test secret key",
  test_webhook_secret: "Test webhook secret",
  live_secret_key: "Live secret key",
  live_webhook_secret: "Live webhook secret",
};

function maskedPlaceholder(settings: StripeModeSettings, kind: "secret" | "webhook"): string {
  const configured = kind === "secret" ? settings.secret_key_configured : settings.webhook_secret_configured;
  const last4 = kind === "secret" ? settings.secret_key_last4 : settings.webhook_secret_last4;
  if (!configured) return "Not configured";
  return last4 ? `••••••••••••${last4}` : "••••••••••••";
}

export default function PaymentsPage() {
  const [data, setData] = useState<StripeConfiguration | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<StripeTestConnectionResponse | null>(null);
  const [clearField, setClearField] = useState<SecretField | null>(null);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [selectedMode, setSelectedMode] = useState<"test" | "live">("test");
  const [inspection, setInspection] = useState<StripeCheckoutInspection | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const result = await platformApi.get<StripeConfiguration>("/payments/stripe");
      setData(result);
      setSelectedMode(result.mode);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load Stripe configuration.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const str = (name: string) => (form.get(name) as string | null) || null;
    try {
      const result = await platformApi.put<{ message: string }>("/payments/stripe/settings", {
        enabled: form.get("enabled") === "on",
        acquisition_enabled:
          form.get("family_signups_enabled") === "on" ||
          form.get("ultimate_signups_enabled") === "on",
        family_signups_enabled: form.get("family_signups_enabled") === "on",
        ultimate_signups_enabled: form.get("ultimate_signups_enabled") === "on",
        mode: form.get("mode"),
        test_publishable_key: str("test_publishable_key"),
        test_secret_key: str("test_secret_key"),
        test_webhook_secret: str("test_webhook_secret"),
        test_family_monthly_price_id: str("test_family_monthly_price_id"),
        test_family_annual_price_id: str("test_family_annual_price_id"),
        test_ultimate_monthly_price_id: str("test_ultimate_monthly_price_id"),
        test_ultimate_annual_price_id: str("test_ultimate_annual_price_id"),
        live_publishable_key: str("live_publishable_key"),
        live_secret_key: str("live_secret_key"),
        live_webhook_secret: str("live_webhook_secret"),
        live_family_monthly_price_id: str("live_family_monthly_price_id"),
        live_family_annual_price_id: str("live_family_annual_price_id"),
        live_ultimate_monthly_price_id: str("live_ultimate_monthly_price_id"),
        live_ultimate_annual_price_id: str("live_ultimate_annual_price_id"),
        reason: form.get("reason"),
        confirmed: true,
      });
      setMessage(result.message);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save Stripe settings.");
    } finally {
      setSaving(false);
    }
  }

  async function clearSecret(formData: FormData) {
    if (!clearField) return;
    setError("");
    setMessage("");
    try {
      const result = await platformApi.post<{ message: string }>("/payments/stripe/settings/clear-secret", {
        field: clearField,
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage(result.message);
      setClearField(null);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not clear the stored secret.");
    }
  }

  async function testConnection(formData: FormData) {
    setTesting(true);
    setError("");
    setMessage("");
    setTestResult(null);
    try {
      const result = await platformApi.post<StripeTestConnectionResponse>("/payments/stripe/test-connection", {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setTestResult(result);
      setTestDialogOpen(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not test the Stripe connection.");
    } finally {
      setTesting(false);
    }
  }

  async function inspectCheckout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setInspection(null);
    const form = new FormData(event.currentTarget);
    try {
      const result = await platformApi.post<StripeCheckoutInspection>(
        "/payments/stripe/inspect-checkout",
        {
          session_id: form.get("inspection_session_id"),
          reason: form.get("inspection_reason"),
          confirmed: true,
        },
      );
      setInspection(result);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not inspect that Checkout Session.");
    }
  }

  function modeFields(mode: "test" | "live", settings: StripeModeSettings, danger: boolean) {
    return (
      <CcCard
        className={`pcc-payment-card pcc-payment-configuration-card ${danger ? "pcc-payment-live-card" : ""}`}
        title={mode === "test" ? "Test configuration" : "Live configuration"}
        icon={Wrench}
        description={
          mode === "live"
            ? "These are production Stripe credentials — changes here affect real billing."
            : "Sandbox Stripe credentials, safe to experiment with."
        }
      >
        <div className="pcc-payment-fields-grid">
        <label>
          Publishable key
          <input name={`${mode}_publishable_key`} defaultValue={settings.publishable_key ?? ""} maxLength={200} />
        </label>
        <label>
          Secret key
          <input
            name={`${mode}_secret_key`}
            type="password"
            autoComplete="new-password"
            placeholder={maskedPlaceholder(settings, "secret")}
            maxLength={500}
          />
        </label>
        {settings.secret_key_configured && (
          <p>
            <small>A secret key is currently stored.</small>{" "}
            <button
              type="button"
              className="secondary"
              onClick={() => setClearField(mode === "test" ? "test_secret_key" : "live_secret_key")}
            >
              Remove
            </button>
          </p>
        )}
        <label>
          Webhook signing secret
          <input
            name={`${mode}_webhook_secret`}
            type="password"
            autoComplete="new-password"
            placeholder={maskedPlaceholder(settings, "webhook")}
            maxLength={500}
          />
        </label>
        {settings.webhook_secret_configured && (
          <p>
            <small>A webhook secret is currently stored.</small>{" "}
            <button
              type="button"
              className="secondary"
              onClick={() => setClearField(mode === "test" ? "test_webhook_secret" : "live_webhook_secret")}
            >
              Remove
            </button>
          </p>
        )}
        <label>
          Family monthly Price ID
          <input
            name={`${mode}_family_monthly_price_id`}
            defaultValue={settings.family_monthly_price_id ?? ""}
            maxLength={200}
          />
        </label>
        <label>
          Family annual Price ID
          <input
            name={`${mode}_family_annual_price_id`}
            defaultValue={settings.family_annual_price_id ?? ""}
            maxLength={200}
          />
        </label>
        <label>
          Ultimate monthly Price ID
          <input
            name={`${mode}_ultimate_monthly_price_id`}
            defaultValue={settings.ultimate_monthly_price_id ?? ""}
            maxLength={200}
          />
        </label>
        <label>
          Ultimate annual Price ID
          <input
            name={`${mode}_ultimate_annual_price_id`}
            defaultValue={settings.ultimate_annual_price_id ?? ""}
            maxLength={200}
          />
        </label>
        </div>
      </CcCard>
    );
  }

  return (
    <PlatformShell>
      <CcPage wide className="pcc-payments-page">
        <CcPageHeader
          eyebrow="Billing & payments"
          title="Payments"
          description="Manage your Stripe billing integration, subscriptions and credentials. Enable payments for new subscriptions and securely process payments through Stripe."
          primaryAction={
            <aside className="pcc-payments-how-it-works">
              <span className="pcc-payments-how-icon"><BookOpen size={21} aria-hidden="true" /></span>
              <div>
                <strong>How this works</strong>
                <p>Connect your Stripe account to enable payments, manage subscription sign-ups, and configure test or live credentials.</p>
              </div>
            </aside>
          }
          secondaryActions={
            <button className="secondary" onClick={() => void load()}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}
        {testResult && (
          <CcNotice tone={testResult.result === "connected" ? "success" : "error"}>
            {testResult.detail}
          </CcNotice>
        )}

        {!data ? (
          <p role="status">Loading Stripe configuration…</p>
        ) : (
          <>
            {!data.enabled && (
              <div className="pcc-payments-warning" role="status">
                <AlertTriangle size={22} aria-hidden="true" />
                <div>
                  <strong>Stripe is disabled</strong>
                  <span>The Stripe billing integration is currently disabled. Enable it to allow new subscriptions and process payments.</span>
                </div>
              </div>
            )}

            <div className="pcc-payments-summary-grid" aria-label="Payment summary">
              {[
                { label: "Integration", value: data.enabled ? "Enabled" : "Disabled", tone: data.enabled ? "success" : "danger", icon: Link2 },
                { label: "Active mode", value: data.mode === "live" ? "Live" : "Test", tone: data.mode === "live" ? "danger" : "info", icon: Database },
                { label: "New subscriptions", value: data.acquisition_enabled ? "Allowed" : "Paused", tone: data.acquisition_enabled ? "success" : "warning", icon: UsersRound },
                { label: "Configuration source", value: titleCase(data.source), tone: data.source === "unconfigured" ? "neutral" : "info", icon: FileKey2 },
                { label: "Credentials", value: data.configured ? "Configured" : "Incomplete", tone: data.configured ? "success" : "danger", icon: ShieldCheck },
              ].map(({ label, value, tone, icon: Icon }) => (
                <div className="pcc-payments-summary-card" key={label}>
                  <span className={`pcc-payments-summary-icon pcc-payments-summary-icon-${tone}`}><Icon size={20} aria-hidden="true" /></span>
                  <span><small>{label}</small><CcBadge tone={tone as CcBadgeTone}>{value}</CcBadge></span>
                </div>
              ))}
            </div>

            <CcCard
              className="pcc-payment-card pcc-payment-status-card"
              title="Stripe status"
              description="Current state of your Stripe billing integration and configuration."
              icon={CreditCard}
              actions={
                <button type="button" className="secondary" onClick={() => setTestDialogOpen(true)} disabled={testing}>
                  <Link2 size={15} aria-hidden="true" /> {testing ? "Testing…" : "Test connection"}
                </button>
              }
            >
              <dl className="pcc-payment-status-grid">
                <div>
                  <dt>Integration</dt>
                  <dd>
                    <CcBadge tone={data.enabled ? "success" : "neutral"}>
                      {data.enabled ? "Enabled" : "Disabled"}
                    </CcBadge>
                  </dd>
                </div>
                <div>
                  <dt>Active mode</dt>
                  <dd>
                    <CcBadge tone={data.mode === "live" ? "danger" : "info"}>
                      {data.mode === "live" ? "Live" : "Test"}
                    </CcBadge>
                  </dd>
                </div>
                <div>
                  <dt>Configuration source</dt>
                  <dd><CcBadge tone={data.source === "unconfigured" ? "neutral" : "info"}>{titleCase(data.source)}</CcBadge></dd>
                </div>
                <div>
                  <dt>Configured</dt>
                  <dd>
                    <CcBadge tone={data.configured ? "success" : "warning"}>
                      {data.configured ? "Yes" : "No"}
                    </CcBadge>
                  </dd>
                </div>
                <div>
                  <dt>New subscriptions</dt>
                  <dd>
                    <CcBadge tone={data.acquisition_enabled ? "success" : "warning"}>
                      {data.acquisition_enabled ? "Allowed" : "Paused"}
                    </CcBadge>
                  </dd>
                </div>
                {data.incomplete_reason && (
                  <div>
                    <dt>Diagnostic</dt>
                    <dd>{data.incomplete_reason}</dd>
                  </div>
                )}
              </dl>
              {!data.editable && (
                <p className="notice pcc-payment-environment-note">
                  Managed by the deployment environment (MYKHAYA_STRIPE_BILLING_CONFIGURED). These fields
                  cannot be changed here — edit the server&apos;s .env and redeploy.
                </p>
              )}
            </CcCard>

            <form onSubmit={saveSettings}>
              <fieldset disabled={!data.editable}>
                <CcCard
                  className="pcc-payment-card pcc-payment-controls-card"
                  title="Mode and subscription controls"
                  description="Configure how Stripe integration behaves and control new subscription sign-ups."
                  icon={Settings2}
                >
                  <div className="pcc-payment-controls-grid">
                    <div className="pcc-payment-toggle-list">
                      {[
                        ["enabled", "Integration enabled", "Connect and enable the Stripe billing integration.", data.enabled],
                        ["family_signups_enabled", "Allow new Family subscriptions", "Allow new Family plan sign-ups through Stripe.", data.family_signups_enabled ?? data.acquisition_enabled],
                        ["ultimate_signups_enabled", "Allow new Ultimate subscriptions", "Allow new Ultimate plan sign-ups through Stripe.", data.ultimate_signups_enabled],
                      ].map(([name, label, description, checked]) => (
                        <label className="pcc-payment-toggle" key={name as string}>
                          <span><strong>{label as string}</strong><small>{description as string}</small></span>
                          <input type="checkbox" name={name as string} defaultChecked={checked as boolean} />
                          <span className="pcc-payment-toggle-track" aria-hidden="true"><span /></span>
                        </label>
                      ))}
                      <p className="pcc-payment-info-note"><Info size={16} aria-hidden="true" /> Pausing new paid sign-ups does not disable existing renewals, webhooks, cancellations, or the customer portal.</p>
                    </div>
                    <div className="pcc-payment-mode-selector">
                      <div className="pcc-payment-subheading"><strong>Stripe mode</strong><small>Choose which Stripe environment to use for processing payments.</small></div>
                      <label className={`pcc-payment-radio-card ${selectedMode === "test" ? "is-selected" : ""}`}>
                        <input type="radio" name="mode" value="test" checked={selectedMode === "test"} onChange={() => setSelectedMode("test")} />
                        <span className="pcc-payment-radio-mark" aria-hidden="true"><span /></span>
                        <span><strong>Test mode</strong><small>Use Stripe&apos;s test environment for sandbox payments.</small></span>
                      </label>
                      <label className={`pcc-payment-radio-card ${selectedMode === "live" ? "is-selected" : ""}`}>
                        <input type="radio" name="mode" value="live" checked={selectedMode === "live"} onChange={() => setSelectedMode("live")} />
                        <span className="pcc-payment-radio-mark" aria-hidden="true"><span /></span>
                        <span><strong>Live mode</strong><small>Use Stripe&apos;s live environment for real payments.</small></span>
                      </label>
                      {selectedMode === "live" && (
                        <CcNotice tone="warning">
                          Selecting Live mode makes real Stripe billing active once saved. Existing Homes,
                          webhooks, renewals and cancellations are never affected by this switch by themselves.
                        </CcNotice>
                      )}
                    </div>
                  </div>
                </CcCard>

                {modeFields("test", data.test, false)}
                {modeFields("live", data.live, true)}

                <CcSection title="Webhook">
                  <dl>
                    <div>
                      <dt>Endpoint</dt>
                      <dd>{data.webhook.endpoint_url ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>
                        <CcBadge tone={toneFromStateClass(`state-${data.webhook.state}`)}>
                          {data.webhook.state}
                        </CcBadge>
                      </dd>
                    </div>
                    <div>
                      <dt>Last received</dt>
                      <dd>{data.webhook.last_event_at ? relativeTime(data.webhook.last_event_at) : "No webhook received yet"}</dd>
                    </div>
                    <div>
                      <dt>Recent failures (24h)</dt>
                      <dd>{data.webhook.recent_failure_count}</dd>
                    </div>
                  </dl>
                </CcSection>

                <label>
                  Reason for change
                  <input name="reason" minLength={10} maxLength={500} required />
                </label>
                <button disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
              </fieldset>
            </form>

            <CcSection title="Connection test">
              <p>
                Makes one safe, read-only request to Stripe using the currently active mode&apos;s
                credentials. This never creates a charge, customer or subscription.
              </p>
              <button type="button" onClick={() => setTestDialogOpen(true)} disabled={testing}>
                {testing ? "Testing…" : "Test Stripe connection"}
              </button>
            </CcSection>

            <CcSection title="Billing diagnostics">
              <dl>
                <div>
                  <dt>Last checkout confirmation</dt>
                  <dd>
                    {data.diagnostics.latest_checkout
                      ? `${relativeTime(data.diagnostics.latest_checkout.created_at)} — ${titleCase(data.diagnostics.latest_checkout.result)}`
                      : "None"}
                  </dd>
                </div>
                <div>
                  <dt>Last webhook</dt>
                  <dd>
                    {data.diagnostics.latest_webhook
                      ? `${relativeTime(data.diagnostics.latest_webhook.created_at)} — ${titleCase(data.diagnostics.latest_webhook.result)}`
                      : "None"}
                  </dd>
                </div>
                <div>
                  <dt>Last reconciliation</dt>
                  <dd>
                    {data.diagnostics.latest_reconciliation
                      ? `${relativeTime(data.diagnostics.latest_reconciliation.created_at)} — ${titleCase(data.diagnostics.latest_reconciliation.result)}`
                      : "None"}
                  </dd>
                </div>
              </dl>
              {data.diagnostics.latest && (
                <div className="notice">
                  <strong>Latest result: {titleCase(data.diagnostics.latest.result)}</strong>
                  <p>
                    Stage: {data.diagnostics.latest.stage}
                    {data.diagnostics.latest.safe_error_message
                      ? ` — ${data.diagnostics.latest.safe_error_message}`
                      : ""}
                  </p>
                  {data.diagnostics.latest.checkout_session_id && (
                    <p>Checkout Session: {data.diagnostics.latest.checkout_session_id}</p>
                  )}
                  {data.diagnostics.latest.stripe_subscription_id && (
                    <p>Subscription: {data.diagnostics.latest.stripe_subscription_id}</p>
                  )}
                  <p>
                    Stored plan: {data.diagnostics.latest.stored_plan ?? "None"}; Effective plan:{" "}
                    {data.diagnostics.latest.effective_plan ?? "None"}
                  </p>
                </div>
              )}
            </CcSection>

            <CcSection title="Inspect Checkout">
              <p><small>Read-only lookup for a Stripe Checkout Session. This does not change billing state.</small></p>
              <form onSubmit={inspectCheckout}>
                <label>
                  Checkout Session ID
                  <input name="inspection_session_id" placeholder="cs_..." pattern="cs_[A-Za-z0-9_]+" required />
                </label>
                <label>
                  Reason for inspection
                  <input name="inspection_reason" minLength={10} maxLength={500} required />
                </label>
                <button type="submit">Inspect Checkout</button>
              </form>
              {inspection && (
                <dl>
                  <div><dt>Session</dt><dd>{inspection.session_exists ? "Found" : "Not found"}</dd></div>
                  <div><dt>Status</dt><dd>{inspection.status ?? "Unknown"}</dd></div>
                  <div><dt>Payment</dt><dd>{inspection.payment_status ?? "Unknown"}</dd></div>
                  <div><dt>Home reference</dt><dd>{inspection.home_reference}</dd></div>
                  <div><dt>Customer</dt><dd>{inspection.customer_id ?? "None"}</dd></div>
                  <div><dt>Subscription</dt><dd>{inspection.subscription_id ?? "None"}</dd></div>
                  <div><dt>Price matched</dt><dd>{inspection.configured_price_matched ? "Yes" : "No"}</dd></div>
                  <div><dt>Subscription status</dt><dd>{inspection.subscription_status ?? "Unknown"}</dd></div>
                </dl>
              )}
            </CcSection>
          </>
        )}

        <CcConfirmDialog
          open={clearField !== null}
          onClose={() => setClearField(null)}
          title={`Remove ${clearField ? SECRET_FIELD_LABELS[clearField] : ""}?`}
          description="This clears the stored value. Billing operations using this mode will stop working until a new value is saved."
          confirmLabel="Remove"
          variant="destructive"
          onConfirm={clearSecret}
        />

        <CcConfirmDialog
          open={testDialogOpen}
          onClose={() => setTestDialogOpen(false)}
          title="Test Stripe connection?"
          description="This makes one read-only request to Stripe using the currently active mode."
          confirmLabel="Run test"
          onConfirm={testConnection}
        />
      </CcPage>
    </PlatformShell>
  );
}
