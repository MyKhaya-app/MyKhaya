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
    api: { ...actual.api, publicSignupState: vi.fn() },
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const { api } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const publicSignupState = api.publicSignupState as unknown as ReturnType<typeof vi.fn>;
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

function baseSettings() {
  return {
    settings: [
      {
        key: "platform_display_name",
        label: "Platform name",
        description: "The name shown for MyKhaya in administrator-facing surfaces.",
        section: "General",
        value_type: "text",
        risk: "normal",
        runtime_effect: "informational",
        editable: true,
        consumer_visible: false,
        value: null,
        state: "unset",
      },
      {
        key: "service_status_url",
        label: "Service status page",
        description: "The page consumers are sent to from Help & Support to check MyKhaya's status.",
        section: "Support",
        value_type: "url",
        risk: "normal",
        runtime_effect: "effective",
        editable: true,
        consumer_visible: true,
        value: "https://status.dev.mykhaya.app/",
        state: "default",
      },
      {
        key: "maintenance_mode",
        label: "Maintenance mode",
        description: "Take MyKhaya offline for maintenance.",
        section: "General",
        value_type: "boolean",
        risk: "sensitive",
        runtime_effect: "not_enforced",
        editable: true,
        consumer_visible: false,
        value: false,
        state: "unset",
      },
    ],
    environment: [
      { key: "public_url", value: "https://dev.mykhaya.app", category: "environment_controlled", editable: false },
    ],
  };
}

function mockRoutes(
  settings = baseSettings(),
  syslogOverrides: Record<string, unknown> = {},
  dvlaOverrides: Record<string, unknown> = {},
) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/settings") return Promise.resolve(settings);
    if (path === "/public/signup-state") return Promise.resolve({
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
    if (path === "/logging/syslog") return Promise.resolve({ enabled: false, configured: false, host: "", port: 6514, protocol: "tls", facility: 16, environment: "test", tls_verify: true, minimum_level: "INFO", categories: ["application", "http", "security", "audit", "worker", "integration"], last_successful_delivery: null, last_error: null, dropped_count: 0, ...syslogOverrides });
    if (path === "/logging/syslog/diagnostics") return Promise.resolve({ events_seen: 0, events_queued: 0, events_sent: 0, events_filtered: 0, events_category_filtered: 0, events_dropped: 0, transport_failures: 0 });
    throw new Error(`Unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  publicSignupState.mockResolvedValue({
    signup_mode: "normal",
    registration_open: true,
    invitation_required: false,
    normal_signup_available: true,
    beta_joining_available: false,
    waitlist_available: false,
    joinable_count: 0,
  });
  mockRoutes();
});

afterEach(() => {
  // clearAllMocks (not restoreAllMocks) deliberately preserves each
  // mock's implementation across tests -- PlatformShell/AppShell's own
  // unawaited background auth-refresh effect can still be in flight when
  // this fires, and restoring to a bare no-op vi.fn() made it crash with
  // "Cannot read properties of undefined (reading 'then')" on whichever
  // test happened to be running when it finally settled.
  vi.clearAllMocks();
});

describe("PCC Settings — friendly labels, not raw keys", () => {
  it("renders friendly labels as the primary heading, with the key only as secondary text", async () => {
    render(<PlatformSettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Platform name" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("platform_display_name")).toBeInTheDocument();
  });

  it("groups settings under section headings", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Support" })).toBeInTheDocument();
  });
});

describe("PCC Settings — value/state rendering, never Unavailable", () => {
  it("shows a default-sourced value with the 'Using deployment default' caption", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Service status page" });
    expect(screen.getByDisplayValue("https://status.dev.mykhaya.app/")).toBeInTheDocument();
    expect(screen.getByText("Using deployment default")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("shows an unset value as an empty field with neutral placeholder copy", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    const input = screen.getByPlaceholderText("Not yet set");
    expect(input).toHaveValue("");
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("shows a not_enforced caption without claiming an operational effect", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Maintenance mode" });
    expect(screen.getByText("Not yet enforced by the application.")).toBeInTheDocument();
  });
});

describe("PCC Settings — saving a normal setting", () => {
  it("saves exactly one key/value/reason via PUT and shows the configured caption after reload", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ key: "platform_display_name", value: "MyKhaya", risk: "normal" });
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    const row = (await screen.findByRole("heading", { name: "Platform name" })).closest(
      ".setting-row",
    ) as HTMLElement;
    const input = within(row).getByPlaceholderText("Not yet set");
    await user.type(input, "MyKhaya");
    await user.type(within(row).getByLabelText("Reason for this change"), "Setting the platform name.");

    mockRoutes({
      ...baseSettings(),
      settings: baseSettings().settings.map((item) =>
        item.key === "platform_display_name"
          ? { ...item, value: "MyKhaya", state: "configured" }
          : item,
      ),
    });

    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/settings/platform_display_name", {
        value: "MyKhaya",
        reason: "Setting the platform name.",
        confirmed: true,
      }),
    );
    await within(row).findByText("Configured in Platform Control Centre");
  });

  it("surfaces a validation error from a rejected save without clearing the field", async () => {
    const user = userEvent.setup();
    put.mockRejectedValue(new Error("That must be a valid http(s) URL."));
    render(<PlatformSettingsPage />);

    const row = (await screen.findByRole("heading", { name: "Service status page" })).closest(
      ".setting-row",
    ) as HTMLElement;
    // A native <input type="url"> already blocks browser submission for a
    // syntactically-invalid URL like "not-a-url" before this component's own
    // onSubmit ever runs — using a value that *is* syntactically valid HTML5
    // URL syntax (so it reaches our submit handler / the mocked PUT) but
    // that the server's stricter scheme check rejects is what actually
    // exercises the server-validation-error rendering path this test cares
    // about.
    const urlInput = within(row).getByDisplayValue("https://status.dev.mykhaya.app/");
    fireEvent.change(urlInput, { target: { value: "ftp://status.example.com" } });
    await user.type(within(row).getByLabelText("Reason for this change"), "Testing a bad URL.");

    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(put).toHaveBeenCalled());
    await within(row).findByText("That must be a valid http(s) URL.");
    expect(urlInput).toHaveValue("ftp://status.example.com");
  });
});

describe("PCC Settings — central logging", () => {
  it("sends only the backend configuration contract when saving", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ enabled: true, configured: true, host: "graylog.internal", port: 6514, protocol: "tls", facility: 16, environment: "test", tls_verify: true, minimum_level: "INFO", categories: ["application", "http", "security", "audit", "worker", "integration"], last_successful_delivery: null, last_error: null, dropped_count: 0 });
    render(<PlatformSettingsPage />);

    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    await user.click(within(card).getByLabelText("Enabled"));
    await user.type(within(card).getByLabelText("Host"), "graylog.internal");
    await user.type(within(card).getByLabelText("Reason for this change"), "Enable central logging safely");
    await user.click(within(card).getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(put).toHaveBeenCalledWith("/logging/syslog", {
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
    }));
    const savedPayload = put.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(savedPayload).not.toHaveProperty("configured");
    expect(savedPayload).not.toHaveProperty("dropped_count");
  });

  it("shows field validation and does not submit an enabled configuration without a host", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);

    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    await user.click(within(card).getByLabelText("Enabled"));
    await user.type(within(card).getByLabelText("Reason for this change"), "Enable central logging safely");
    await user.click(within(card).getByRole("button", { name: "Save settings" }));

    expect(put).not.toHaveBeenCalled();
    expect(screen.getByText("Host is required when central logging is enabled.")).toBeInTheDocument();
  });

  it("keeps test message disabled until an enabled configuration is saved", async () => {
    render(<PlatformSettingsPage />);
    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    expect(within(card).getByRole("button", { name: "Send test message" })).toBeDisabled();
    const statusGrid = card.querySelector(".central-logging-status-grid");
    expect(statusGrid).toBeInTheDocument();
    expect(within(statusGrid as HTMLElement).getByText("None").parentElement).toHaveClass("cc-metadata-item-span");
  });

  it("saves the selected minimum level and disables TLS verification for UDP", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ enabled: false, configured: false, host: "", port: 6514, protocol: "udp", facility: 16, environment: "test", tls_verify: true, minimum_level: "WARNING", last_successful_delivery: null, last_error: null, dropped_count: 0 });
    render(<PlatformSettingsPage />);

    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    await user.selectOptions(within(card).getByLabelText("Minimum log level"), "WARNING");
    await user.selectOptions(within(card).getByLabelText("Protocol"), "udp");
    expect(within(card).getByLabelText("Verify TLS certificate")).toBeDisabled();
    await user.type(within(card).getByLabelText("Reason for this change"), "Adjust remote filtering safely");
    await user.click(within(card).getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(put).toHaveBeenCalledWith("/logging/syslog", expect.objectContaining({ minimum_level: "WARNING", protocol: "udp" })));
  });

  it("saves category selections and clearly explains an empty selection", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ enabled: true, configured: true, host: "graylog.internal", port: 6514, protocol: "tls", facility: 16, environment: "test", tls_verify: true, minimum_level: "INFO", categories: ["http"], last_successful_delivery: null, last_error: null, dropped_count: 0 });
    mockRoutes(baseSettings(), { enabled: true, configured: true, host: "graylog.internal", categories: ["application", "http", "security", "audit", "worker", "integration"] });
    render(<PlatformSettingsPage />);

    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    await user.click(within(card).getByLabelText("Application"));
    await user.click(within(card).getByLabelText("HTTP / API Requests"));
    await user.click(within(card).getByLabelText("Security & Authentication"));
    await user.click(within(card).getByLabelText("Audit"));
    await user.click(within(card).getByLabelText("Workers & Scheduler"));
    await user.click(within(card).getByLabelText("External Integrations"));
    expect(within(card).getByText("Central Logging remains enabled, but no normal application events will be forwarded.")).toBeInTheDocument();
    await user.type(within(card).getByLabelText("Reason for this change"), "Disable normal remote categories");
    await user.click(within(card).getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(put).toHaveBeenCalledWith("/logging/syslog", expect.objectContaining({ categories: [] })));
  });

  it("renders last delivery as a local human-readable timestamp", async () => {
    mockRoutes(baseSettings(), { last_successful_delivery: "2026-09-28T18:30:20.818411+00:00" });
    render(<PlatformSettingsPage />);
    const card = (await screen.findByRole("heading", { name: "Central logging" })).closest(".cc-card") as HTMLElement;
    expect(within(card).queryByText("2026-09-28T18:30:20.818411+00:00")).not.toBeInTheDocument();
    expect(within(card).getByText(/28 Sept? 2026/)).toBeInTheDocument();
  });
});

describe("PCC Settings — sensitive settings require confirmation", () => {
  it("opens CcConfirmDialog instead of saving directly when a sensitive value changes", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);

    const row = (await screen.findByRole("heading", { name: "Maintenance mode" })).closest(
      ".setting-row",
    ) as HTMLElement;
    await user.click(within(row).getByRole("checkbox"));
    await user.click(within(row).getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/does not currently change user access or behaviour/i)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });
});

describe("PCC Settings — Driveway/DVLA integration", () => {
  function driveawayCard() {
    return screen.findByRole("heading", { name: "Driveway integrations" }).then(
      (heading) => heading.closest(".cc-card") as HTMLElement,
    );
  }

  it("shows Not configured and disables Test connection when no environment is selected", async () => {
    mockRoutes();
    render(<PlatformSettingsPage />);
    const card = await driveawayCard();
    expect(within(card).getAllByText("Not configured").length).toBeGreaterThan(0);
    expect(within(card).getByRole("button", { name: "Test connection" })).toBeDisabled();
  });

  it("shows the friendly UAT label, endpoint, and never renders the API key", async () => {
    mockRoutes(baseSettings(), {}, {
      enabled: true,
      configured: true,
      environment: "UAT",
      endpoint: "https://uat.dvla.example/vehicle-enquiry",
      health: { state: "Healthy" },
    });
    render(<PlatformSettingsPage />);
    const card = await driveawayCard();
    expect(within(card).getByText("UAT")).toBeInTheDocument();
    expect(within(card).getByText("https://uat.dvla.example/vehicle-enquiry")).toBeInTheDocument();
    expect(screen.queryByText(/uat-secret|api-key|apikey/i)).not.toBeInTheDocument();
  });

  it("shows a Production warning notice only when the active environment is Production", async () => {
    mockRoutes(baseSettings(), {}, {
      enabled: true,
      configured: true,
      environment: "Production",
      endpoint: "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
      health: { state: "Healthy" },
    });
    render(<PlatformSettingsPage />);
    const card = await driveawayCard();
    expect(within(card).getByText(/Production DVLA service/)).toBeInTheDocument();
  });

  it("shows last successful and failed lookup timestamps when available", async () => {
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
    render(<PlatformSettingsPage />);
    const card = await driveawayCard();
    expect(within(card).getByText(/20 Sept? 2026/)).toBeInTheDocument();
    expect(within(card).getByText(/29 Sept? 2026/)).toBeInTheDocument();
    expect(within(card).getByText("Provider unavailable")).toBeInTheDocument();
  });

  it("runs the test connection using the entered registration and shows the result", async () => {
    const user = userEvent.setup();
    mockRoutes(baseSettings(), {}, {
      enabled: true,
      configured: true,
      environment: "UAT",
      endpoint: "https://uat.dvla.example/vehicle-enquiry",
      health: { state: "Healthy" },
    });
    post.mockResolvedValue({ state: "Healthy", message: "DVLA UAT connection successful." });
    render(<PlatformSettingsPage />);
    const card = await driveawayCard();
    await user.type(within(card).getByLabelText("Test registration"), "AB12 CDE");
    await user.click(within(card).getByRole("button", { name: "Test connection" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/integrations/dvla/test",
        expect.objectContaining({ registration: "AB12 CDE", confirmed: true }),
      ),
    );
    expect(await within(card).findByText("DVLA UAT connection successful.")).toBeInTheDocument();
  });
});

describe("PCC Settings — enforced access controls", () => {
  function enforcedSettings() {
    const base = baseSettings();
    const registration = ["registration_enabled", "invite_only_mode"].map((key) => ({
      key,
      label: key === "registration_enabled" ? "Allow any new registrations" : "Invitation-only access",
      description: "Server-enforced signup control.",
      section: "Registration & Access",
      value_type: "boolean",
      risk: "sensitive",
      runtime_effect: "effective",
      editable: true,
      consumer_visible: false,
      value: key === "registration_enabled",
      state: "unset",
    }));
    return {
      ...base,
      settings: [
        ...base.settings.map((item) =>
          item.key === "maintenance_mode" ? { ...item, runtime_effect: "effective" } : item,
        ),
        ...registration,
      ],
    };
  }

  it("shows no 'not enforced' warning for a setting the server enforces", async () => {
    mockRoutes(enforcedSettings());
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Maintenance mode" });
    expect(screen.queryByText("Not yet enforced by the application.")).not.toBeInTheDocument();
  });

  it("lists the registration controls and warns about real access effects when saving", async () => {
    const user = userEvent.setup();
    mockRoutes(enforcedSettings());
    render(<PlatformSettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Allow any new registrations" });
    expect(screen.getByRole("heading", { name: "Invitation-only access" })).toBeInTheDocument();
    const row = heading.closest(".setting-row") as HTMLElement;
    await user.click(within(row).getByRole("checkbox"));
    await user.click(within(row).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(/affects real user access or availability/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/not yet enforced/i)).not.toBeInTheDocument();
  });

  it("shows effective registration summary and keeps email verification read-only", async () => {
    const settings = enforcedSettings();
    settings.settings.push({
      key: "email_verification_required",
      label: "Require email verification",
      description: "Deployment safeguard.",
      section: "Registration & Access",
      value_type: "boolean",
      risk: "sensitive",
      runtime_effect: "effective",
      editable: true,
      consumer_visible: false,
      value: true,
      state: "default",
    });
    mockRoutes(settings);
    render(<PlatformSettingsPage />);

    expect(await screen.findByRole("heading", { name: "Effective registration behaviour" })).toBeInTheDocument();
    expect(screen.getByText("Existing user sign-in")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Email verification" })).toBeInTheDocument();
    expect(screen.getByText("Managed by deployment policy. Production cannot turn this safeguard off from PCC.")).toBeInTheDocument();
    const verificationHeading = screen.getByRole("heading", { name: "Email verification" });
    expect(within(verificationHeading.closest(".cc-card") as HTMLElement).queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
  });
});
