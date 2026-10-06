"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Settings as SettingsIcon } from "lucide-react";
import { platformApi, type PublicSignupState } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import { registrationSummary } from "./registration-access";

type ValueType = "text" | "email" | "url" | "boolean" | "integer" | "list";
type Risk = "normal" | "sensitive";
type RuntimeEffect = "effective" | "informational" | "not_enforced";
type SettingState = "configured" | "default" | "unset";

type SettingValue = string | number | boolean | string[] | null;

type SettingItem = {
  key: string;
  label: string;
  description: string;
  section: string;
  value_type: ValueType;
  risk: Risk;
  runtime_effect: RuntimeEffect;
  editable: boolean;
  consumer_visible: boolean;
  value: SettingValue;
  state: SettingState;
};

type EnvironmentItem = { key: string; value: string; category: string; editable: boolean };

type SettingsResponse = { settings: SettingItem[]; environment: EnvironmentItem[] };
type DrivewayDvlaStatus = {
  enabled: boolean;
  configured: boolean;
  environment: string | null;
  endpoint: string | null;
  health: { state: string; message?: string };
  last_success_at: string | null;
  last_success_summary: string | null;
  last_failure_at: string | null;
  last_failure_summary: string | null;
};
type SyslogSettings = {
  enabled: boolean;
  configured: boolean;
  host: string;
  port: number;
  protocol: "udp" | "tcp" | "tls";
  facility: number;
  environment: string;
  tls_verify: boolean;
  minimum_level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  categories: SyslogCategory[];
  last_successful_delivery: string | null;
  last_error: string | null;
  dropped_count: number;
};
type SyslogDiagnostics = {
  events_seen: number;
  events_queued: number;
  events_sent: number;
  events_filtered: number;
  events_category_filtered: number;
  events_dropped: number;
  transport_failures: number;
};
type SyslogField = "enabled" | "host" | "port" | "protocol" | "facility" | "environment" | "tls_verify" | "minimum_level" | "reason";
type SyslogFieldErrors = Partial<Record<SyslogField, string>>;
type SyslogCategory = "application" | "http" | "security" | "audit" | "worker" | "integration";

const SYSLOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
const SYSLOG_CATEGORIES: Array<{ value: SyslogCategory; label: string }> = [
  { value: "application", label: "Application" },
  { value: "http", label: "HTTP / API Requests" },
  { value: "security", label: "Security & Authentication" },
  { value: "audit", label: "Audit" },
  { value: "worker", label: "Workers & Scheduler" },
  { value: "integration", label: "External Integrations" },
];

const DEFAULT_SYSLOG_CATEGORIES = SYSLOG_CATEGORIES.map(({ value }) => value);
const SYSLOG_FACILITIES = [
  ...Array.from({ length: 8 }, (_, index) => ({ value: index, label: `Kernel${index} (${index})` })),
  { value: 8, label: "User-level (8)" },
  { value: 9, label: "Mail (9)" },
  { value: 10, label: "System (10)" },
  { value: 11, label: "Security (11)" },
  { value: 12, label: "Syslog (12)" },
  { value: 13, label: "Line printer (13)" },
  { value: 14, label: "Network news (14)" },
  { value: 15, label: "UUCP (15)" },
  ...Array.from({ length: 8 }, (_, index) => ({ value: index + 16, label: `Local${index} (${index + 16})` })),
];

function formatSyslogTimestamp(value: string | null): string {
  if (!value) return "No successful delivery recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  // Explicit locale, not the ambient ICU default — the container running
  // this (and every end user's own device locale) can't be relied on to
  // match the rest of the app's en-GB date formatting (see
  // components/platform-format.ts's readableDate for the shared pattern).
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatTimestamp(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function dvlaHealthTone(state: string | undefined): "success" | "warning" | "danger" | "neutral" {
  switch (state) {
    case "Healthy":
      return "success";
    case "Not configured":
    case "Disabled":
      return "neutral";
    case "Degraded":
    case "Unavailable":
      return "danger";
    default:
      return "neutral";
  }
}

function normaliseSyslogSettings(value: SyslogSettings): SyslogSettings {
  return {
    ...value,
    categories: Array.isArray(value.categories) ? value.categories : DEFAULT_SYSLOG_CATEGORIES,
  };
}

// Sections render in this order regardless of API response order; any
// section not listed here (there shouldn't be one) falls back to the end.
const SECTION_ORDER = ["General", "Signup", "Registration & Access", "Home Limits", "Support", "Regional", "Legal"];

function groupBySection(items: SettingItem[]): [string, SettingItem[]][] {
  const bySection = new Map<string, SettingItem[]>();
  for (const item of items) {
    const list = bySection.get(item.section) ?? [];
    list.push(item);
    bySection.set(item.section, list);
  }
  return [...bySection.entries()].sort(
    (a, b) => SECTION_ORDER.indexOf(a[0]) - SECTION_ORDER.indexOf(b[0]),
  );
}

function stateCaption(state: SettingState): string | null {
  if (state === "default") return "Using deployment default";
  if (state === "configured") return "Configured in Platform Control Centre";
  return null;
}

// Confirmation copy is derived from runtime_effect, never hand-written per
// key — a setting that later gains real enforcement only needs its schema
// runtime_effect changed to "effective" for this copy to switch to the
// stronger operational warning; see docs/architecture/platform-control-centre.md.
function confirmationDescription(item: SettingItem): string {
  if (item.runtime_effect === "not_enforced") {
    return (
      "This setting is not yet enforced by the application — saving it records the " +
      "configured value in Platform Control Centre but does not currently change user " +
      "access or behaviour."
    );
  }
  return `${item.label} affects real user access or availability. Make sure you intend this change before saving.`;
}

function toDraftText(value: SettingValue): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function parseDraft(valueType: ValueType, draft: string, boolDraft: boolean): SettingValue {
  if (valueType === "boolean") return boolDraft;
  if (valueType === "integer") return Number(draft);
  if (valueType === "list")
    return draft
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  return draft;
}

function isDirty(item: SettingItem, draft: string, boolDraft: boolean): boolean {
  if (item.value_type === "boolean") return Boolean(item.value) !== boolDraft;
  return toDraftText(item.value) !== draft;
}

function SettingRow({ item, onSaved, label, description, hideKey }: { item: SettingItem; onSaved: () => Promise<void>; label?: string; description?: string; hideKey?: boolean }) {
  const [draft, setDraft] = useState(() => toDraftText(item.value));
  const [boolDraft, setBoolDraft] = useState(() => Boolean(item.value));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    setDraft(toDraftText(item.value));
    setBoolDraft(Boolean(item.value));
  }, [item.value]);

  const dirty = isDirty(item, draft, boolDraft);

  const save = useCallback(
    async (reasonText: string) => {
      setSaving(true);
      setError("");
      try {
        await platformApi.put(`/settings/${item.key}`, {
          value: parseDraft(item.value_type, draft, boolDraft),
          reason: reasonText,
          confirmed: true,
        });
        setReason("");
        await onSaved();
      } catch (cause) {
        setError((cause as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [item.key, item.value_type, draft, boolDraft, onSaved],
  );

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty || saving) return;
    if (item.risk === "sensitive") {
      setConfirmOpen(true);
      return;
    }
    void save(reason);
  }

  const caption = stateCaption(item.state);

  return (
    <CcCard
      className="setting-row"
      title={label ?? item.label}
      description={
        <>
          {description ?? item.description} {!hideKey && <small className="setting-row-key">{item.key}</small>}
        </>
      }
    >
      {item.runtime_effect === "not_enforced" && <CcNotice tone="warning">Not yet enforced by the application.</CcNotice>}
      <form className="setting-row-form" onSubmit={onSubmit}>
        {item.value_type === "boolean" ? (
          <CcField label="Enabled" help={caption}>
            <input
              type="checkbox"
              checked={boolDraft}
              onChange={(event) => setBoolDraft(event.target.checked)}
            />
          </CcField>
        ) : (
          <CcField label="Value" help={caption}>
            <input
              type={
                item.value_type === "email"
                  ? "email"
                  : item.value_type === "url"
                    ? "url"
                    : item.value_type === "integer"
                      ? "number"
                      : "text"
              }
              value={draft}
              placeholder={item.state === "unset" ? "Not yet set" : undefined}
              onChange={(event) => setDraft(event.target.value)}
            />
          </CcField>
        )}
        {item.risk !== "sensitive" && (
          <CcField label="Reason for this change">
            <input
              type="text"
              value={reason}
              minLength={10}
              maxLength={500}
              required={dirty}
              onChange={(event) => setReason(event.target.value)}
            />
          </CcField>
        )}
        <button type="submit" disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
      {error && <CcNotice tone="error">{error}</CcNotice>}
      <CcConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={`Save ${item.label}?`}
        description={confirmationDescription(item)}
        confirmLabel="Save"
        variant="destructive"
        onConfirm={async (formData) => {
          const raw = formData.get("audit_reason");
          const confirmReason = typeof raw === "string" ? raw : "";
          setConfirmOpen(false);
          await save(confirmReason);
        }}
      />
    </CcCard>
  );
}

const SIGNUP_MODES = [
  { value: "normal", label: "Normal", help: "Allow ordinary account signup; Beta joining follows programme availability." },
  { value: "beta_only", label: "Beta only", help: "Only the approved Founding Beta registration path is available." },
  { value: "mixed", label: "Mixed", help: "Allow both ordinary signup and eligible Founding Beta joining." },
  { value: "closed", label: "Closed", help: "Do not accept new account or Beta registrations." },
] as const;

function SignupModeCard({ item, onSaved }: { item: SettingItem; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState(String(item.value ?? "normal"));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setValue(String(item.value ?? "normal")), [item.value]);
  const selected = SIGNUP_MODES.find((mode) => mode.value === value) ?? SIGNUP_MODES[0];
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim() || reason.trim().length < 10 || busy) return;
    setBusy(true); setError("");
    try {
      await platformApi.put(`/settings/${item.key}`, { value, reason, confirmed: true });
      setReason("");
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to save Signup Mode.");
    } finally { setBusy(false); }
  }
  return (
    <CcCard className="registration-access-card" title="Signup Mode" description="Choose which new-account paths are available. This is narrowed by the master switch, invitation-only access and Founding Beta capacity.">
      <form className="setting-row-form" onSubmit={save}>
        <CcField label="Signup Mode" help={selected.help}>
          <select value={value} onChange={(event) => setValue(event.target.value)}>
            {SIGNUP_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
          </select>
        </CcField>
        <CcField label="Reason for this change" help="Changes are recorded in the existing Platform audit log.">
          <input value={reason} minLength={10} maxLength={500} required onChange={(event) => setReason(event.target.value)} />
        </CcField>
        <button type="submit" disabled={busy || value === String(item.value ?? "normal")}>{busy ? "Saving…" : "Save"}</button>
      </form>
      {error && <CcNotice tone="error">{error}</CcNotice>}
    </CcCard>
  );
}

function ReadonlyVerificationCard({ item }: { item: SettingItem }) {
  const required = item.value !== false;
  return (
    <CcCard className="registration-access-card" title="Email verification" description="Managed by deployment policy. Production cannot turn this safeguard off from PCC.">
      <div className="registration-readonly-value">
        <strong>{required ? "Required" : "Optional"}</strong>
        <span>New accounts must verify their email before signing in when required.</span>
      </div>
    </CcCard>
  );
}

function RegistrationSummaryCard({ items, publicState }: { items: SettingItem[]; publicState: PublicSignupState | null }) {
  const summary = registrationSummary(items, publicState);
  const fields = [
    ["Signup Mode", summary.signupMode],
    ["Normal signup", summary.normalSignup],
    ["Founding Beta signup", summary.betaSignup],
    ["Waitlist", summary.waitlist],
    ["Invitation required", summary.invitation],
    ["Email verification", summary.emailVerification],
    ["Existing user sign-in", summary.signIn],
  ];
  return (
    <CcCard className="registration-summary-card" title="Effective registration behaviour" description="This is the current answer for a new visitor. Existing users can always sign in; the master switch overrides Signup Mode, then invitation-only access and Beta capacity or waitlist rules narrow what remains.">
      <dl className="registration-summary-grid">
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><CcBadge tone={value === "Disabled" || value === "Closed" ? "neutral" : "info"}>{value}</CcBadge></dd></div>)}
      </dl>
    </CcCard>
  );
}

function RegistrationAccessSection({ items, signup, publicState, onSaved }: { items: SettingItem[]; signup?: SettingItem; publicState: PublicSignupState | null; onSaved: () => Promise<void> }) {
  const item = (key: string) => items.find((candidate) => candidate.key === key);
  return (
    <section className="platform-settings-section registration-access-section" aria-labelledby="registration-access-heading">
      <h2 id="registration-access-heading">Registration &amp; Access</h2>
      <RegistrationSummaryCard items={items} publicState={publicState} />
      <div className="registration-access-group">
        <h3>Signup availability</h3>
        {signup && <SignupModeCard item={signup} onSaved={onSaved} />}
      </div>
      <div className="registration-access-group">
        <h3>Registration safeguards</h3>
        {item("registration_enabled") && <SettingRow item={item("registration_enabled")!} label="Allow any new registrations" description="Emergency master switch for every new account path. Turning this off closes normal and Founding Beta signup while existing users can still sign in." hideKey onSaved={onSaved} />}
        {item("invite_only_mode") && <SettingRow item={item("invite_only_mode")!} label="Invitation-only access" description="Require a valid Home invitation for normal signup or a Beta invitation for Founding Beta signup. This narrows the selected Signup Mode." hideKey onSaved={onSaved} />}
      </div>
      <div className="registration-access-group">
        <h3>Verification &amp; security</h3>
        {item("email_verification_required") && <ReadonlyVerificationCard item={item("email_verification_required")!} />}
        {item("allowed_registration_domains") && <SettingRow item={item("allowed_registration_domains")!} label="Allowed registration domains" hideKey onSaved={onSaved} />}
        {item("invitation_expiry_days") && <SettingRow item={item("invitation_expiry_days")!} label="Invitation expiry" hideKey onSaved={onSaved} />}
      </div>
    </section>
  );
}

export default function PlatformSettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [publicSignupState, setPublicSignupState] = useState<PublicSignupState | null>(null);
  const [dvla, setDvla] = useState<DrivewayDvlaStatus | null>(null);
  const [syslog, setSyslog] = useState<SyslogSettings | null>(null);
  const [syslogDraft, setSyslogDraft] = useState<SyslogSettings | null>(null);
  const [syslogDiagnostics, setSyslogDiagnostics] = useState<SyslogDiagnostics | null>(null);
  const [syslogReason, setSyslogReason] = useState("");
  const [syslogBusy, setSyslogBusy] = useState(false);
  const [syslogResult, setSyslogResult] = useState("");
  const [syslogErrors, setSyslogErrors] = useState<SyslogFieldErrors>({});
  const [testRegistration, setTestRegistration] = useState("");
  const [testResult, setTestResult] = useState("");
  const [testBusy, setTestBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [settings, publicState, dvlaStatus, syslogStatus, diagnostics] = await Promise.all([
        platformApi.get<SettingsResponse>("/settings"),
        platformApi.get<PublicSignupState>("/signup-state"),
        platformApi.get<DrivewayDvlaStatus>("/integrations/dvla"),
        platformApi.get<SyslogSettings>("/logging/syslog"),
        platformApi.get<SyslogDiagnostics>("/logging/syslog/diagnostics"),
      ]);
      setData(settings);
      setPublicSignupState(publicState);
      setDvla(dvlaStatus);
      const normalisedSyslog = normaliseSyslogSettings(syslogStatus);
      setSyslog(normalisedSyslog);
      setSyslogDraft(normalisedSyslog);
      setSyslogDiagnostics(diagnostics);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function testDvla() {
    if (!testRegistration.trim() || testBusy) return;
    setTestBusy(true);
    setTestResult("");
    try {
      const result = await platformApi.post<{ message: string }>("/integrations/dvla/test", {
        registration: testRegistration,
        reason: "Verify the configured DVLA vehicle lookup connection",
        confirmed: true,
      });
      setTestResult(result.message);
      await load();
    } catch (cause) {
      setTestResult(cause instanceof Error ? cause.message : "The DVLA connection test failed.");
    } finally {
      setTestBusy(false);
    }
  }

  async function saveSyslog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!syslogDraft || syslogBusy) return;
    const errors: SyslogFieldErrors = {};
    if (syslogDraft.enabled && !syslogDraft.host.trim()) errors.host = "Host is required when central logging is enabled.";
    if (!Number.isInteger(syslogDraft.port) || syslogDraft.port < 1 || syslogDraft.port > 65535) errors.port = "Port must be between 1 and 65535.";
    if (!Number.isInteger(syslogDraft.facility) || syslogDraft.facility < 0 || syslogDraft.facility > 23) errors.facility = "Facility must be between 0 and 23.";
    if (!syslogReason.trim() || syslogReason.trim().length < 10) errors.reason = "Reason for this change must be at least 10 characters.";
    setSyslogErrors(errors);
    if (Object.keys(errors).length) return;
    setSyslogBusy(true);
    setSyslogResult("");
    try {
      const saved = await platformApi.put<SyslogSettings>("/logging/syslog", {
        enabled: syslogDraft.enabled,
        host: syslogDraft.host,
        port: syslogDraft.port,
        protocol: syslogDraft.protocol,
        facility: syslogDraft.facility,
        environment: syslogDraft.environment,
        tls_verify: syslogDraft.tls_verify,
        minimum_level: syslogDraft.minimum_level,
        categories: syslogDraft.categories,
        reason: syslogReason,
        confirmed: true,
      });
      const normalisedSaved = normaliseSyslogSettings(saved);
      setSyslog(normalisedSaved);
      setSyslogDraft(normalisedSaved);
      setSyslogReason("");
      setSyslogResult("Central logging settings saved.");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to save central logging settings.";
      setSyslogResult(message);
      if (message.toLowerCase().includes("host")) setSyslogErrors({ host: message });
      else if (message.toLowerCase().includes("port")) setSyslogErrors({ port: message });
      else if (message.toLowerCase().includes("facility")) setSyslogErrors({ facility: message });
      else if (message.toLowerCase().includes("reason")) setSyslogErrors({ reason: message });
    } finally {
      setSyslogBusy(false);
    }
  }

  async function testSyslog() {
    if (syslogBusy || !syslog?.enabled || !syslogDraft || JSON.stringify(syslog) !== JSON.stringify(syslogDraft)) return;
    setSyslogBusy(true);
    setSyslogResult("");
    try {
      const result = await platformApi.post<{ message: string }>("/logging/syslog/test", {
        reason: "Verify the configured central logging destination",
        confirmed: true,
      });
      setSyslogResult(result.message);
      await load();
    } catch (cause) {
      setSyslogResult(cause instanceof Error ? cause.message : "The syslog test failed.");
    } finally {
      setSyslogBusy(false);
    }
  }

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader eyebrow="Control Centre" title="Settings" />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {!data && !error ? (
          <CcLoadingState label="Loading settings…" />
        ) : (
          data && (
            <>
              <CcCard title="Environment" description="Managed by the deployment environment — edit the server's .env and redeploy." icon={SettingsIcon}>
                <CcMetadataGrid>
                  {data.environment.map((item) => (
                    <CcMetadataItem key={item.key} label={titleCase(item.key)}>
                      {item.value}
                    </CcMetadataItem>
                  ))}
                </CcMetadataGrid>
              </CcCard>
              <CcCard title="Driveway integrations" description="Operational status for the server-side UK vehicle lookup provider.">
                <CcMetadataGrid>
                  <CcMetadataItem label="Environment">
                    {dvla ? (dvla.environment ?? "Not configured") : "Loading…"}
                  </CcMetadataItem>
                  <CcMetadataItem label="Integration status">
                    <CcBadge tone={dvla?.enabled ? "success" : "neutral"}>{dvla?.enabled ? "Enabled" : "Disabled"}</CcBadge>
                  </CcMetadataItem>
                  <CcMetadataItem label="API key">{dvla?.configured ? "Configured" : "Not configured"}</CcMetadataItem>
                  <CcMetadataItem label="Health"><CcBadge tone={dvlaHealthTone(dvla?.health.state)}>{dvla?.health.state ?? "Loading…"}</CcBadge></CcMetadataItem>
                  <CcMetadataItem label="Endpoint" span>{dvla?.endpoint ?? "Not configured"}</CcMetadataItem>
                  {dvla?.last_success_at && (
                    <CcMetadataItem label="Last successful lookup">{formatTimestamp(dvla.last_success_at, "Never")}</CcMetadataItem>
                  )}
                  {dvla?.last_failure_at && (
                    <CcMetadataItem label="Last failed lookup">{formatTimestamp(dvla.last_failure_at, "Never")}</CcMetadataItem>
                  )}
                  {dvla?.last_failure_summary && (
                    <CcMetadataItem label="Last error" span>{dvla.last_failure_summary}</CcMetadataItem>
                  )}
                </CcMetadataGrid>
                {dvla?.environment === "Production" && (
                  <CcNotice tone="warning">Production DVLA service — lookups here use real, live vehicle data.</CcNotice>
                )}
                <p className="cc-page-meta">Enable or disable the provider using the Driveway integrations setting below. The API key is deployment-managed and never displayed.</p>
                <div className="cc-inline-form">
                  <label>Test registration<input value={testRegistration} onChange={(event) => setTestRegistration(event.target.value)} placeholder="AB12 CDE" /></label>
                  <button className="button secondary" type="button" onClick={() => void testDvla()} disabled={testBusy || !testRegistration.trim() || !dvla?.configured}>{testBusy ? "Testing…" : "Test connection"}</button>
                  {testResult && <p role="status">{testResult}</p>}
                </div>
              </CcCard>
              {syslogDraft && syslog && (
                <CcCard title="Central logging" description="Forward structured platform logs to an RFC 5424 syslog destination. Disabled by default; browser and household data are never sent directly from the client.">
                  <form className="setting-row-form central-logging-form" onSubmit={(event) => void saveSyslog(event)}>
                    <CcMetadataGrid className="central-logging-status-grid">
                      <CcMetadataItem label="Status"><CcBadge tone={syslog.enabled ? "success" : "neutral"}>{syslog.enabled ? "Enabled" : "Disabled"}</CcBadge></CcMetadataItem>
                      <CcMetadataItem label="Last delivery">{formatSyslogTimestamp(syslog.last_successful_delivery)}</CcMetadataItem>
                      <CcMetadataItem label="Dropped messages">{syslog.dropped_count}</CcMetadataItem>
                      <CcMetadataItem label="Last error" span>{syslog.last_error ?? "None"}</CcMetadataItem>
                    </CcMetadataGrid>
                    <div className="central-logging-form-grid">
                      <section>
                        <h3>Destination</h3>
                    <CcField label="Enabled" help="Best-effort delivery uses a bounded queue and never blocks requests.">
                      <input type="checkbox" checked={syslogDraft.enabled} onChange={(event) => setSyslogDraft({ ...syslogDraft, enabled: event.target.checked })} />
                    </CcField>
                    <CcField label="Host" error={syslogErrors.host}><input value={syslogDraft.host} onChange={(event) => { setSyslogErrors({}); setSyslogDraft({ ...syslogDraft, host: event.target.value }); }} /></CcField>
                    <CcField label="Port" error={syslogErrors.port}><input type="number" min={1} max={65535} value={syslogDraft.port} onChange={(event) => { setSyslogErrors({}); setSyslogDraft({ ...syslogDraft, port: Number(event.target.value) }); }} /></CcField>
                    <CcField label="Protocol"><select value={syslogDraft.protocol} onChange={(event) => setSyslogDraft({ ...syslogDraft, protocol: event.target.value as SyslogSettings["protocol"] })}><option value="tls">TLS</option><option value="tcp">TCP</option><option value="udp">UDP</option></select></CcField>
                    <CcField label="Facility" error={syslogErrors.facility}><select value={syslogDraft.facility} onChange={(event) => { setSyslogErrors({}); setSyslogDraft({ ...syslogDraft, facility: Number(event.target.value) }); }}>{SYSLOG_FACILITIES.map((facility) => <option key={facility.value} value={facility.value}>{facility.label}</option>)}</select></CcField>
                      </section>
                      <section>
                        <h3>Logging</h3>
                        <CcField label="Minimum log level"><select value={syslogDraft.minimum_level} onChange={(event) => setSyslogDraft({ ...syslogDraft, minimum_level: event.target.value as SyslogSettings["minimum_level"] })}>{SYSLOG_LEVELS.map((level) => <option key={level} value={level}>{level.charAt(0) + level.slice(1).toLowerCase()}</option>)}</select></CcField>
                        <CcField label="Environment"><input maxLength={80} value={syslogDraft.environment} onChange={(event) => setSyslogDraft({ ...syslogDraft, environment: event.target.value })} /></CcField>
                        <CcField label="Verify TLS certificate" help={syslogDraft.protocol === "tls" ? undefined : "Only applies to TLS connections."}><input type="checkbox" disabled={syslogDraft.protocol !== "tls"} checked={syslogDraft.tls_verify} onChange={(event) => setSyslogDraft({ ...syslogDraft, tls_verify: event.target.checked })} /></CcField>
                        <span className="cc-field-help">Verify the remote certificate</span>
                      </section>
                    </div>
                    <section className="central-logging-change-control">
                      <h3>Change control</h3>
                    <CcField label="Reason for this change" error={syslogErrors.reason}><input minLength={10} maxLength={500} required value={syslogReason} onChange={(event) => { setSyslogErrors({}); setSyslogReason(event.target.value); }} /></CcField>
                      <p className="cc-page-meta">Recent administrator authentication is required to change central logging configuration.</p>
                    </section>
                    <fieldset className="central-logging-categories">
                      <legend>Events to send</legend>
                      <p className="cc-page-meta">Choose which MyKhaya events are forwarded. Local application logging is unaffected.</p>
                      <div className="central-logging-category-grid">
                        {SYSLOG_CATEGORIES.map((category) => (
                          <label key={category.value} className="central-logging-category-option">
                            <input
                              type="checkbox"
                              checked={syslogDraft.categories.includes(category.value)}
                              onChange={(event) => setSyslogDraft({
                                ...syslogDraft,
                                categories: event.target.checked
                                  ? [...syslogDraft.categories, category.value]
                                  : syslogDraft.categories.filter((item) => item !== category.value),
                              })}
                            />
                            <span>{category.label}</span>
                          </label>
                        ))}
                      </div>
                      {syslogDraft.categories.length === 0 && <p className="cc-field-help">Central Logging remains enabled, but no normal application events will be forwarded.</p>}
                    </fieldset>
                    <div className="cc-inline-form"><button type="submit" disabled={syslogBusy}>{syslogBusy ? "Saving…" : "Save settings"}</button><button className="button secondary" type="button" onClick={() => void testSyslog()} disabled={syslogBusy || !syslog?.enabled || !syslogDraft || JSON.stringify(syslog) !== JSON.stringify(syslogDraft)}>{syslogBusy ? "Testing…" : "Send test message"}</button></div>
                  </form>
                  {syslogDiagnostics && <details className="central-logging-diagnostics"><summary>Advanced diagnostics</summary><CcMetadataGrid>
                    <CcMetadataItem label="Events seen">{syslogDiagnostics.events_seen}</CcMetadataItem>
                    <CcMetadataItem label="Events queued">{syslogDiagnostics.events_queued}</CcMetadataItem>
                    <CcMetadataItem label="Events sent">{syslogDiagnostics.events_sent}</CcMetadataItem>
                    <CcMetadataItem label="Events filtered">{syslogDiagnostics.events_filtered}</CcMetadataItem>
                    <CcMetadataItem label="Category-filtered">{syslogDiagnostics.events_category_filtered}</CcMetadataItem>
                    <CcMetadataItem label="Events dropped">{syslogDiagnostics.events_dropped}</CcMetadataItem>
                    <CcMetadataItem label="Transport failures">{syslogDiagnostics.transport_failures}</CcMetadataItem>
                  </CcMetadataGrid></details>}
                  {syslogResult && <p role="status" className="cc-page-meta">{syslogResult}</p>}
                </CcCard>
              )}
              {groupBySection(data.settings.filter((item) => item.key !== "signup_mode" && item.section !== "Registration & Access")).map(([section, items]) => (
                <section key={section} className="platform-settings-section">
                  <h2>{section}</h2>
                  <div className="settings-section-rows">
                    {items.map((item) => (
                      <SettingRow key={item.key} item={item} onSaved={load} />
                    ))}
                  </div>
                </section>
              ))}
              <RegistrationAccessSection
                items={data.settings.filter((item) => item.section === "Registration & Access")}
                signup={data.settings.find((item) => item.key === "signup_mode")}
                publicState={publicSignupState}
                onSaved={load}
              />
            </>
          )
        )}
      </CcPage>
    </PlatformShell>
  );
}
