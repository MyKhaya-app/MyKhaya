import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import ServiceStatus from "./page";

// Coverage for the public Status page's Billing & Subscriptions service,
// incident-driven overall banner wording, current-incident timelines and
// resolved-incident Recent history — see mykhaya.status_aggregation and
// mykhaya.routers.status for the backend this renders.

function jsonResponse(body: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  } as Response);
}

function baseServices(overrides: Record<string, string> = {}) {
  const keys = [
    "web_application",
    "authentication",
    "api",
    "email_delivery",
    "notifications",
    "background_processing",
    "billing",
  ];
  const names: Record<string, string> = {
    web_application: "MyKhaya Web Application",
    authentication: "Authentication",
    api: "API",
    email_delivery: "Email Delivery",
    notifications: "Notifications",
    background_processing: "Background Processing",
    billing: "Billing & Subscriptions",
  };
  return keys.map((key) => ({ key, name: names[key], state: overrides[key] ?? "operational" }));
}

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("Public Status page — Billing & Subscriptions service", () => {
  it("shows Billing & Subscriptions among the monitored services", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "operational",
        overall_message: "Operational",
        last_updated: "2026-01-01T00:00:00Z",
        services: baseServices(),
        current_incidents: [],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    expect(await screen.findByText("Billing & Subscriptions")).toBeInTheDocument();
  });
});

describe("Public Status page — overall banner wording", () => {
  it("shows plain Operational with no current incidents when nothing is affected", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "operational",
        overall_message: "Operational",
        last_updated: "2026-01-01T00:00:00Z",
        services: baseServices(),
        current_incidents: [],
        recent_incidents: [],
      }),
    );

    const { container } = render(<ServiceStatus />);

    await screen.findByText("No current incidents.");
    const banner = container.querySelector(".status-banner");
    expect(banner).not.toBeNull();
    expect(within(banner!).getByText("Operational")).toBeInTheDocument();
  });

  it("shows the degraded wording when a service is degraded", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "degraded_performance",
        overall_message: "Some systems are experiencing degraded performance",
        last_updated: "2026-01-01T00:00:00Z",
        services: baseServices({ billing: "degraded_performance" }),
        current_incidents: [],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    expect(
      await screen.findByText("Some systems are experiencing degraded performance"),
    ).toBeInTheDocument();
  });

  it("shows the major outage wording for a major outage", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "major_outage",
        overall_message: "Major service disruption",
        last_updated: "2026-01-01T00:00:00Z",
        services: baseServices({ billing: "major_outage" }),
        current_incidents: [],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    expect(await screen.findByText("Major service disruption")).toBeInTheDocument();
  });
});

describe("Public Status page — current incidents", () => {
  it("renders an active incident's affected services and update timeline", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "partial_outage",
        overall_message: "Partial service disruption",
        last_updated: "2026-01-01T16:03:00Z",
        services: baseServices({ billing: "partial_outage" }),
        current_incidents: [
          {
            id: "incident-1",
            title: "Problems processing Family subscription purchases",
            lifecycle_state: "monitoring",
            services: [{ key: "billing", name: "Billing & Subscriptions", impact: "partial_outage" }],
            started_at: "2026-01-01T15:00:00Z",
            resolved_at: null,
            updates: [
              {
                lifecycle_state: "investigating",
                message: "We are investigating reports of users being unable to complete purchases.",
                occurred_at: "2026-01-01T15:04:00Z",
              },
              {
                lifecycle_state: "identified",
                message: "The issue has been identified and a fix is being deployed.",
                occurred_at: "2026-01-01T15:22:00Z",
              },
            ],
          },
        ],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    expect(
      await screen.findByText("Problems processing Family subscription purchases"),
    ).toBeInTheDocument();
    expect(screen.getByText("Monitoring")).toBeInTheDocument();
    expect(screen.getByText(/Billing & Subscriptions — Partial Outage/)).toBeInTheDocument();
    expect(
      screen.getByText("We are investigating reports of users being unable to complete purchases."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The issue has been identified and a fix is being deployed."),
    ).toBeInTheDocument();
  });

  it("never renders internal-only fields for an incident", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "partial_outage",
        overall_message: "Partial service disruption",
        last_updated: "2026-01-01T16:03:00Z",
        services: baseServices({ billing: "partial_outage" }),
        current_incidents: [
          {
            id: "incident-1",
            title: "Billing incident",
            lifecycle_state: "investigating",
            services: [{ key: "billing", name: "Billing & Subscriptions", impact: "partial_outage" }],
            started_at: "2026-01-01T15:00:00Z",
            resolved_at: null,
            updates: [],
          },
        ],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    await screen.findByText("Billing incident");
    expect(screen.queryByText(/internal/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk_live/i)).not.toBeInTheDocument();
  });
});

describe("Public Status page — recent history", () => {
  it("shows a resolved incident's duration and full timeline when expanded", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "operational",
        overall_message: "Operational",
        last_updated: "2026-01-01T16:03:00Z",
        services: baseServices(),
        current_incidents: [],
        recent_incidents: [
          {
            id: "incident-2",
            title: "Billing services have returned to normal",
            lifecycle_state: "resolved",
            services: [{ key: "billing", name: "Billing & Subscriptions", impact: "major_outage" }],
            started_at: "2026-01-01T15:04:00Z",
            resolved_at: "2026-01-01T16:03:00Z",
            duration_seconds: 3540,
            updates: [
              {
                lifecycle_state: "investigating",
                message: "We are investigating reports of failed purchases.",
                occurred_at: "2026-01-01T15:04:00Z",
              },
              {
                lifecycle_state: "resolved",
                message: "Billing services have returned to normal.",
                occurred_at: "2026-01-01T16:03:00Z",
              },
            ],
          },
        ],
      }),
    );

    render(<ServiceStatus />);

    const summary = await screen.findByText("Billing services have returned to normal");
    expect(within(summary.closest("details")!).getByText(/Resolved after 59m/)).toBeInTheDocument();
    expect(
      screen.getByText("Billing services have returned to normal.", { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("shows the no-incidents message when history is empty", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        overall: "operational",
        overall_message: "Operational",
        last_updated: "2026-01-01T00:00:00Z",
        services: baseServices(),
        current_incidents: [],
        recent_incidents: [],
      }),
    );

    render(<ServiceStatus />);

    await waitFor(() =>
      expect(screen.getByText("No incidents reported in the last 90 days.")).toBeInTheDocument(),
    );
  });
});
