import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { platformApi } from "@mykhaya/api-client";
import { MonitoringPanel } from "./monitoring-panel";

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const component = {
  key: "provider.dvsa.connectivity",
  name: "DVSA MOT History connectivity",
  category: "external",
  provider: "DVSA",
  check_type: "tls",
  verifies: "DNS and TLS only",
  customer_impact: "MOT history may be unavailable",
  services: [{ key: "dvsa_mot_history", name: "DVSA MOT History" }],
  state: "unavailable",
  stored_state: "unavailable",
  confidence: "limited",
  enabled: true,
  interval_seconds: 300,
  timeout_seconds: 10,
  failure_threshold: 3,
  recovery_threshold: 2,
  public_visible: true,
  severity: "critical",
  consecutive_failures: 4,
  consecutive_successes: 0,
  last_attempted_at: "2026-11-09T19:25:00Z",
  last_checked_at: "2026-11-09T19:25:00Z",
  last_success_at: "2026-11-09T19:21:00Z",
  last_failure_at: "2026-11-09T19:25:00Z",
  last_latency_ms: null,
  last_failure_category: "tls",
  last_failure_label: "TLS or certificate failure",
  last_failure_detail: "TLS handshake or certificate validation failed for history.mot.api.gov.uk.",
  state_changed_at: "2026-11-09T19:25:00Z",
  stale_after_seconds: 900,
  simulating_until: null,
  watchdog_managed: false,
  requires_live_validation: true,
};

const overview = {
  environment: "DEV",
  monitoring_enabled: true,
  fault_injection_available: true,
  runner: { active: false, last_cycle_at: "2026-11-09T19:00:00Z", detail: "Monitoring cycle completed" },
  components: [component],
  public_preview: {
    overall: "partial_outage",
    overall_message: "Partial service disruption",
    services: [{ key: "dvsa_mot_history", name: "DVSA MOT History", state: "major_outage", confidence: "limited" }],
  },
  overrides: [],
  recent_transitions: [],
  unacknowledged_alerts: 1,
};

const alerts = {
  items: [
    {
      id: "a1",
      created_at: "2026-11-09T19:25:00Z",
      kind: "unavailable",
      severity: "critical",
      component_key: component.key,
      component_name: component.name,
      incident_id: "i1",
      subject: "[MyKhaya DEV] Service Unavailable: DVSA MOT History",
      summary: "Service: DVSA MOT History",
      suppressed_reason: null,
      recipient_count: 2,
      deliveries: [
        { attempt: "initial", recipient: "admin:1", channel: "email", status: "failed", attempted_at: null, retry_count: 1, failure_reason: "dns_or_connectivity_failure" },
        { attempt: "initial", recipient: "admin:2", channel: "email", status: "sent", attempted_at: null, retry_count: 0, failure_reason: null },
      ],
      acknowledged_at: null,
      acknowledged_by: null,
    },
  ],
};

const settings = {
  enabled: true,
  roles: ["platform_owner", "platform_administrator"],
  additional_recipients: [],
  cooldown_minutes: 30,
  email_warning_severity: true,
  recipient_count: 2,
  receiving_alerts: true,
  can_manage: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/monitoring") return Promise.resolve(overview);
    if (path === "/monitoring/alerts") return Promise.resolve(alerts);
    if (path === "/monitoring/alert-settings") return Promise.resolve(settings);
    return Promise.reject(new Error("unexpected"));
  });
});

describe("Automated monitoring panel", () => {
  it("shows that monitoring itself has stopped", async () => {
    render(<MonitoringPanel />);
    expect(await screen.findByText("Monitoring stopped")).toBeInTheDocument();
  });

  it("lists components with their sanitised failure detail and DEV fault injection", async () => {
    render(<MonitoringPanel />);
    const name = await screen.findByText("DVSA MOT History connectivity");
    const row = name.closest("tr")!;
    expect(within(row).getByText("Unavailable")).toBeInTheDocument();
    expect(within(row).getByText(/TLS or certificate failure/)).toBeInTheDocument();
    expect(within(row).getByText("4/3 consecutive failures")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Simulate failure" })).toBeInTheDocument();
    expect(within(row).queryByText("PCC only: awaiting live validation")).not.toBeInTheDocument();
  });

  it("shows alert delivery outcomes and offers a resend when one failed", async () => {
    render(<MonitoringPanel />);
    expect(await screen.findByText(alerts.items[0]!.subject)).toBeInTheDocument();
    expect(screen.getByText("Email: 1 sent · 1 failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend email" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
  });

  it("shows an active simulation and a state still held by fault injection with Stop simulation", async () => {
    const active = { ...component, simulating_until: "2026-11-09T19:40:00Z" };
    const held = {
      ...component,
      key: "background.outbox",
      name: "Job queue progress",
      simulated_failure_held: true,
    };
    get.mockImplementation((path: string) => {
      if (path === "/monitoring") return Promise.resolve({ ...overview, components: [active, held] });
      if (path === "/monitoring/alerts") return Promise.resolve(alerts);
      return Promise.resolve(settings);
    });
    render(<MonitoringPanel />);
    const activeRow = (await screen.findByText("DVSA MOT History connectivity")).closest("tr")!;
    expect(within(activeRow).getByText(/DEV fault injection active until/)).toBeInTheDocument();
    expect(within(activeRow).getByRole("button", { name: "Stop simulation" })).toBeInTheDocument();
    const heldRow = screen.getByText("Job queue progress").closest("tr")!;
    expect(within(heldRow).getByText(/Held by DEV fault injection/)).toBeInTheDocument();
    expect(within(heldRow).getByRole("button", { name: "Stop simulation" })).toBeInTheDocument();
    expect(within(heldRow).queryByRole("button", { name: "Simulate failure" })).not.toBeInTheDocument();
  });

  it("hides fault injection where the deployment does not allow it", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/monitoring") return Promise.resolve({ ...overview, fault_injection_available: false });
      if (path === "/monitoring/alerts") return Promise.resolve(alerts);
      return Promise.resolve(settings);
    });
    render(<MonitoringPanel />);
    await screen.findByText("DVSA MOT History connectivity");
    expect(screen.queryByRole("button", { name: "Simulate failure" })).not.toBeInTheDocument();
  });

  it("reports monitoring as unavailable for an unrecognised payload", async () => {
    get.mockImplementation(() => Promise.resolve({ overall: "Healthy", services: [] }));
    render(<MonitoringPanel />);
    expect(await screen.findByText("Automated monitoring is unavailable.")).toBeInTheDocument();
  });
});

describe("Automated monitoring panel: live-validation gate", () => {
  it("marks an unvalidated vantage-dependent check as PCC only", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/monitoring")
        return Promise.resolve({ ...overview, components: [{ ...component, public_visible: false }] });
      if (path === "/monitoring/alerts") return Promise.resolve(alerts);
      return Promise.resolve(settings);
    });
    render(<MonitoringPanel />);
    expect(await screen.findByText("PCC only: awaiting live validation")).toBeInTheDocument();
  });
});

describe("Automated monitoring panel: alert recipients", () => {
  it("never shows recipient addresses or the editor to roles that cannot manage them", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/monitoring") return Promise.resolve(overview);
      if (path === "/monitoring/alerts") return Promise.resolve(alerts);
      // The API omits additional_recipients for these roles.
      return Promise.resolve({
        enabled: true,
        roles: settings.roles,
        cooldown_minutes: 30,
        email_warning_severity: true,
        recipient_count: 2,
        receiving_alerts: false,
        can_manage: false,
        additional_recipient_count: 1,
      });
    });
    render(<MonitoringPanel />);
    expect(await screen.findByText("1 additional address(es)")).toBeInTheDocument();
    expect(screen.queryByText(/x@example.com/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("explains commissioning suppression on an alert", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/monitoring") return Promise.resolve(overview);
      if (path === "/monitoring/alerts")
        return Promise.resolve({
          items: [{ ...alerts.items[0]!, suppressed_reason: "awaiting_validation", deliveries: [] }],
        });
      return Promise.resolve(settings);
    });
    render(<MonitoringPanel />);
    expect(
      await screen.findByText("Not emailed: check awaiting live validation (commissioning)"),
    ).toBeInTheDocument();
  });
});
