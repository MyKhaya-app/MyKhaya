"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime, titleCase } from "@/components/platform-format";
import type {
  StripeConfiguration,
  StripeModeSettings,
  StripeTestConnectionResponse,
} from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge, toneFromStateClass } from "@/components/control-centre/badge";
import { CcSection } from "@/components/control-centre/section";
import { CcConfirmDialog } from "@/components/control-centre/dialog";

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
        acquisition_enabled: form.get("acquisition_enabled") === "on",
        mode: form.get("mode"),
        test_publishable_key: str("test_publishable_key"),
        test_secret_key: str("test_secret_key"),
        test_webhook_secret: str("test_webhook_secret"),
        test_family_monthly_price_id: str("test_family_monthly_price_id"),
        test_family_annual_price_id: str("test_family_annual_price_id"),
        live_publishable_key: str("live_publishable_key"),
        live_secret_key: str("live_secret_key"),
        live_webhook_secret: str("live_webhook_secret"),
        live_family_monthly_price_id: str("live_family_monthly_price_id"),
        live_family_annual_price_id: str("live_family_annual_price_id"),
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

  function modeFields(mode: "test" | "live", settings: StripeModeSettings, danger: boolean) {
    return (
      <CcSection
        title={mode === "test" ? "Test configuration" : "Live configuration"}
        tone={danger ? "danger" : "default"}
        description={
          mode === "live"
            ? "These are production Stripe credentials — changes here affect real billing."
            : "Sandbox Stripe credentials, safe to experiment with."
        }
      >
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
          Monthly Price ID
          <input
            name={`${mode}_family_monthly_price_id`}
            defaultValue={settings.family_monthly_price_id ?? ""}
            maxLength={200}
          />
        </label>
        <label>
          Annual Price ID
          <input
            name={`${mode}_family_annual_price_id`}
            defaultValue={settings.family_annual_price_id ?? ""}
            maxLength={200}
          />
        </label>
      </CcSection>
    );
  }

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Payments"
          title="Stripe"
          description="Configure and test the Stripe integration used for Family billing. Secret values are never shown after they are stored — only whether one is configured and its last few characters."
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
            <CcSection title="Status">
              <dl>
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
                  <dd>{titleCase(data.source)}</dd>
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
                <p className="notice">
                  Managed by the deployment environment (MYKHAYA_STRIPE_BILLING_CONFIGURED). These fields
                  cannot be changed here — edit the server&apos;s .env and redeploy.
                </p>
              )}
            </CcSection>

            <form onSubmit={saveSettings}>
              <fieldset disabled={!data.editable}>
                <CcSection title="Mode">
                  <label className="check-row">
                    <input type="checkbox" name="enabled" defaultChecked={data.enabled} /> Integration enabled
                  </label>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      name="acquisition_enabled"
                      defaultChecked={data.acquisition_enabled}
                    /> Allow new Family subscriptions
                  </label>
                  <p><small>Pause new paid sign-ups without disabling renewals, webhooks, cancellations, or the customer portal.</small></p>
                  <label className="check-row">
                    <input
                      type="radio"
                      name="mode"
                      value="test"
                      checked={selectedMode === "test"}
                      onChange={() => setSelectedMode("test")}
                    />{" "}
                    Test
                  </label>
                  <label className="check-row">
                    <input
                      type="radio"
                      name="mode"
                      value="live"
                      checked={selectedMode === "live"}
                      onChange={() => setSelectedMode("live")}
                    />{" "}
                    Live
                  </label>
                  {selectedMode === "live" && (
                    <CcNotice tone="warning">
                      Selecting Live mode makes real Stripe billing active once saved. Existing Homes,
                      webhooks, renewals and cancellations are never affected by this switch by themselves.
                    </CcNotice>
                  )}
                </CcSection>

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
