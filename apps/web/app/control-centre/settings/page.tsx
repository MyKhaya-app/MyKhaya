"use client";

import "@fontsource/plus-jakarta-sans/latin-400.css";
import "@fontsource/plus-jakarta-sans/latin-500.css";
import "@fontsource/plus-jakarta-sans/latin-600.css";
import "@fontsource/plus-jakarta-sans/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import {
  createContext,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { platformApi, type PublicSignupState } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { registrationSummary } from "./registration-access";

// PCC Settings. Every editable value is tracked as a draft against the
// last-loaded value and saved together from the sticky save bar with one
// audit reason; each setting is still PUT (and audited) individually.
// Styles live in pcc.css under .pccs-root: the admin host's CSP forbids
// inline styles and third-party fonts, so fonts are self-hosted.

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
type SettingsResponse = {
  settings: SettingItem[];
  environment: EnvironmentItem[];
  deployment_environment?: string;
};
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
type DrivewayDvsaStatus = {
  enabled: boolean;
  deployment_enabled: boolean;
  configured: boolean;
  environment: string | null;
  health: { state: string };
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_category: string | null;
};
type SyslogCategory = "application" | "http" | "security" | "audit" | "worker" | "integration";
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
type SyslogField = "host" | "port" | "facility";
type SyslogFieldErrors = Partial<Record<SyslogField, string>>;
type Draft = string | boolean;
type Tone = "ok" | "warn" | "off" | "info";

const DVSA_FAILURE_LABELS: Record<string, string> = {
  auth_failed: "Authentication failed",
  rate_limited: "Rate limited",
  unavailable: "Service unavailable or timed out",
  malformed: "Unexpected response",
  not_configured: "Not configured",
};

const SYSLOG_LEVELS = [
  { value: "DEBUG", label: "Debug" },
  { value: "INFO", label: "Info" },
  { value: "WARNING", label: "Warning" },
  { value: "ERROR", label: "Error" },
  { value: "CRITICAL", label: "Critical" },
] as const;
const SYSLOG_CATEGORIES: Array<{ value: SyslogCategory; label: string }> = [
  { value: "application", label: "Application" },
  { value: "http", label: "HTTP / API requests" },
  { value: "security", label: "Security & authentication" },
  { value: "audit", label: "Audit" },
  { value: "worker", label: "Workers & schedules" },
  { value: "integration", label: "External integrations" },
];
const DEFAULT_SYSLOG_CATEGORIES = SYSLOG_CATEGORIES.map(({ value }) => value);
// RFC 5424 facility codes.
const SYSLOG_FACILITIES = [
  "kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
  "uucp", "cron", "authpriv", "ftp", "ntp", "audit", "alert", "clock",
  "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7",
].map((name, value) => ({ value, label: `${name} (${value})` }));

const SIGNUP_MODES = [
  { value: "normal", label: "Normal", help: "Allow ordinary account signup; Beta joining follows programme availability." },
  { value: "beta_only", label: "Beta only", help: "Only the approved Founding Beta registration path is available." },
  { value: "mixed", label: "Mixed", help: "Allow both ordinary signup and eligible Founding Beta joining." },
  { value: "closed", label: "Closed", help: "Do not accept new account or Beta registrations." },
] as const;
const SIGNUP_STRIP_LABELS: Record<string, string> = {
  normal: "Normal",
  beta_only: "Founding Beta",
  mixed: "Mixed",
  closed: "Closed",
};

const LOCALES: Array<[string, string]> = [
  ["en-GB", "English (United Kingdom)"],
  ["en-US", "English (United States)"],
  ["en-ZA", "English (South Africa)"],
  ["af-ZA", "Afrikaans (South Africa)"],
];

// Row copy. Labels/descriptions follow the PCC Settings design; the
// backend's own label is the fallback for any key not listed here.
const COPY: Record<string, { label: string; description?: string }> = {
  driveway_dvla_enabled: { label: "DVLA vehicle lookup", description: "Add vehicles by registration via the DVLA provider." },
  driveway_dvsa_enabled: { label: "DVSA MOT history", description: "Refresh MOT status and history." },
  platform_display_name: { label: "Platform name", description: "Shown throughout administrator-facing surfaces." },
  maintenance_mode: {
    label: "Maintenance mode",
    description: "Takes MyKhaya offline for everyone except Control Centre operators. API returns 503 and apps show the maintenance screen.",
  },
  home_migration_enabled: {
    label: "Home migration",
    description: "Let platform administrators export or import home migration packages. Keep off unless a migration is in progress.",
  },
  maximum_homes_per_user: {
    label: "Max homes per user",
    description: "Blocks creating, joining or accepting an invite to another home. Existing memberships are unaffected.",
  },
  maximum_members_per_home: { label: "Max members per home", description: "Platform-wide ceiling. A plan may set a lower one." },
  support_contact_address: { label: "Support email", description: "Where support-related correspondence is directed." },
  service_status_url: { label: "Service status page", description: "Linked from Help & Support. Falls back to the deployment default." },
  default_locale: { label: "Default language" },
  default_timezone: { label: "Default timezone" },
  privacy_notice_version: { label: "Privacy notice version" },
  terms_version: { label: "Terms version" },
  signup_mode: {
    label: "Signup mode",
    description: "Which new-account paths are available. Narrowed by the master switch, invitation-only access and Founding Beta capacity.",
  },
  registration_enabled: {
    label: "Allow new registrations",
    description: "Emergency master switch. Off closes all paths; existing users can still sign in.",
  },
  invite_only_mode: { label: "Invitation-only", description: "Require a valid home invitation or Founding Beta invitation to sign up." },
  allowed_registration_domains: { label: "Allowed email domains", description: "Comma-separated. Blank allows any domain." },
  invitation_expiry_days: { label: "Invitation expiry", description: "Applies to new invitations only." },
};

// Deployment-managed: shown, never editable here, never dirty.
const READ_ONLY_KEYS = new Set(["email_verification_required"]);

const ENVIRONMENT_LABELS: Record<string, string> = {
  public_url: "Public URL",
  admin_url: "Admin URL",
  status_url: "Status URL",
};

const NAV_GROUPS = [
  { label: "System", items: [["env", "Environment"], ["integrations", "Integrations"], ["logging", "Central logging"]] },
  { label: "Platform", items: [["general", "General"], ["operations", "Operations"], ["limits", "Home limits"]] },
  { label: "Policy", items: [["support", "Support"], ["regional", "Regional"], ["legal", "Legal"], ["registration", "Registration & access"]] },
] as const;
type SectionId = (typeof NAV_GROUPS)[number]["items"][number][0];

const LOGGING_TERMS = [
  "Central logging",
  "Forward structured platform logs to an RFC 5424 syslog destination. Secrets and household data are never sent.",
  "Host", "Port", "Protocol", "Facility", "Minimum level", "Environment tag", "Events to send", "Verify TLS certificate",
  ...SYSLOG_CATEGORIES.map((category) => category.label),
];

function copyFor(key: string, item?: SettingItem): { label: string; description?: string } {
  return COPY[key] ?? { label: item?.label ?? key, description: item?.description };
}

function formatTimestamp(value: string | null | undefined, withYear = true): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  // Explicit en-GB: the server/container locale can't be relied on.
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function latest(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return new Date(a) > new Date(b) ? a : b;
}

function healthTone(state: string | undefined): Tone {
  switch (state) {
    case "Healthy":
      return "ok";
    case "Disabled":
      return "off";
    case undefined:
      return "off";
    default:
      return "warn";
  }
}

function normaliseSyslog(value: SyslogSettings): SyslogSettings {
  return { ...value, categories: Array.isArray(value.categories) ? value.categories : DEFAULT_SYSLOG_CATEGORIES };
}

function syslogComparable(value: SyslogSettings): string {
  return JSON.stringify([
    value.enabled,
    value.host,
    value.port,
    value.protocol,
    value.facility,
    value.environment,
    value.tls_verify,
    value.minimum_level,
    [...value.categories].sort(),
  ]);
}

function validateSyslog(value: SyslogSettings): SyslogFieldErrors {
  const errors: SyslogFieldErrors = {};
  if (value.enabled && !value.host.trim()) errors.host = "Host is required when central logging is enabled.";
  if (!Number.isInteger(value.port) || value.port < 1 || value.port > 65535) errors.port = "Port must be between 1 and 65535.";
  if (!Number.isInteger(value.facility) || value.facility < 0 || value.facility > 23) errors.facility = "Facility must be between 0 and 23.";
  return errors;
}

function baselineDraft(item: SettingItem): Draft {
  if (item.value_type === "boolean") return Boolean(item.value);
  if (item.value === null || item.value === undefined) return "";
  if (Array.isArray(item.value)) return item.value.join(", ");
  return String(item.value);
}

function parseList(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function parseDraft(item: SettingItem, draft: Draft): SettingValue {
  if (item.value_type === "boolean") return Boolean(draft);
  const text = String(draft);
  if (item.value_type === "integer") return Number(text);
  if (item.value_type === "list") return parseList(text);
  return text;
}

function isDirty(item: SettingItem, draft: Draft): boolean {
  const base = baselineDraft(item);
  if (item.value_type === "list") return parseList(String(base)).join(",") !== parseList(String(draft)).join(",");
  return base !== draft;
}

// Confirmation copy is derived from runtime_effect, never hand-written per
// key; see docs/architecture/platform-control-centre.md.
function confirmationDescription(item: SettingItem, label: string): string {
  if (item.runtime_effect === "not_enforced") {
    return (
      `${label} is not yet enforced by the application — saving it records the configured value in ` +
      "Platform Control Centre but does not currently change user access or behaviour."
    );
  }
  return `${label} affects real user access or availability. Make sure you intend this change before saving.`;
}

function matches(filter: string, ...texts: Array<string | undefined>): boolean {
  const needle = filter.trim().toLowerCase();
  if (!needle) return true;
  return texts.some((text) => text?.toLowerCase().includes(needle));
}

const FilterContext = createContext("");

function Badge({ tone, dot = false, children }: { tone: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`pccs-badge pccs-badge-${tone}`}>
      {dot && <span className="pccs-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

function Switch({
  label,
  checked,
  disabled,
  onChange,
  id,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  id?: string;
}) {
  return (
    <span className="pccs-switch">
      <input
        id={id}
        type="checkbox"
        role="switch"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <i aria-hidden="true" />
    </span>
  );
}

function Card({
  title,
  description,
  aside,
  children,
}: {
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="pccs-card">
      <div className="pccs-card-h">
        <div>
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        {aside}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  description,
  controlId,
  warm,
  error,
  children,
  extra,
  searchText,
}: {
  label: string;
  description?: ReactNode;
  /** Plain-text description used by the filter when `description` is rich. */
  searchText?: string;
  controlId?: string;
  warm?: boolean;
  error?: string;
  children: ReactNode;
  extra?: ReactNode;
}) {
  const filter = useContext(FilterContext);
  if (!matches(filter, label, searchText ?? (typeof description === "string" ? description : undefined))) return null;
  return (
    <div className={`pccs-row${warm ? " pccs-row-warm" : ""}`}>
      <div className="pccs-lbl">
        {controlId ? (
          <label className="pccs-lbl-title" htmlFor={controlId}>
            {label}
          </label>
        ) : (
          <b className="pccs-lbl-title">{label}</b>
        )}
        {description && <span className="pccs-lbl-desc">{description}</span>}
      </div>
      <div className="pccs-ctl">{children}</div>
      {extra}
      {error && (
        <p className="pccs-row-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function SignupModeControl({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const index = Math.max(
    0,
    SIGNUP_MODES.findIndex((mode) => mode.value === value),
  );
  function onKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    let next = index + step;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = SIGNUP_MODES.length - 1;
    else if (!step) return;
    event.preventDefault();
    next = (next + SIGNUP_MODES.length) % SIGNUP_MODES.length;
    onChange(SIGNUP_MODES[next]!.value);
    refs.current[next]?.focus();
  }
  return (
    <div className="pccs-ctl pccs-seg" role="radiogroup" aria-label="Signup mode">
      {SIGNUP_MODES.map((mode, position) => {
        const checked = position === index;
        return (
          <button
            key={mode.value}
            ref={(node) => {
              refs.current[position] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            className="pccs-seg-btn"
            onClick={() => onChange(mode.value)}
            onKeyDown={onKeyDown}
          >
            {mode.label}
          </button>
        );
      })}
    </div>
  );
}

function useScrollSpy(ids: readonly string[], enabled: boolean): [string, (id: string) => void] {
  const [active, setActive] = useState<string>(ids[0] ?? "");
  useEffect(() => {
    if (!enabled || typeof IntersectionObserver === "undefined") return;
    const visible = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) visible.set(entry.target.id, entry.isIntersecting);
        const first = ids.find((id) => visible.get(id));
        if (first) setActive(first);
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    for (const id of ids) {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, [ids, enabled]);
  return [active, setActive];
}

const SECTION_IDS: readonly SectionId[] = NAV_GROUPS.flatMap((group) => group.items.map(([id]) => id));

export default function PlatformSettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [publicState, setPublicState] = useState<PublicSignupState | null>(null);
  const [dvla, setDvla] = useState<DrivewayDvlaStatus | null>(null);
  const [dvsa, setDvsa] = useState<DrivewayDvsaStatus | null>(null);
  const [syslog, setSyslog] = useState<SyslogSettings | null>(null);
  const [syslogDraft, setSyslogDraft] = useState<SyslogSettings | null>(null);
  const [syslogDiagnostics, setSyslogDiagnostics] = useState<SyslogDiagnostics | null>(null);
  const [syslogErrors, setSyslogErrors] = useState<SyslogFieldErrors>({});
  const [syslogSaveError, setSyslogSaveError] = useState("");
  const [syslogTest, setSyslogTest] = useState({ busy: false, result: "" });
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [testRegistration, setTestRegistration] = useState("");
  const [dvlaTest, setDvlaTest] = useState({ busy: false, result: "" });
  const [dvsaTest, setDvsaTest] = useState({ busy: false, result: "" });
  const [error, setError] = useState("");
  const ids = useId();
  const [activeSection, setActiveSection] = useScrollSpy(SECTION_IDS, Boolean(data) && !filter.trim());

  const load = useCallback(async (keep?: { keys: Set<string>; syslog: boolean }) => {
    setError("");
    try {
      const [settings, signupState, dvlaStatus, dvsaStatus, syslogStatus, diagnostics] = await Promise.all([
        platformApi.get<SettingsResponse>("/settings"),
        platformApi.get<PublicSignupState>("/signup-state"),
        platformApi.get<DrivewayDvlaStatus>("/integrations/dvla"),
        platformApi.get<DrivewayDvsaStatus>("/integrations/dvsa"),
        platformApi.get<SyslogSettings>("/logging/syslog"),
        platformApi.get<SyslogDiagnostics>("/logging/syslog/diagnostics"),
      ]);
      setData(settings);
      setPublicState(signupState);
      setDvla(dvlaStatus);
      setDvsa(dvsaStatus);
      const nextSyslog = normaliseSyslog(syslogStatus);
      setSyslog(nextSyslog);
      if (!keep?.syslog) setSyslogDraft(nextSyslog);
      setSyslogDiagnostics(diagnostics);
      setDrafts((current) => (keep ? Object.fromEntries(Object.entries(current).filter(([key]) => keep.keys.has(key))) : {}));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => data?.settings ?? [], [data]);
  const byKey = useMemo(() => new Map(items.map((item) => [item.key, item])), [items]);
  const draftOf = (item: SettingItem): Draft => drafts[item.key] ?? baselineDraft(item);
  const changed = useMemo(
    () =>
      items.filter(
        (item) => item.editable && !READ_ONLY_KEYS.has(item.key) && item.key in drafts && isDirty(item, drafts[item.key]!),
      ),
    [items, drafts],
  );
  const syslogDirty = Boolean(syslog && syslogDraft && syslogComparable(syslog) !== syslogComparable(syslogDraft));
  const changeNames = [...changed.map((item) => copyFor(item.key, item).label), ...(syslogDirty ? ["Central logging"] : [])];
  const changeCount = changeNames.length;
  const dirty = changeCount > 0;

  function setDraft(key: string, value: Draft) {
    setDrafts((current) => ({ ...current, [key]: value }));
    setSaveMessage("");
  }

  function updateSyslog(patch: Partial<SyslogSettings>) {
    setSyslogDraft((current) => (current ? { ...current, ...patch } : current));
    setSyslogErrors({});
    setSyslogSaveError("");
    setSaveMessage("");
  }

  // Warn before leaving with unsaved edits: browser unload, and in-app link
  // navigation (captured before Next's router sees the click).
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    function onClick(event: MouseEvent) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!anchor || anchor.getAttribute("target") === "_blank") return;
      const href = anchor.getAttribute("href") ?? "";
      if (href.startsWith("#")) return;
      if (!window.confirm("You have unsaved changes. Leave this page without saving them?")) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  function discard() {
    setDrafts({});
    if (syslog) setSyslogDraft(syslog);
    setSyslogErrors({});
    setSyslogSaveError("");
    setRowErrors({});
    setReason("");
    setReasonError("");
    setSaveMessage("");
  }

  function requestSave() {
    if (!dirty || saving) return;
    if (reason.trim().length < 10) {
      setReasonError("Reason for change must be at least 10 characters.");
      return;
    }
    if (syslogDirty && syslogDraft) {
      const errors = validateSyslog(syslogDraft);
      setSyslogErrors(errors);
      if (Object.keys(errors).length) return;
    }
    if (changed.some((item) => item.risk === "sensitive")) {
      setConfirmOpen(true);
      return;
    }
    void performSave();
  }

  async function performSave() {
    setConfirmOpen(false);
    setSaving(true);
    setSaveMessage("");
    const auditReason = reason.trim();
    const failures: Record<string, string> = {};
    for (const item of changed) {
      try {
        await platformApi.put(`/settings/${item.key}`, {
          value: parseDraft(item, drafts[item.key]!),
          reason: auditReason,
          confirmed: true,
        });
      } catch (cause) {
        failures[item.key] = cause instanceof Error ? cause.message : "This change could not be saved.";
      }
    }
    let syslogFailed = false;
    if (syslogDirty && syslogDraft) {
      try {
        await platformApi.put<SyslogSettings>("/logging/syslog", {
          enabled: syslogDraft.enabled,
          host: syslogDraft.host,
          port: syslogDraft.port,
          protocol: syslogDraft.protocol,
          facility: syslogDraft.facility,
          environment: syslogDraft.environment,
          tls_verify: syslogDraft.tls_verify,
          minimum_level: syslogDraft.minimum_level,
          categories: syslogDraft.categories,
          reason: auditReason,
          confirmed: true,
        });
      } catch (cause) {
        syslogFailed = true;
        const message = cause instanceof Error ? cause.message : "Unable to save central logging settings.";
        const lower = message.toLowerCase();
        if (lower.includes("host")) setSyslogErrors({ host: message });
        else if (lower.includes("port")) setSyslogErrors({ port: message });
        else if (lower.includes("facility")) setSyslogErrors({ facility: message });
        else setSyslogSaveError(message);
      }
    }
    await load({ keys: new Set(Object.keys(failures)), syslog: syslogFailed });
    setRowErrors(failures);
    const failed = Object.keys(failures).length + (syslogFailed ? 1 : 0);
    if (failed === 0) {
      setReason("");
      setReasonError("");
      setSaveMessage("Changes saved.");
    } else {
      setSaveMessage(`${failed} ${failed === 1 ? "change" : "changes"} could not be saved. ${failed === 1 ? "It is" : "They are"} still marked below.`);
    }
    setSaving(false);
  }

  async function refreshIntegrations() {
    const [dvlaStatus, dvsaStatus] = await Promise.all([
      platformApi.get<DrivewayDvlaStatus>("/integrations/dvla"),
      platformApi.get<DrivewayDvsaStatus>("/integrations/dvsa"),
    ]);
    setDvla(dvlaStatus);
    setDvsa(dvsaStatus);
  }

  async function testProvider(provider: "dvla" | "dvsa") {
    const set = provider === "dvla" ? setDvlaTest : setDvsaTest;
    if (!testRegistration.trim()) return;
    set({ busy: true, result: "" });
    try {
      const result = await platformApi.post<{ message: string }>(`/integrations/${provider}/test`, {
        registration: testRegistration,
        reason:
          provider === "dvla"
            ? "Verify the configured DVLA vehicle lookup connection"
            : "Verify the configured DVSA MOT History connection",
        confirmed: true,
      });
      set({ busy: false, result: result.message });
      await refreshIntegrations().catch(() => undefined);
    } catch (cause) {
      set({
        busy: false,
        result: cause instanceof Error ? cause.message : `The ${provider.toUpperCase()} connection test failed.`,
      });
    }
  }

  async function testSyslog() {
    if (syslogTest.busy || !syslog?.enabled || syslogDirty) return;
    setSyslogTest({ busy: true, result: "" });
    try {
      const result = await platformApi.post<{ message: string }>("/logging/syslog/test", {
        reason: "Verify the configured central logging destination",
        confirmed: true,
      });
      setSyslogTest({ busy: false, result: result.message });
      const [status, diagnostics] = await Promise.all([
        platformApi.get<SyslogSettings>("/logging/syslog"),
        platformApi.get<SyslogDiagnostics>("/logging/syslog/diagnostics"),
      ]);
      const next = normaliseSyslog(status);
      setSyslog(next);
      setSyslogDraft(next);
      setSyslogDiagnostics(diagnostics);
    } catch (cause) {
      setSyslogTest({ busy: false, result: cause instanceof Error ? cause.message : "The syslog test failed." });
    }
  }

  const timezones = useMemo(() => {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    const list = supported ? supported("timeZone") : ["Africa/Johannesburg", "Europe/London", "UTC"];
    return list.includes("UTC") ? list : [...list, "UTC"];
  }, []);

  // ---- rendering helpers ------------------------------------------------

  const controlId = (key: string) => `${ids}-${key}`;

  function settingRow(key: string, options: { width?: "sm" | "md" | "lg"; placeholder?: string; warm?: boolean; suffix?: string } = {}) {
    const item = byKey.get(key);
    if (!item) return null;
    const { label, description } = copyFor(key, item);
    const draft = draftOf(item);
    const id = controlId(key);
    const control =
      item.value_type === "boolean" ? (
        <Switch id={id} label={label} checked={Boolean(draft)} onChange={(checked) => setDraft(key, checked)} />
      ) : (
        <>
          <input
            id={id}
            className={`pccs-in${options.width ? ` pccs-w-${options.width}` : ""}`}
            type={item.value_type === "integer" ? "number" : item.value_type === "email" ? "email" : item.value_type === "url" ? "url" : "text"}
            min={item.value_type === "integer" ? 1 : undefined}
            max={item.value_type === "integer" ? 10000 : undefined}
            value={String(draft)}
            placeholder={options.placeholder}
            aria-describedby={rowErrors[key] ? `${id}-error` : undefined}
            onChange={(event) => setDraft(key, event.target.value)}
          />
          {options.suffix && <span className="pccs-suffix">{options.suffix}</span>}
        </>
      );
    return (
      <Row
        key={key}
        label={label}
        description={description}
        controlId={item.value_type === "boolean" ? undefined : id}
        warm={options.warm}
        error={rowErrors[key]}
      >
        {control}
      </Row>
    );
  }

  function selectRow(key: string, choices: Array<[string, string]>) {
    const item = byKey.get(key);
    if (!item) return null;
    const { label, description } = copyFor(key, item);
    const draft = String(draftOf(item));
    const id = controlId(key);
    const options = [...choices];
    if (draft && !options.some(([value]) => value === draft)) options.unshift([draft, draft]);
    return (
      <Row key={key} label={label} description={description} controlId={id} error={rowErrors[key]}>
        <select id={id} className="pccs-in" value={draft} onChange={(event) => setDraft(key, event.target.value)}>
          {!draft && <option value="">Not set</option>}
          {options.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      </Row>
    );
  }

  function cardVisible(...terms: Array<string | undefined>) {
    return matches(filter, ...terms);
  }

  function rowTerms(...keys: string[]): string[] {
    return keys.flatMap((key) => {
      const copy = copyFor(key, byKey.get(key));
      return byKey.has(key) || key in COPY ? [copy.label, copy.description ?? ""] : [];
    });
  }

  // ---- derived display state -------------------------------------------

  const signupItem = byKey.get("signup_mode");
  const signupDraft = signupItem ? String(draftOf(signupItem) || "normal") : "normal";
  const signupSelected = SIGNUP_MODES.find((mode) => mode.value === signupDraft) ?? SIGNUP_MODES[0];
  const savedSignup = SIGNUP_MODES.find((mode) => mode.value === String(signupItem?.value ?? "normal")) ?? SIGNUP_MODES[0];
  const maintenanceOn = byKey.get("maintenance_mode")?.value === true;
  const configuredCount = (dvla?.configured ? 1 : 0) + (dvsa?.configured ? 1 : 0);
  const regionalNotEnforced = ["default_locale", "default_timezone"].some((key) => byKey.get(key)?.runtime_effect === "not_enforced");
  const summary = registrationSummary(items, publicState);
  const stripMode = publicState?.signup_mode ?? String(signupItem?.value ?? "normal");

  const visible = {
    env: cardVisible("Environment", "Public URL", "Admin URL", "Status URL"),
    integrations: cardVisible("Driveway integrations", ...rowTerms("driveway_dvla_enabled", "driveway_dvsa_enabled")),
    logging: cardVisible(...LOGGING_TERMS),
    general: cardVisible("General", ...rowTerms("platform_display_name", "maintenance_mode")),
    operations: cardVisible("Operations", ...rowTerms("home_migration_enabled")),
    limits: cardVisible("Home limits", ...rowTerms("maximum_homes_per_user", "maximum_members_per_home")),
    support: cardVisible("Support", ...rowTerms("support_contact_address", "service_status_url")),
    regional: cardVisible("Regional", ...rowTerms("default_locale", "default_timezone")),
    legal: cardVisible("Legal", ...rowTerms("privacy_notice_version", "terms_version")),
    registration: cardVisible(
      "Registration & access",
      ...rowTerms("signup_mode", "registration_enabled", "invite_only_mode", "allowed_registration_domains", "invitation_expiry_days"),
    ),
  } satisfies Record<SectionId, boolean>;
  // When the card title itself matches, show every row in it.
  const titleMatch = (title: string) => filter.trim() !== "" && matches(filter, title);
  const anyVisible = Object.values(visible).some(Boolean);

  const dvlaDescription = dvla && (
    <>
      Add vehicles by registration via the DVLA provider.{" "}
      {dvla.configured
        ? [dvla.environment, dvla.endpoint].filter(Boolean).join(" · ")
        : "API key and endpoint are not configured."}
      {dvla.last_success_at && <> · Last lookup {formatTimestamp(dvla.last_success_at)}</>}
      {dvla.last_failure_at && <> · Last failed lookup {formatTimestamp(dvla.last_failure_at)}</>}
      {dvla.last_failure_summary && <> · {dvla.last_failure_summary}</>}
      {dvla.configured && "."}
    </>
  );
  const dvsaLastRequest = dvsa ? latest(dvsa.last_success_at, dvsa.last_failure_at) : null;
  const dvsaDescription = dvsa && (
    <>
      Refresh MOT status and history.{" "}
      {dvsaLastRequest ? `Last request ${formatTimestamp(dvsaLastRequest)} · ` : ""}
      credentials {dvsa.configured ? "configured" : "not configured"}
      {dvsa.environment && <> · {dvsa.environment}</>}
      {!dvsa.deployment_enabled && <> · deployment switch off</>}
      {dvsa.last_failure_category && <> · Last error: {DVSA_FAILURE_LABELS[dvsa.last_failure_category] ?? "Provider error"}</>}
      .
    </>
  );

  const deliveredAt = formatTimestamp(syslog?.last_successful_delivery, false);

  return (
    <PlatformShell>
      <FilterContext.Provider value={filter}>
        <div className="pccs-root">
          <main className="pccs">
            <div className="pccs-crumb">
              <Link href="/">Overview</Link> / Settings
            </div>
            <div className="pccs-head">
              <div>
                <h1>Settings</h1>
                <p>Platform-wide configuration. Changes are audited and need a reason.</p>
              </div>
              <label className="pccs-filter">
                <span className="pccs-sr">Filter settings</span>
                <input
                  className="pccs-in"
                  type="search"
                  placeholder="Filter settings…"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                />
              </label>
            </div>

            {error && <CcNotice tone="error">{error}</CcNotice>}
            {saveMessage && (
              <p className="pccs-save-message" role="status">
                {saveMessage}
              </p>
            )}

            {!data && !error ? (
              <CcLoadingState label="Loading settings…" />
            ) : (
              data && (
                <>
                  <div className="pccs-tiles">
                    <div className="pccs-tile">
                      <small>Environment</small>
                      <b>{data.deployment_environment ?? "Unknown"}</b>
                    </div>
                    <div className="pccs-tile">
                      <small>Driveway integrations</small>
                      <Badge tone={configuredCount === 2 ? "ok" : "warn"} dot>
                        {configuredCount} of 2 configured
                      </Badge>
                    </div>
                    <div className="pccs-tile">
                      <small>Central logging</small>
                      {syslog?.enabled ? (
                        <Badge tone="ok" dot>
                          Enabled · {syslog.dropped_count} dropped
                        </Badge>
                      ) : (
                        <Badge tone="off" dot>
                          Disabled
                        </Badge>
                      )}
                    </div>
                    <div className="pccs-tile">
                      <small>Signup mode</small>
                      <Badge tone="info">{savedSignup.label}</Badge>
                    </div>
                    <div className="pccs-tile">
                      <small>Maintenance mode</small>
                      <Badge tone={maintenanceOn ? "warn" : "off"}>{maintenanceOn ? "On" : "Off"}</Badge>
                    </div>
                  </div>

                  <div className="pccs-cols">
                    <nav className="pccs-sub" aria-label="Settings sections">
                      {NAV_GROUPS.map((group) => (
                        <div key={group.label}>
                          <div className="pccs-grp">{group.label}</div>
                          {group.items.map(([id, label]) => (
                            <a
                              key={id}
                              href={`#${id}`}
                              className={activeSection === id ? "pccs-on" : undefined}
                              aria-current={activeSection === id ? "true" : undefined}
                              onClick={() => setActiveSection(id)}
                            >
                              {label}
                            </a>
                          ))}
                        </div>
                      ))}
                    </nav>

                    <div className="pccs-main">
                      {!anyVisible && <p className="pccs-empty">No settings match “{filter.trim()}”.</p>}

                      {/* SYSTEM */}
                      {visible.env && (
                        <section id="env" className="pccs-sec" aria-label="Environment">
                          <h2 className="pccs-sec-t">System</h2>
                          <Card title="Environment" description="Managed by the deployment — edit the server’s env and redeploy." aside={<Badge tone="off">Read-only</Badge>}>
                            {data.environment.map((item) => (
                              <div key={item.key} className="pccs-row">
                                <div className="pccs-lbl">
                                  <b className="pccs-lbl-title">{ENVIRONMENT_LABELS[item.key] ?? item.key}</b>
                                </div>
                                <div className="pccs-ctl pccs-ro">{item.value}</div>
                              </div>
                            ))}
                          </Card>
                        </section>
                      )}

                      {visible.integrations && (
                        <section id="integrations" className="pccs-sec" aria-label="Integrations">
                          {!visible.env && <h2 className="pccs-sec-t">System</h2>}
                          <Card
                            title="Driveway integrations"
                            description="UK vehicle lookups for the Driveway area of the app."
                            aside={
                              <div className="pccs-aside">
                                <label className="pccs-aside-label" htmlFor={`${ids}-test-reg`}>
                                  Test reg
                                </label>
                                <input
                                  id={`${ids}-test-reg`}
                                  className="pccs-in pccs-reg"
                                  value={testRegistration}
                                  placeholder="AB12 CDE"
                                  onChange={(event) => setTestRegistration(event.target.value)}
                                />
                              </div>
                            }
                          >
                            <FilterContext.Provider value={titleMatch("Driveway integrations") ? "" : filter}>
                              {byKey.has("driveway_dvla_enabled") ? (
                                <Row
                                  label="DVLA vehicle lookup"
                                  description={dvlaDescription}
                                  searchText={COPY.driveway_dvla_enabled!.description}
                                  error={rowErrors.driveway_dvla_enabled}
                                  extra={
                                    <>
                                      {dvla?.environment === "Production" && (
                                        <p className="pccs-row-note pccs-row-note-warn">Production DVLA service — lookups here use real, live vehicle data.</p>
                                      )}
                                      {dvlaTest.result && (
                                        <p className="pccs-row-note" role="status">
                                          {dvlaTest.result}
                                        </p>
                                      )}
                                    </>
                                  }
                                >
                                  <Badge tone={healthTone(dvla?.health.state)} dot>
                                    {dvla?.health.state ?? "Unknown"}
                                  </Badge>
                                  <button
                                    type="button"
                                    className="pccs-btn"
                                    aria-label="Test DVLA connection"
                                    disabled={dvlaTest.busy || !testRegistration.trim() || !dvla?.configured}
                                    onClick={() => void testProvider("dvla")}
                                  >
                                    {dvlaTest.busy ? "Testing…" : "Test"}
                                  </button>
                                  <Switch
                                    label="Enable DVLA vehicle lookup"
                                    checked={Boolean(draftOf(byKey.get("driveway_dvla_enabled")!))}
                                    onChange={(checked) => setDraft("driveway_dvla_enabled", checked)}
                                  />
                                </Row>
                              ) : null}
                              {byKey.has("driveway_dvsa_enabled") ? (
                                <Row
                                  label="DVSA MOT history"
                                  description={dvsaDescription}
                                  searchText={COPY.driveway_dvsa_enabled!.description}
                                  error={rowErrors.driveway_dvsa_enabled}
                                  extra={
                                    dvsaTest.result && (
                                      <p className="pccs-row-note" role="status">
                                        {dvsaTest.result}
                                      </p>
                                    )
                                  }
                                >
                                  <Badge tone={healthTone(dvsa?.health.state)} dot>
                                    {dvsa?.health.state ?? "Unknown"}
                                  </Badge>
                                  <button
                                    type="button"
                                    className="pccs-btn"
                                    aria-label="Test DVSA connection"
                                    disabled={dvsaTest.busy || !testRegistration.trim() || !dvsa?.configured}
                                    onClick={() => void testProvider("dvsa")}
                                  >
                                    {dvsaTest.busy ? "Testing…" : "Test"}
                                  </button>
                                  <Switch
                                    label="Enable DVSA MOT history"
                                    checked={Boolean(draftOf(byKey.get("driveway_dvsa_enabled")!))}
                                    onChange={(checked) => setDraft("driveway_dvsa_enabled", checked)}
                                  />
                                </Row>
                              ) : null}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.logging && syslog && syslogDraft && (
                        <section id="logging" className="pccs-sec" aria-label="Central logging">
                          {!visible.env && !visible.integrations && <h2 className="pccs-sec-t">System</h2>}
                          <Card
                            title="Central logging"
                            description="Forward structured platform logs to an RFC 5424 syslog destination. Secrets and household data are never sent."
                            aside={
                              <div className="pccs-aside">
                                {syslog.last_error ? (
                                  <Badge tone="warn" dot>
                                    Delivery failing
                                  </Badge>
                                ) : deliveredAt ? (
                                  <Badge tone="ok" dot>
                                    Last delivery {deliveredAt}
                                  </Badge>
                                ) : (
                                  <Badge tone="off" dot>
                                    No delivery yet
                                  </Badge>
                                )}
                                <button
                                  type="button"
                                  className="pccs-btn"
                                  disabled={syslogTest.busy || !syslog.enabled || syslogDirty}
                                  onClick={() => void testSyslog()}
                                >
                                  {syslogTest.busy ? "Sending…" : "Send test"}
                                </button>
                                <Switch label="Enable central logging" checked={syslogDraft.enabled} onChange={(checked) => updateSyslog({ enabled: checked })} />
                              </div>
                            }
                          >
                            <div className="pccs-grid">
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-host`}>Host</label>
                                <input id={`${ids}-host`} className="pccs-in" value={syslogDraft.host} aria-invalid={Boolean(syslogErrors.host)} onChange={(event) => updateSyslog({ host: event.target.value })} />
                                {syslogErrors.host && <p className="pccs-field-error" role="alert">{syslogErrors.host}</p>}
                              </div>
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-port`}>Port</label>
                                <input id={`${ids}-port`} className="pccs-in" type="number" min={1} max={65535} value={syslogDraft.port} aria-invalid={Boolean(syslogErrors.port)} onChange={(event) => updateSyslog({ port: Number(event.target.value) })} />
                                {syslogErrors.port && <p className="pccs-field-error" role="alert">{syslogErrors.port}</p>}
                              </div>
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-protocol`}>Protocol</label>
                                <select id={`${ids}-protocol`} className="pccs-in" value={syslogDraft.protocol} onChange={(event) => updateSyslog({ protocol: event.target.value as SyslogSettings["protocol"] })}>
                                  <option value="udp">UDP</option>
                                  <option value="tcp">TCP</option>
                                  <option value="tls">TLS</option>
                                </select>
                              </div>
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-facility`}>Facility</label>
                                <select id={`${ids}-facility`} className="pccs-in" value={syslogDraft.facility} aria-invalid={Boolean(syslogErrors.facility)} onChange={(event) => updateSyslog({ facility: Number(event.target.value) })}>
                                  {SYSLOG_FACILITIES.map((facility) => (
                                    <option key={facility.value} value={facility.value}>
                                      {facility.label}
                                    </option>
                                  ))}
                                </select>
                                {syslogErrors.facility && <p className="pccs-field-error" role="alert">{syslogErrors.facility}</p>}
                              </div>
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-level`}>Minimum level</label>
                                <select id={`${ids}-level`} className="pccs-in" value={syslogDraft.minimum_level} onChange={(event) => updateSyslog({ minimum_level: event.target.value as SyslogSettings["minimum_level"] })}>
                                  {SYSLOG_LEVELS.map((level) => (
                                    <option key={level.value} value={level.value}>
                                      {level.label}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <div className="pccs-f">
                                <label htmlFor={`${ids}-env-tag`}>Environment tag</label>
                                <input id={`${ids}-env-tag`} className="pccs-in" maxLength={80} value={syslogDraft.environment} onChange={(event) => updateSyslog({ environment: event.target.value })} />
                              </div>
                            </div>
                            <div className="pccs-events">
                              <div className="pccs-events-t" id={`${ids}-events`}>
                                Events to send
                              </div>
                              <div className="pccs-chips" role="group" aria-labelledby={`${ids}-events`}>
                                {SYSLOG_CATEGORIES.map((category) => (
                                  <label key={category.value} className="pccs-chip">
                                    <input
                                      type="checkbox"
                                      checked={syslogDraft.categories.includes(category.value)}
                                      onChange={(event) =>
                                        updateSyslog({
                                          categories: event.target.checked
                                            ? [...syslogDraft.categories, category.value]
                                            : syslogDraft.categories.filter((value) => value !== category.value),
                                        })
                                      }
                                    />
                                    {category.label}
                                  </label>
                                ))}
                              </div>
                              {syslogDraft.categories.length === 0 && (
                                <p className="pccs-hint">Central logging stays enabled, but no normal application events will be forwarded.</p>
                              )}
                              <div className="pccs-tls">
                                <label className="pccs-chip pccs-chip-bare">
                                  <input
                                    type="checkbox"
                                    checked={syslogDraft.tls_verify}
                                    disabled={syslogDraft.protocol !== "tls"}
                                    onChange={(event) => updateSyslog({ tls_verify: event.target.checked })}
                                  />
                                  Verify TLS certificate
                                </label>
                                <span>· only applies to TLS</span>
                              </div>
                              {syslog.last_error && <p className="pccs-hint pccs-hint-warn">Last error: {syslog.last_error}</p>}
                              {syslogSaveError && <p className="pccs-field-error" role="alert">{syslogSaveError}</p>}
                              {syslogTest.result && (
                                <p className="pccs-hint" role="status">
                                  {syslogTest.result}
                                </p>
                              )}
                              {syslogDiagnostics && (
                                <details className="pccs-diag">
                                  <summary>Advanced diagnostics</summary>
                                  <dl>
                                    {(
                                      [
                                        ["Events seen", syslogDiagnostics.events_seen],
                                        ["Events queued", syslogDiagnostics.events_queued],
                                        ["Events sent", syslogDiagnostics.events_sent],
                                        ["Events filtered", syslogDiagnostics.events_filtered],
                                        ["Category-filtered", syslogDiagnostics.events_category_filtered],
                                        ["Events dropped", syslogDiagnostics.events_dropped],
                                        ["Transport failures", syslogDiagnostics.transport_failures],
                                      ] as const
                                    ).map(([label, value]) => (
                                      <div key={label}>
                                        <dt>{label}</dt>
                                        <dd>{value}</dd>
                                      </div>
                                    ))}
                                  </dl>
                                </details>
                              )}
                            </div>
                          </Card>
                        </section>
                      )}

                      {/* PLATFORM */}
                      {visible.general && (
                        <section id="general" className="pccs-sec" aria-label="General">
                          <h2 className="pccs-sec-t">Platform</h2>
                          <Card title="General">
                            <FilterContext.Provider value={titleMatch("General") ? "" : filter}>
                              {settingRow("platform_display_name", { placeholder: "MyKhaya" })}
                              {settingRow("maintenance_mode", { warm: true })}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.operations && (
                        <section id="operations" className="pccs-sec" aria-label="Operations">
                          {!visible.general && <h2 className="pccs-sec-t">Platform</h2>}
                          <Card title="Operations">
                            <FilterContext.Provider value={titleMatch("Operations") ? "" : filter}>
                              {settingRow("home_migration_enabled")}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.limits && (
                        <section id="limits" className="pccs-sec" aria-label="Home limits">
                          {!visible.general && !visible.operations && <h2 className="pccs-sec-t">Platform</h2>}
                          <Card title="Home limits" description="Leave blank for no limit.">
                            <FilterContext.Provider value={titleMatch("Home limits") ? "" : filter}>
                              {settingRow("maximum_homes_per_user", { width: "md", placeholder: "No limit" })}
                              {settingRow("maximum_members_per_home", { width: "md", placeholder: "No limit" })}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {/* POLICY */}
                      {visible.support && (
                        <section id="support" className="pccs-sec" aria-label="Support">
                          <h2 className="pccs-sec-t">Policy</h2>
                          <Card title="Support">
                            <FilterContext.Provider value={titleMatch("Support") ? "" : filter}>
                              {settingRow("support_contact_address")}
                              {settingRow("service_status_url")}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.regional && (
                        <section id="regional" className="pccs-sec" aria-label="Regional">
                          {!visible.support && <h2 className="pccs-sec-t">Policy</h2>}
                          <Card
                            title="Regional"
                            description="Defaults for new accounts and homes."
                            aside={regionalNotEnforced ? <Badge tone="warn">Not yet enforced by the app</Badge> : undefined}
                          >
                            <FilterContext.Provider value={titleMatch("Regional") ? "" : filter}>
                              {selectRow("default_locale", LOCALES)}
                              {selectRow(
                                "default_timezone",
                                timezones.map((zone) => [zone, zone]),
                              )}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.legal && (
                        <section id="legal" className="pccs-sec" aria-label="Legal">
                          {!visible.support && !visible.regional && <h2 className="pccs-sec-t">Policy</h2>}
                          <Card title="Legal" description="Current published document versions.">
                            <FilterContext.Provider value={titleMatch("Legal") ? "" : filter}>
                              {settingRow("privacy_notice_version", { width: "lg", placeholder: "e.g. 2026-10" })}
                              {settingRow("terms_version", { width: "lg", placeholder: "e.g. 2026-10" })}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}

                      {visible.registration && (
                        <section id="registration" className="pccs-sec" aria-label="Registration & access">
                          {!visible.support && !visible.regional && !visible.legal && <h2 className="pccs-sec-t">Policy</h2>}
                          <Card title="Registration & access" description="What a new visitor can do right now.">
                            <div className="pccs-strip" aria-label="Effective registration behaviour">
                              <span>
                                Signup <Badge tone="info">{SIGNUP_STRIP_LABELS[stripMode] ?? stripMode}</Badge>
                              </span>
                              <span>
                                Normal signup{" "}
                                <Badge tone={summary.normalSignup === "Enabled" ? "ok" : "off"}>{summary.normalSignup}</Badge>
                              </span>
                              <span>
                                Founding Beta{" "}
                                <Badge tone={summary.betaSignup === "Enabled" ? "ok" : "off"}>{summary.betaSignup}</Badge>
                              </span>
                              <span>
                                Invitation{" "}
                                <Badge tone={summary.invitation === "Required" ? "warn" : "off"}>{summary.invitation}</Badge>
                              </span>
                              <span>
                                Email verification{" "}
                                <Badge tone={summary.emailVerification === "Required" ? "warn" : "off"}>{summary.emailVerification}</Badge>
                              </span>
                            </div>
                            <FilterContext.Provider value={titleMatch("Registration & access") ? "" : filter}>
                              {signupItem && (
                                <Row
                                  label={COPY.signup_mode!.label}
                                  description={COPY.signup_mode!.description}
                                  error={rowErrors.signup_mode}
                                  extra={
                                    <div className="pccs-mode-line">
                                      <Badge tone="info">{signupSelected.label}</Badge>
                                      {signupSelected.help}
                                    </div>
                                  }
                                >
                                  <SignupModeControl value={signupDraft} onChange={(value) => setDraft("signup_mode", value)} />
                                </Row>
                              )}
                              {settingRow("registration_enabled")}
                              {settingRow("invite_only_mode")}
                              {settingRow("allowed_registration_domains", { placeholder: "e.g. mykhaya.app" })}
                              {settingRow("invitation_expiry_days", { width: "sm", placeholder: "7", suffix: "days" })}
                            </FilterContext.Provider>
                          </Card>
                        </section>
                      )}
                    </div>
                  </div>
                </>
              )
            )}
          </main>

          {dirty && (
            <div className="pccs-savebar" role="region" aria-label="Unsaved changes">
              <div className="pccs-savebar-in">
                <div className="pccs-savebar-sum">
                  <b>
                    {changeCount} unsaved {changeCount === 1 ? "change" : "changes"}
                  </b>
                  <div>{changeNames.join(" · ")}</div>
                </div>
                <label className="pccs-savebar-reason">
                  <span className="pccs-sr">Reason for change</span>
                  <input
                    className="pccs-in"
                    value={reason}
                    maxLength={500}
                    placeholder="Reason for change (required, recorded in audit log)"
                    aria-invalid={Boolean(reasonError)}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setReasonError("");
                    }}
                  />
                  {reasonError && (
                    <span className="pccs-field-error" role="alert">
                      {reasonError}
                    </span>
                  )}
                </label>
                <button type="button" className="pccs-btn" onClick={discard} disabled={saving}>
                  Discard
                </button>
                <button type="button" className="pccs-btn pccs-btn-p" onClick={requestSave} disabled={saving || !reason.trim()}>
                  {saving ? "Saving…" : "Save changes"}
                </button>
              </div>
            </div>
          )}

          <CcDialog open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Save these changes?">
            <div className="cc-dialog-scroll">
              <ul className="pccs-confirm-list">
                {changed
                  .filter((item) => item.risk === "sensitive")
                  .map((item) => (
                    <li key={item.key}>{confirmationDescription(item, copyFor(item.key, item).label)}</li>
                  ))}
              </ul>
              <p>Reason recorded in the audit log: “{reason.trim()}”</p>
            </div>
            <CcDialogActions>
              <button type="button" className="secondary" onClick={() => setConfirmOpen(false)}>
                Cancel
              </button>
              <button type="button" className="danger" onClick={() => void performSave()}>
                Save changes
              </button>
            </CcDialogActions>
          </CcDialog>
        </div>
      </FilterContext.Provider>
    </PlatformShell>
  );
}
