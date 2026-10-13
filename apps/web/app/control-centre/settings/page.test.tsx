import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlatformSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/settings",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

type Item = Record<string, unknown> & { key: string };

function item(key: string, overrides: Record<string, unknown>): Item {
  return {
    key,
    label: key,
    description: `Backend description for ${key}.`,
    section: "General",
    value_type: "text",
    risk: "normal",
    runtime_effect: "effective",
    editable: true,
    consumer_visible: false,
    value: null,
    state: "unset",
    ...overrides,
  };
}

function baseSettings() {
  return {
    deployment_environment: "development",
    settings: [
      item("platform_display_name", { label: "Platform name", runtime_effect: "informational" }),
      item("service_status_url", { section: "Support", value_type: "url", value: "https://status.dev.mykhaya.app/", state: "default" }),
      item("support_contact_address", { section: "Support", value_type: "email", value: "support@mykhaya.app", state: "configured" }),
      item("maintenance_mode", { value_type: "boolean", risk: "sensitive", runtime_effect: "not_enforced", value: false }),
      item("maximum_homes_per_user", { section: "Home Limits", value_type: "integer" }),
      item("default_locale", { section: "Regional", runtime_effect: "not_enforced", value: "en-GB", state: "configured" }),
      item("driveway_dvla_enabled", { section: "Driveway integrations", value_type: "boolean", risk: "sensitive", value: false }),
      item("driveway_dvsa_enabled", { section: "Driveway integrations", value_type: "boolean", risk: "sensitive", value: false }),
      item("signup_mode", { section: "Signup", risk: "sensitive", value: "normal", state: "configured" }),
      item("registration_enabled", { section: "Registration & Access", value_type: "boolean", risk: "sensitive", value: true }),
      item("invite_only_mode", { section: "Registration & Access", value_type: "boolean", risk: "sensitive", value: false }),
      item("email_verification_required", { section: "Registration & Access", value_type: "boolean", risk: "sensitive", value: true, state: "default" }),
      item("allowed_registration_domains", { section: "Registration & Access", value_type: "list", risk: "sensitive" }),
      item("invitation_expiry_days", { section: "Registration & Access", value_type: "integer" }),
    ],
    environment: [
      { key: "public_url", value: "https://dev.mykhaya.app", category: "environment_controlled", editable: false },
      { key: "admin_url", value: "https://admin.dev.mykhaya.app", category: "environment_controlled", editable: false },
    ],
  };
}

const SYSLOG = {
  enabled: false,
  configured: false,
  host: "",
  port: 6514,
  protocol: "tls",
  facility: 16,
  environment: "test",
  tls_verify: true,
  minimum_level: "INFO",
  categories: ["application", "http", "security", "audit", "worker", "integration"],
  last_successful_delivery: null,
  last_error: null,
  dropped_count: 0,
};

function mockRoutes(
  settings: ReturnType<typeof baseSettings> = baseSettings(),
  syslogOverrides: Record<string, unknown> = {},
  dvlaOverrides: Record<string, unknown> = {},
  dvsaOverrides: Record<string, unknown> = {},
) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/settings") return Promise.resolve(settings);
    if (path === "/signup-state")
      return Promise.resolve({
        signup_mode: "normal",
        registration_open: true,
        invitation_required: false,
        normal_signup_available: true,
        beta_joining_available: false,
        waitlist_available: false,
        joinable_count: 0,
      });
    if (path === "/integrations/dvla")
      return Promise.resolve({
        enabled: false,
        configured: false,
        environment: null,
        endpoint: null,
        health: { state: "Not configured" },
        last_success_at: null,
        last_success_summary: null,
        last_failure_at: null,
        last_failure_summary: null,
        ...dvlaOverrides,
      });
    if (path === "/integrations/dvsa")
      return Promise.resolve({
        enabled: false,
        deployment_enabled: false,
        configured: false,
        environment: null,
        health: { state: "Not configured" },
        last_success_at: null,
        last_failure_at: null,
        last_failure_category: null,
        ...dvsaOverrides,
      });
    if (path === "/logging/syslog") return Promise.resolve({ ...SYSLOG, ...syslogOverrides });
    if (path === "/logging/syslog/diagnostics")
      return Promise.resolve({ events_seen: 0, events_queued: 0, events_sent: 0, events_filtered: 0, events_category_filtered: 0, events_dropped: 0, transport_failures: 0 });
    throw new Error(`Unexpected GET ${path}`);
  });
}

function withValue(key: string, value: unknown) {
  const settings = baseSettings();
  return { ...settings, settings: settings.settings.map((row) => (row.key === key ? { ...row, value, state: "configured" } : row)) };
}

async function renderPage() {
  render(<PlatformSettingsPage />);
  await screen.findByRole("heading", { name: "Settings", level: 1 });
  await screen.findByRole("heading", { name: "General" });
}

function saveBar() {
  return screen.getByRole("region", { name: "Unsaved changes" });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRoutes();
});

afterEach(() => {
  // clearAllMocks (not restoreAllMocks) deliberately preserves each mock's
  // implementation: PlatformShell's unawaited auth refresh can still be in
  // flight when a test finishes.
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("PCC Settings — layout and live values", () => {
  it("renders the header, section navigation and grouped cards without raw setting keys", async () => {
    await renderPage();
    expect(screen.getByText("Platform-wide configuration. Changes are audited and need a reason.")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    for (const label of ["Environment", "Integrations", "Central logging", "General", "Operations", "Home limits", "Support", "Regional", "Legal", "Registration & access"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "System" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Platform" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Policy" })).toBeInTheDocument();
    expect(screen.getByLabelText("Platform name")).toBeInTheDocument();
    expect(screen.queryByText("platform_display_name")).not.toBeInTheDocument();
    expect(screen.queryByText("registration_enabled")).not.toBeInTheDocument();
  });

  it("fills the at-a-glance strip from live data", async () => {
    mockRoutes(withValue("signup_mode", "beta_only"), { enabled: true, dropped_count: 3 }, { configured: true });
    await renderPage();
    expect(get).toHaveBeenCalledWith("/signup-state");
    expect(screen.getByText("development")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 configured")).toBeInTheDocument();
    expect(screen.getByText("Enabled · 3 dropped")).toBeInTheDocument();
    expect(screen.getAllByText("Beta only").length).toBeGreaterThan(0);
  });

  it("shows deployment URLs read-only and existing values in their controls", async () => {
    await renderPage();
    expect(screen.getByText("https://admin.dev.mykhaya.app")).toBeInTheDocument();
    expect(screen.getByLabelText("Service status page")).toHaveValue("https://status.dev.mykhaya.app/");
    expect(screen.getByLabelText("Max homes per user")).toHaveAttribute("placeholder", "No limit");
    expect(screen.getByLabelText("Default language")).toHaveValue("en-GB");
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("marks Regional as not yet enforced only when the server says so", async () => {
    await renderPage();
    expect(screen.getByText("Not yet enforced by the app")).toBeInTheDocument();
    const settings = baseSettings();
    settings.settings = settings.settings.map((row) => (row.key === "default_locale" ? { ...row, runtime_effect: "effective" } : row));
    mockRoutes(settings);
    document.body.innerHTML = "";
    await renderPage();
    expect(screen.queryByText("Not yet enforced by the app")).not.toBeInTheDocument();
  });

  it("filters rows by label or description", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.type(screen.getByPlaceholderText("Filter settings…"), "maintenance");
    expect(screen.getByRole("switch", { name: "Maintenance mode" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Platform name")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Support" })).not.toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText("Filter settings…"));
    await user.type(screen.getByPlaceholderText("Filter settings…"), "zzzz");
    expect(screen.getByText("No settings match “zzzz”.")).toBeInTheDocument();
  });
});

describe("PCC Settings — unified save bar", () => {
  it("is hidden until something changes and lists each changed setting", async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reason for this change")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    await user.click(screen.getByRole("switch", { name: "Maintenance mode" }));
    const bar = saveBar();
    expect(within(bar).getByText("2 unsaved changes")).toBeInTheDocument();
    expect(within(bar).getByText("Platform name · Maintenance mode")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("never treats a reverted edit or a read-only setting as dirty", async () => {
    const user = userEvent.setup();
    await renderPage();
    const toggle = screen.getByRole("switch", { name: "Maintenance mode" });
    await user.click(toggle);
    await user.click(toggle);
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /email verification/i })).not.toBeInTheDocument();
  });

  it("saves every changed setting with the single reason, then clears the bar", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({});
    await renderPage();
    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    await user.clear(screen.getByLabelText("Support email"));
    await user.type(screen.getByLabelText("Support email"), "help@mykhaya.app");
    await user.type(screen.getByLabelText("Max homes per user"), "5");
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Routine platform update");

    mockRoutes({
      ...baseSettings(),
      settings: baseSettings().settings.map((row) =>
        row.key === "platform_display_name" ? { ...row, value: "MyKhaya" }
          : row.key === "support_contact_address" ? { ...row, value: "help@mykhaya.app" }
          : row.key === "maximum_homes_per_user" ? { ...row, value: 5 }
          : row,
      ),
    });
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(3));
    expect(put).toHaveBeenCalledWith("/settings/platform_display_name", { value: "MyKhaya", reason: "Routine platform update", confirmed: true });
    expect(put).toHaveBeenCalledWith("/settings/support_contact_address", { value: "help@mykhaya.app", reason: "Routine platform update", confirmed: true });
    expect(put).toHaveBeenCalledWith("/settings/maximum_homes_per_user", { value: 5, reason: "Routine platform update", confirmed: true });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Unsaved changes" })).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Changes saved.");
    expect(screen.getByLabelText("Platform name")).toHaveValue("MyKhaya");
  });

  it("requires a reason of at least 10 characters", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "short");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Reason for change must be at least 10 characters.")).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("keeps failed rows dirty with their own error after a partial failure", async () => {
    const user = userEvent.setup();
    put.mockImplementation((path: string) =>
      path === "/settings/service_status_url" ? Promise.reject(new Error("That must be a valid http(s) URL.")) : Promise.resolve({}),
    );
    await renderPage();
    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    fireEvent.change(screen.getByLabelText("Service status page"), { target: { value: "ftp://status.example.com" } });
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Routine platform update");
    mockRoutes(withValue("platform_display_name", "MyKhaya"));
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("That must be a valid http(s) URL.")).toBeInTheDocument();
    expect(screen.getByLabelText("Service status page")).toHaveValue("ftp://status.example.com");
    expect(within(saveBar()).getByText("1 unsaved change")).toBeInTheDocument();
    expect(within(saveBar()).getByText("Service status page")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 change could not be saved.");
  });

  it("discards every unsaved edit", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    await user.click(screen.getByRole("switch", { name: "Maintenance mode" }));
    await user.click(within(saveBar()).getByRole("button", { name: "Discard" }));
    expect(screen.getByLabelText("Platform name")).toHaveValue("");
    expect(screen.getByRole("switch", { name: "Maintenance mode" })).not.toBeChecked();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).not.toBeInTheDocument();
  });

  it("warns before leaving the page with unsaved changes", async () => {
    const user = userEvent.setup();
    await renderPage();
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    await user.type(screen.getByLabelText("Platform name"), "MyKhaya");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    // The sidebar link would navigate away; it must be held behind a confirm.
    const link = screen.getAllByRole("link", { name: "Overview" })[0]!;
    const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    link.dispatchEvent(click);
    expect(confirm).toHaveBeenCalled();
    expect(click.defaultPrevented).toBe(true);
  });
});

describe("PCC Settings — sensitive settings require confirmation", () => {
  it("confirms before saving a sensitive change, with runtime-effect copy", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({});
    await renderPage();
    await user.click(screen.getByRole("switch", { name: "Maintenance mode" }));
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Planned maintenance window");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/does not currently change user access or behaviour/i)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/settings/maintenance_mode", { value: true, reason: "Planned maintenance window", confirmed: true }),
    );
  });

  it("warns about real access effects for enforced settings", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole("switch", { name: "Allow new registrations" }));
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Pause new signups today");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Allow new registrations affects real user access or availability/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(put).not.toHaveBeenCalled();
  });
});

describe("PCC Settings — registration & access", () => {
  it("shows the effective behaviour strip and keeps email verification read-only", async () => {
    await renderPage();
    const strip = screen.getByLabelText("Effective registration behaviour");
    expect(within(strip).getByText("Normal signup")).toBeInTheDocument();
    expect(within(strip).getByText("Email verification")).toBeInTheDocument();
    expect(within(strip).getByText("Required")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /verification/i })).not.toBeInTheDocument();
  });

  it("selects signup mode with a radiogroup supporting arrow keys", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({});
    await renderPage();
    const group = screen.getByRole("radiogroup", { name: "Signup mode" });
    const normal = within(group).getByRole("radio", { name: "Normal" });
    expect(normal).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: "Mixed" })).toHaveAttribute("tabindex", "-1");

    normal.focus();
    await user.keyboard("{ArrowRight}");
    const beta = within(group).getByRole("radio", { name: "Beta only" });
    expect(beta).toHaveAttribute("aria-checked", "true");
    expect(beta).toHaveFocus();
    expect(screen.getByText("Only the approved Founding Beta registration path is available.")).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(within(group).getByRole("radio", { name: "Closed" })).toHaveAttribute("aria-checked", "true");

    expect(within(saveBar()).getByText("Signup mode")).toBeInTheDocument();
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Close signups for now");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/settings/signup_mode", { value: "closed", reason: "Close signups for now", confirmed: true }));
  });

  it("saves domains as a list and expiry as a number", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({});
    await renderPage();
    await user.type(screen.getByLabelText("Allowed email domains"), "mykhaya.app, example.com");
    await user.type(screen.getByLabelText("Invitation expiry"), "14");
    expect(screen.getByText("days")).toBeInTheDocument();
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Tighten registration access");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/settings/allowed_registration_domains", expect.objectContaining({ value: ["mykhaya.app", "example.com"] })));
    expect(put).toHaveBeenCalledWith("/settings/invitation_expiry_days", expect.objectContaining({ value: 14 }));
  });
});

describe("PCC Settings — central logging", () => {
  it("saves only the backend configuration contract with the shared reason", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ ...SYSLOG, enabled: true, configured: true, host: "graylog.internal" });
    await renderPage();
    await user.click(screen.getByRole("switch", { name: "Enable central logging" }));
    await user.type(screen.getByLabelText("Host"), "graylog.internal");
    expect(within(saveBar()).getByText("Central logging")).toBeInTheDocument();
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Enable central logging safely");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/logging/syslog", {
        enabled: true,
        host: "graylog.internal",
        port: 6514,
        protocol: "tls",
        facility: 16,
        environment: "test",
        tls_verify: true,
        minimum_level: "INFO",
        categories: ["application", "http", "security", "audit", "worker", "integration"],
        reason: "Enable central logging safely",
        confirmed: true,
      }),
    );
    const payload = put.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(payload).not.toHaveProperty("configured");
    expect(payload).not.toHaveProperty("dropped_count");
  });

  it("blocks saving an enabled configuration without a host", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole("switch", { name: "Enable central logging" }));
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Enable central logging safely");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    expect(put).not.toHaveBeenCalled();
    expect(screen.getByText("Host is required when central logging is enabled.")).toBeInTheDocument();
  });

  it("keeps Send test disabled until an enabled configuration is saved", async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(screen.getByRole("button", { name: "Send test" })).toBeDisabled();
    document.body.innerHTML = "";
    mockRoutes(baseSettings(), { enabled: true, configured: true, host: "graylog.internal" });
    await renderPage();
    const send = screen.getByRole("button", { name: "Send test" });
    expect(send).toBeEnabled();
    await user.selectOptions(screen.getByLabelText("Minimum level"), "WARNING");
    expect(send).toBeDisabled();
  });

  it("disables TLS verification for non-TLS protocols and explains an empty category selection", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.selectOptions(screen.getByLabelText("Protocol"), "udp");
    expect(screen.getByLabelText("Verify TLS certificate")).toBeDisabled();
    for (const label of ["Application", "HTTP / API requests", "Security & authentication", "Audit", "Workers & schedules", "External integrations"]) {
      await user.click(screen.getByLabelText(label));
    }
    expect(screen.getByText("Central logging stays enabled, but no normal application events will be forwarded.")).toBeInTheDocument();
  });

  it("renders last delivery as a short human-readable timestamp", async () => {
    mockRoutes(baseSettings(), { last_successful_delivery: "2026-09-28T18:30:20.818411+00:00" });
    await renderPage();
    expect(screen.queryByText(/2026-09-28T18:30/)).not.toBeInTheDocument();
    expect(screen.getByText(/Last delivery 28 Sept?, \d\d:\d\d/)).toBeInTheDocument();
  });
});

describe("PCC Settings — Driveway integrations", () => {
  it("shows status badges and keeps tests disabled until configured with a registration", async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    expect(screen.getByText(/API key and endpoint are not configured\./)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Test reg"), "AB12 CDE");
    expect(screen.getByRole("button", { name: "Test DVLA connection" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test DVSA connection" })).toBeDisabled();
  });

  it("shows DVLA environment, endpoint and lookup history but never the key", async () => {
    mockRoutes(baseSettings(), {}, {
      enabled: true,
      configured: true,
      environment: "UAT",
      endpoint: "https://uat.dvla.example/vehicle-enquiry",
      health: { state: "Degraded" },
      last_success_at: "2026-09-20T10:00:00Z",
      last_failure_at: "2026-09-29T08:15:00Z",
      last_failure_summary: "Provider unavailable",
    });
    await renderPage();
    expect(screen.getByText(/UAT · https:\/\/uat\.dvla\.example\/vehicle-enquiry/)).toBeInTheDocument();
    expect(screen.getByText(/Last lookup 20 Sept? 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Last failed lookup 29 Sept? 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Provider unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.queryByText(/uat-secret|api-key|apikey/i)).not.toBeInTheDocument();
  });

  it("warns only for the Production DVLA service", async () => {
    mockRoutes(baseSettings(), {}, { enabled: true, configured: true, environment: "Production", health: { state: "Healthy" } });
    await renderPage();
    expect(screen.getByText(/Production DVLA service/)).toBeInTheDocument();
  });

  it("runs the DVLA and DVSA tests with the shared test registration", async () => {
    const user = userEvent.setup();
    mockRoutes(baseSettings(), {}, { enabled: true, configured: true, environment: "UAT", health: { state: "Healthy" } }, {
      enabled: true, deployment_enabled: true, configured: true, environment: "Development", health: { state: "Healthy" },
    });
    post.mockImplementation((path: string) =>
      Promise.resolve({ message: path.includes("dvla") ? "DVLA UAT connection successful." : "DVSA MOT History connection successful." }),
    );
    await renderPage();
    await user.type(screen.getByLabelText("Test reg"), "AB12 CDE");
    await user.click(screen.getByRole("button", { name: "Test DVLA connection" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/integrations/dvla/test", expect.objectContaining({ registration: "AB12 CDE", confirmed: true })));
    expect(await screen.findByText("DVLA UAT connection successful.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test DVSA connection" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/integrations/dvsa/test", expect.objectContaining({ registration: "AB12 CDE", confirmed: true })));
    expect(await screen.findByText("DVSA MOT History connection successful.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).not.toBeInTheDocument();
  });

  it("describes DVSA state with configured/not-configured only and a friendly error category", async () => {
    mockRoutes(baseSettings(), {}, {}, {
      enabled: true,
      deployment_enabled: true,
      configured: true,
      environment: "Development",
      health: { state: "Degraded" },
      last_failure_at: "2026-10-12T09:00:00Z",
      last_failure_category: "rate_limited",
    });
    await renderPage();
    expect(screen.getByText(/credentials configured · Development · Last error: Rate limited/)).toBeInTheDocument();
    expect(screen.queryByText(/client secret|api key value|bearer/i)).not.toBeInTheDocument();
  });

  it("saves the provider toggles through the save bar", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({});
    await renderPage();
    await user.click(screen.getByRole("switch", { name: "Enable DVSA MOT history" }));
    expect(within(saveBar()).getByText("DVSA MOT history")).toBeInTheDocument();
    await user.type(within(saveBar()).getByPlaceholderText(/Reason for change/), "Enable DVSA checks on DEV");
    await user.click(within(saveBar()).getByRole("button", { name: "Save changes" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/settings/driveway_dvsa_enabled", { value: true, reason: "Enable DVSA checks on DEV", confirmed: true }));
  });
});
