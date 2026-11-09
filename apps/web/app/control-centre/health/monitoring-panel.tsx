"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { relativeTime, readableDate } from "@/components/platform-format";
import { CcBadge } from "@/components/control-centre/badge";
import { CcCard, CcSection } from "@/components/control-centre/section";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcRecordCard, CcRecordList } from "@/components/control-centre/record-list";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcConfirmDialog, CcDialog } from "@/components/control-centre/dialog";
import { CcEmptyState, CcLoadingState, CcNotice } from "@/components/control-centre/status-message";
import { PUBLIC_SERVICE_OPTIONS } from "@/components/platform-types";
import { serviceStateLabel, serviceStateTone } from "@/components/status-incidents-logic";
import type { PublicStatusState } from "@/components/platform-types";
import {
  alertKindLabel,
  alertKindTone,
  componentStateLabel,
  componentStateTone,
  deliverySummary,
  formatInterval,
  formatLatency,
  hasFailedDelivery,
  publicReportingNote,
  sortComponents,
  suppressionLabel,
  type AlertSettings,
  type MonitorAlert,
  type MonitorComponent,
  type MonitoringOverview,
} from "@/components/monitoring-logic";

type History = {
  key: string;
  name: string;
  observations: {
    observed_at: string;
    outcome: string;
    latency_ms: number | null;
    failure_label: string | null;
    detail: string | null;
    trigger: string;
  }[];
  transitions: { occurred_at: string; from_state: string; to_state: string; failure_label: string | null }[];
};

type PendingAction =
  | { type: "run"; component: MonitorComponent }
  | { type: "configure"; component: MonitorComponent }
  | { type: "simulate"; component: MonitorComponent }
  | { type: "clear-simulation"; component: MonitorComponent }
  | { type: "override" }
  | { type: "revoke"; id: string; serviceName: string }
  | { type: "resend"; alert: MonitorAlert }
  | { type: "alert-settings" }
  | { type: "my-alerts"; receive: boolean };

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

// FormData values are strings for every field this panel renders (no file
// inputs); anything else is treated as empty.
function field(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

function reasonOf(form: FormData): string {
  return field(form, "audit_reason").trim();
}

/**
 * Automated monitoring section of the PCC Health page: the persisted state
 * of every monitored component and external dependency, the alert centre,
 * overrides and alert recipients. Unlike the live diagnostics cards above
 * it, everything here comes from stored observations the scheduler's
 * runner records continuously, so it also shows when monitoring itself has
 * stopped.
 */
export function MonitoringPanel() {
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [alerts, setAlerts] = useState<MonitorAlert[] | null>(null);
  const [alertSettings, setAlertSettings] = useState<AlertSettings | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [nextOverview, nextAlerts, nextSettings] = await Promise.all([
        platformApi.get<MonitoringOverview>("/monitoring"),
        platformApi.get<{ items: MonitorAlert[] }>("/monitoring/alerts"),
        platformApi.get<AlertSettings>("/monitoring/alert-settings"),
      ]);
      // Never render a payload we don't recognise (e.g. an older API build
      // without monitoring): say monitoring is unavailable instead.
      if (
        !Array.isArray(nextOverview?.components) ||
        !Array.isArray(nextAlerts?.items) ||
        !Array.isArray(nextSettings?.roles)
      ) {
        throw new Error("unexpected monitoring payload");
      }
      setOverview(nextOverview);
      setAlerts(nextAlerts.items);
      setAlertSettings(nextSettings);
    } catch (cause) {
      setError(safeError(cause, "Automated monitoring is unavailable."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function showHistory(component: MonitorComponent) {
    try {
      setHistory(
        await platformApi.get<History>(
          `/monitoring/components/${encodeURIComponent(component.key)}/history?hours=24`,
        ),
      );
    } catch (cause) {
      setError(safeError(cause, "Check history is unavailable."));
    }
  }

  async function acknowledge(alert: MonitorAlert) {
    try {
      await platformApi.post(`/monitoring/alerts/${encodeURIComponent(alert.id)}/acknowledge`, {});
      await load();
    } catch (cause) {
      setError(safeError(cause, "The alert could not be acknowledged."));
    }
  }

  async function submit(form: FormData) {
    if (!pending) return;
    const reason = reasonOf(form);
    const base = { reason, confirmed: true };
    setError("");
    try {
      switch (pending.type) {
        case "run": {
          const result = await platformApi.post<{ transitions: string[] }>(
            `/monitoring/components/${encodeURIComponent(pending.component.key)}/run`,
            base,
          );
          setNotice(
            result.transitions.length
              ? `Check completed: ${result.transitions.join(", ")}.`
              : "Check completed with no state change.",
          );
          break;
        }
        case "configure":
          await platformApi.patch(`/monitoring/components/${encodeURIComponent(pending.component.key)}`, {
            ...base,
            enabled: form.get("enabled") === "on",
            public_visible: form.get("public_visible") === "on",
            interval_seconds: Number(form.get("interval_seconds")),
            timeout_seconds: Number(form.get("timeout_seconds")),
            failure_threshold: Number(form.get("failure_threshold")),
            recovery_threshold: Number(form.get("recovery_threshold")),
            severity: field(form, "severity"),
          });
          setNotice(`${pending.component.name} settings saved.`);
          break;
        case "simulate":
          await platformApi.post(
            `/monitoring/components/${encodeURIComponent(pending.component.key)}/simulate-failure`,
            { ...base, minutes: Number(form.get("minutes")), severity: field(form, "severity") },
          );
          setNotice(`Simulated failure started for ${pending.component.name}.`);
          break;
        case "clear-simulation":
          await platformApi.post(
            `/monitoring/components/${encodeURIComponent(pending.component.key)}/simulate-failure/clear`,
            base,
          );
          setNotice(`Simulated failure cleared for ${pending.component.name}.`);
          break;
        case "override": {
          const mode = field(form, "mode");
          await platformApi.post("/monitoring/overrides", {
            ...base,
            service_key: field(form, "service_key"),
            forced_state: mode === "suppress" ? null : mode,
            expires_in_minutes: Number(form.get("expires_in_minutes")),
          });
          setNotice("Override recorded.");
          break;
        }
        case "revoke":
          await platformApi.post(`/monitoring/overrides/${encodeURIComponent(pending.id)}/revoke`, base);
          setNotice(`Override for ${pending.serviceName} revoked.`);
          break;
        case "resend": {
          const result = await platformApi.post<{ queued: number }>(
            `/monitoring/alerts/${encodeURIComponent(pending.alert.id)}/resend`,
            base,
          );
          setNotice(`Alert email re-queued for ${result.queued} recipient(s).`);
          break;
        }
        case "alert-settings":
          await platformApi.put("/monitoring/alert-settings", {
            ...base,
            enabled: form.get("enabled") === "on",
            roles: form.getAll("roles").filter((value): value is string => typeof value === "string"),
            additional_recipients: field(form, "additional_recipients")
              .split(/[\s,]+/)
              .map((item) => item.trim())
              .filter(Boolean),
            cooldown_minutes: Number(form.get("cooldown_minutes")),
            email_warning_severity: form.get("email_warning_severity") === "on",
          });
          setNotice("Alert settings saved.");
          break;
        case "my-alerts":
          await platformApi.put("/monitoring/alert-settings/me", { ...base, receive_alerts: pending.receive });
          setNotice(pending.receive ? "You will receive alert emails." : "You will no longer receive alert emails.");
          break;
      }
      setPending(null);
      await load();
    } catch (cause) {
      setError(safeError(cause, "The action could not be completed."));
    }
  }

  if (!overview) {
    return (
      <CcSection title="Automated monitoring">
        {error ? <CcNotice tone="error">{error}</CcNotice> : <CcLoadingState label="Loading monitoring…" />}
      </CcSection>
    );
  }

  const components = sortComponents(overview.components);
  const activeOverrides = overview.overrides.filter((item) => item.active);

  const columns: CcTableColumn<MonitorComponent>[] = [
    {
      key: "name",
      header: "Check",
      render: (row) => (
        <div className="cc-monitor-name">
          <strong>{row.name}</strong>
          <small>
            {row.services.map((service) => service.name).join(", ") || "Internal"}
            {row.provider ? ` · ${row.provider}` : ""}
          </small>
        </div>
      ),
    },
    {
      key: "state",
      header: "State",
      render: (row) => (
        <div className="cc-monitor-state">
          <CcBadge tone={componentStateTone(row.state)}>{componentStateLabel(row.state)}</CcBadge>
          {row.confidence === "limited" && row.state === "healthy" && <small>Limited confidence</small>}
          {publicReportingNote(row) && <small>{publicReportingNote(row)}</small>}
          {row.simulating_until && <small>Simulated failure until {readableDate(row.simulating_until)}</small>}
        </div>
      ),
    },
    {
      key: "checked",
      header: "Last check",
      render: (row) => (
        <div className="cc-monitor-name">
          <span>{row.last_checked_at ? relativeTime(row.last_checked_at) : "Never"}</span>
          <small>Every {formatInterval(row.interval_seconds)} · {formatLatency(row.last_latency_ms)}</small>
        </div>
      ),
    },
    {
      key: "failure",
      header: "Last failure",
      render: (row) =>
        row.last_failure_at ? (
          <div className="cc-monitor-name">
            <span>
              {row.last_failure_label ?? "Failure"} · {relativeTime(row.last_failure_at)}
            </span>
            {row.last_failure_detail && <small>{row.last_failure_detail}</small>}
            {row.consecutive_failures > 0 && (
              <small>
                {row.consecutive_failures}/{row.failure_threshold} consecutive failures
              </small>
            )}
          </div>
        ) : (
          "None"
        ),
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="cc-monitor-actions">
          <button type="button" className="secondary" onClick={() => void showHistory(row)}>
            History
          </button>
          {!row.watchdog_managed && (
            <button type="button" className="secondary" onClick={() => setPending({ type: "run", component: row })}>
              Run now
            </button>
          )}
          <button type="button" className="secondary" onClick={() => setPending({ type: "configure", component: row })}>
            Configure
          </button>
          {overview.fault_injection_available &&
            !row.watchdog_managed &&
            (row.simulating_until ? (
              <button
                type="button"
                className="secondary"
                onClick={() => setPending({ type: "clear-simulation", component: row })}
              >
                Stop simulation
              </button>
            ) : (
              <button type="button" className="secondary" onClick={() => setPending({ type: "simulate", component: row })}>
                Simulate failure
              </button>
            ))}
        </div>
      ),
    },
  ];

  return (
    <>
      <CcSection
        title="Automated monitoring"
        description={`Continuous checks in ${overview.environment}. States below are persisted observations, not a live probe; a check with no recent result is shown as Unknown.`}
      >
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {notice && <CcNotice tone="success">{notice}</CcNotice>}
        {!overview.monitoring_enabled && (
          <CcNotice tone="error">Automated monitoring is disabled in this deployment (MYKHAYA_MONITORING_ENABLED).</CcNotice>
        )}
        <div className="cc-health-grid">
          <CcStatusCard
            tone={overview.runner.active ? "success" : "danger"}
            status={overview.runner.active ? "Monitoring running" : "Monitoring stopped"}
            description={
              overview.runner.last_cycle_at
                ? `Last cycle ${relativeTime(overview.runner.last_cycle_at)}. ${overview.runner.detail ?? ""}`
                : "No monitoring cycle has completed."
            }
          />
          <CcStatusCard
            tone={serviceStateTone(overview.public_preview.overall as PublicStatusState)}
            status={`Public page: ${overview.public_preview.overall_message}`}
            description={`${overview.unacknowledged_alerts} unacknowledged alert${overview.unacknowledged_alerts === 1 ? "" : "s"} · ${activeOverrides.length} active override${activeOverrides.length === 1 ? "" : "s"}`}
          />
        </div>
        <CcCard title="What customers currently see" className="cc-health-grid-full">
          <CcRecordList variant="grid">
            {overview.public_preview.services.map((service) => (
              <CcRecordCard
                key={service.key}
                title={service.name}
                badge={serviceStateLabel(service.state as PublicStatusState)}
                badgeTone={serviceStateTone(service.state as PublicStatusState)}
                meta={[`Confidence: ${service.confidence}`]}
              />
            ))}
          </CcRecordList>
        </CcCard>
        <CcTable
          columns={columns}
          rows={components}
          rowKey={(row) => row.key}
          caption="Monitored components and external dependencies"
          emptyMessage="No monitoring observations yet. Confirm the scheduler is running."
        />
      </CcSection>

      <CcSection
        title="Alerts"
        description="Every confirmed failure, recovery and monitoring outage. Email delivery status comes from the delivery records, so a failed or suppressed email is visible here."
      >
        {alerts === null ? (
          <CcLoadingState />
        ) : alerts.length === 0 ? (
          <CcEmptyState>No monitoring alerts have been raised.</CcEmptyState>
        ) : (
          <CcRecordList>
            {alerts.map((alert) => (
              <CcRecordCard
                key={alert.id}
                title={alert.subject}
                badge={alertKindLabel(alert.kind)}
                badgeTone={alertKindTone(alert.kind)}
                meta={[
                  `${readableDate(alert.created_at)} · ${alert.severity}`,
                  suppressionLabel(alert.suppressed_reason) ?? `Email: ${deliverySummary(alert.deliveries)}`,
                  alert.acknowledged_at
                    ? `Acknowledged ${relativeTime(alert.acknowledged_at)}${alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ""}`
                    : "Not acknowledged",
                ]}
                actions={
                  <>
                    {alert.incident_id && (
                      <a className="secondary" href={`/incidents/${encodeURIComponent(alert.incident_id)}`}>
                        View incident
                      </a>
                    )}
                    {!alert.acknowledged_at && (
                      <button type="button" className="secondary" onClick={() => void acknowledge(alert)}>
                        Acknowledge
                      </button>
                    )}
                    {(hasFailedDelivery(alert.deliveries) || alert.suppressed_reason === "no_recipients") && (
                      <button type="button" className="secondary" onClick={() => setPending({ type: "resend", alert })}>
                        Resend email
                      </button>
                    )}
                  </>
                }
              >
                <details>
                  <summary>Details</summary>
                  <pre className="cc-monitor-summary">{alert.summary}</pre>
                  {alert.deliveries.length > 0 && (
                    <ul className="cc-monitor-deliveries">
                      {alert.deliveries.map((delivery, index) => (
                        <li key={index}>
                          {delivery.attempt} · {delivery.status}
                          {delivery.failure_reason ? ` · ${delivery.failure_reason}` : ""}
                          {delivery.retry_count ? ` · ${delivery.retry_count} retries` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                </details>
              </CcRecordCard>
            ))}
          </CcRecordList>
        )}
      </CcSection>

      <CcSection
        title="Public reporting overrides"
        description="Suppress automated reporting for a service (e.g. a confirmed false positive) or publish a fixed state. Every override expires and is audited."
        actions={
          <button type="button" onClick={() => setPending({ type: "override" })}>
            Add override
          </button>
        }
      >
        <CcRecordList emptyMessage="No overrides recorded.">
          {overview.overrides.map((item) => (
            <CcRecordCard
              key={item.id}
              title={item.service_name}
              badge={item.active ? (item.mode === "suppress" ? "Suppressed" : `Forced: ${serviceStateLabel(item.forced_state as PublicStatusState)}`) : "Inactive"}
              badgeTone={item.active ? "warning" : "neutral"}
              meta={[
                item.reason,
                item.revoked_at
                  ? `Revoked ${relativeTime(item.revoked_at)}`
                  : `Expires ${readableDate(item.expires_at)}`,
              ]}
              actions={
                item.active ? (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setPending({ type: "revoke", id: item.id, serviceName: item.service_name })}
                  >
                    Revoke
                  </button>
                ) : undefined
              }
            />
          ))}
        </CcRecordList>
      </CcSection>

      {alertSettings && (
        <CcSection
          title="Alert recipients"
          description="Alert emails go to active administrators in the selected roles, plus any additional addresses. PCC administrators have no push registration, so email and this page are the alert channels."
          actions={
            <>
              <button
                type="button"
                className="secondary"
                onClick={() => setPending({ type: "my-alerts", receive: !alertSettings.receiving_alerts })}
              >
                {alertSettings.receiving_alerts ? "Stop my alert emails" : "Send me alert emails"}
              </button>
              {alertSettings.can_manage && (
                <button type="button" onClick={() => setPending({ type: "alert-settings" })}>
                  Edit
                </button>
              )}
            </>
          }
        >
          <CcRecordList variant="grid">
            <CcRecordCard
              title="Alert emails"
              badge={alertSettings.enabled ? "Enabled" : "Disabled"}
              badgeTone={alertSettings.enabled ? "success" : "danger"}
              meta={[
                `${alertSettings.recipient_count} recipient${alertSettings.recipient_count === 1 ? "" : "s"}`,
                `Roles: ${alertSettings.roles.join(", ") || "none"}`,
                `Cooldown: ${alertSettings.cooldown_minutes} min`,
                // Addresses are only returned to Owners/Administrators.
                alertSettings.additional_recipients
                  ? `Additional: ${alertSettings.additional_recipients.join(", ") || "none"}`
                  : `${alertSettings.additional_recipient_count ?? 0} additional address(es)`,
                alertSettings.receiving_alerts ? "You receive alert emails" : "You do not receive alert emails",
              ]}
            />
          </CcRecordList>
        </CcSection>
      )}

      <CcDialog open={history !== null} onClose={() => setHistory(null)} title={history ? `${history.name}: last 24 hours` : ""}>
        {history && (
          <div className="cc-dialog-scroll">
            <h3>State changes</h3>
            {history.transitions.length === 0 ? (
              <p>No state changes.</p>
            ) : (
              <ul className="cc-monitor-deliveries">
                {history.transitions.map((item, index) => (
                  <li key={index}>
                    {readableDate(item.occurred_at)}: {componentStateLabel(item.from_state)} →{" "}
                    {componentStateLabel(item.to_state)}
                    {item.failure_label ? ` (${item.failure_label})` : ""}
                  </li>
                ))}
              </ul>
            )}
            <h3>Checks</h3>
            <ul className="cc-monitor-deliveries">
              {history.observations.map((item, index) => (
                <li key={index}>
                  {readableDate(item.observed_at)} · {item.outcome}
                  {item.trigger !== "scheduled" ? ` (${item.trigger})` : ""} · {formatLatency(item.latency_ms)}
                  {item.failure_label ? ` · ${item.failure_label}` : ""}
                  {item.detail ? ` · ${item.detail}` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CcDialog>

      <CcConfirmDialog
        open={pending !== null}
        onClose={() => setPending(null)}
        title={dialogTitle(pending)}
        description={dialogDescription(pending)}
        confirmLabel={dialogConfirm(pending)}
        variant={pending?.type === "simulate" ? "destructive" : "default"}
        extraFields={dialogFields(pending, alertSettings)}
        onConfirm={submit}
      />
    </>
  );
}

function dialogTitle(pending: PendingAction | null): string {
  switch (pending?.type) {
    case "run":
      return `Run ${pending.component.name} now`;
    case "configure":
      return `Configure ${pending.component.name}`;
    case "simulate":
      return `Simulate a failure: ${pending.component.name}`;
    case "clear-simulation":
      return `Stop simulated failure: ${pending.component.name}`;
    case "override":
      return "Add public reporting override";
    case "revoke":
      return `Revoke override for ${pending.serviceName}`;
    case "resend":
      return "Resend alert email";
    case "alert-settings":
      return "Alert recipients";
    case "my-alerts":
      return pending.receive ? "Receive alert emails" : "Stop my alert emails";
    default:
      return "";
  }
}

function dialogDescription(pending: PendingAction | null): string | undefined {
  switch (pending?.type) {
    case "run":
      return "Runs this read-only check immediately. The result counts towards the failure and recovery thresholds like any scheduled check.";
    case "simulate":
      return "DEV only. The check reports a simulated failure until the time below, driving the real public status, incident and alert path. Real services are not touched.";
    case "resend":
      return "Queues the alert email again to the current recipient list.";
    default:
      return undefined;
  }
}

function dialogConfirm(pending: PendingAction | null): string {
  switch (pending?.type) {
    case "run":
      return "Run check";
    case "simulate":
      return "Start simulation";
    case "revoke":
      return "Revoke";
    case "resend":
      return "Resend";
    default:
      return "Save";
  }
}

function dialogFields(pending: PendingAction | null, settings: AlertSettings | null) {
  if (pending?.type === "configure") {
    const row = pending.component;
    return (
      <div className="cc-monitor-form">
        <label>
          <input type="checkbox" name="enabled" defaultChecked={row.enabled} /> Enabled
        </label>
        <label>
          <input type="checkbox" name="public_visible" defaultChecked={row.public_visible} /> Affects the public status page
          {row.requires_live_validation && (
            <small>
              Only enable after confirming this check succeeds from the live server (see the DEV acceptance
              runbook). When enabled, a confirmed failure changes the public page and opens an incident.
            </small>
          )}
        </label>
        <label>
          Interval (seconds)
          <input type="number" name="interval_seconds" min={30} max={3600} defaultValue={row.interval_seconds} required />
        </label>
        <label>
          Timeout (seconds)
          <input type="number" name="timeout_seconds" min={1} max={30} defaultValue={row.timeout_seconds} required />
        </label>
        <label>
          Failures before Degraded/Unavailable
          <input type="number" name="failure_threshold" min={1} max={10} defaultValue={row.failure_threshold} required />
        </label>
        <label>
          Successes before recovered
          <input type="number" name="recovery_threshold" min={1} max={10} defaultValue={row.recovery_threshold} required />
        </label>
        <label>
          Alert severity
          <select name="severity" defaultValue={row.severity}>
            <option value="critical">Critical (email; Unavailable is a major outage)</option>
            <option value="warning">Warning (email; Unavailable is a partial outage)</option>
            <option value="info">Info (alert centre only)</option>
          </select>
        </label>
      </div>
    );
  }
  if (pending?.type === "simulate") {
    return (
      <div className="cc-monitor-form">
        <label>
          Duration (minutes)
          <input type="number" name="minutes" min={1} max={120} defaultValue={10} required />
        </label>
        <label>
          Simulated result
          <select name="severity" defaultValue="unavailable">
            <option value="unavailable">Unavailable</option>
            <option value="degraded">Degraded</option>
          </select>
        </label>
      </div>
    );
  }
  if (pending?.type === "override") {
    return (
      <div className="cc-monitor-form">
        <label>
          Service
          <select name="service_key" required>
            {PUBLIC_SERVICE_OPTIONS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Override
          <select name="mode" defaultValue="suppress">
            <option value="suppress">Suppress automated reporting</option>
            <option value="operational">Publish Operational</option>
            <option value="maintenance">Publish Maintenance</option>
            <option value="degraded_performance">Publish Degraded Performance</option>
            <option value="partial_outage">Publish Partial Outage</option>
            <option value="major_outage">Publish Major Outage</option>
          </select>
        </label>
        <label>
          Expires after (minutes)
          <input type="number" name="expires_in_minutes" min={5} max={10080} defaultValue={120} required />
        </label>
      </div>
    );
  }
  if (pending?.type === "alert-settings" && settings) {
    const roles: [string, string][] = [
      ["platform_owner", "Owner"],
      ["platform_administrator", "Administrator"],
      ["support_operator", "Support"],
      ["security_operator", "Security"],
      ["read_only_operator", "Read-only"],
    ];
    return (
      <div className="cc-monitor-form">
        <label>
          <input type="checkbox" name="enabled" defaultChecked={settings.enabled} /> Send alert emails
        </label>
        <fieldset>
          <legend>Recipient roles</legend>
          {roles.map(([value, label]) => (
            <label key={value}>
              <input type="checkbox" name="roles" value={value} defaultChecked={settings.roles.includes(value)} /> {label}
            </label>
          ))}
        </fieldset>
        <label>
          Additional recipient emails (comma separated)
          <input type="text" name="additional_recipients" defaultValue={(settings.additional_recipients ?? []).join(", ")} />
        </label>
        <label>
          Cooldown between repeated alerts (minutes)
          <input type="number" name="cooldown_minutes" min={0} max={1440} defaultValue={settings.cooldown_minutes} required />
        </label>
        <label>
          <input type="checkbox" name="email_warning_severity" defaultChecked={settings.email_warning_severity} /> Email
          warning-severity alerts
        </label>
      </div>
    );
  }
  return undefined;
}
