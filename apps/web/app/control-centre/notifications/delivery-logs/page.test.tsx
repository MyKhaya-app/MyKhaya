import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NotificationDeliveryLogsPage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/notifications/delivery-logs",
  useRouter: () => stableRouter,
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

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

const entries = [
  {
    id: "d-1",
    occurred_at: "2026-08-20T09:00:00Z",
    notification_type: "event_reminder",
    label: "Event reminder",
    channel: "email",
    status: "failed",
    recipient_email: "megan@example.com",
    sanitised_failure_reason: "SMTP relay timed out",
    retry_count: 2,
    idempotency_key: "abc",
  },
];

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path.startsWith("/communications/diagnostics"))
      return Promise.resolve(overrides.page ?? { items: entries, next_page: null });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NotificationDeliveryLogsPage", () => {
  it("shows the search form before any search has been made, with no results table", async () => {
    mockRoutes();
    render(<NotificationDeliveryLogsPage />);
    await waitFor(() => expect(screen.getByLabelText("Status")).toBeInTheDocument());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("renders delivery log rows safely, without exposing sensitive content", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationDeliveryLogsPage />);
    await waitFor(() => expect(screen.getByLabelText("Status")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByText("Event reminder")).toBeInTheDocument());
    expect(screen.getByText("SMTP relay timed out")).toBeInTheDocument();
    expect(screen.getByText("megan@example.com")).toBeInTheDocument();

    const text = document.body.textContent ?? "";
    expect(text.toLowerCase()).not.toMatch(/verification code|reset[_ ]?token|password|secret|api[_-]?key/);
  });

  it("shows the empty state when no deliveries match the filters", async () => {
    const user = userEvent.setup();
    mockRoutes({ page: { items: [], next_page: null } });
    render(<NotificationDeliveryLogsPage />);
    await waitFor(() => expect(screen.getByLabelText("Status")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No deliveries match those filters.")).toBeInTheDocument();
  });

  it("applies status, channel, type and recipient filters to the request", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationDeliveryLogsPage />);
    await waitFor(() => expect(screen.getByLabelText("Status")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Status"), "failed");
    await user.selectOptions(screen.getByLabelText("Channel"), "email");
    await user.type(screen.getByLabelText("Notification type"), "event_reminder");
    await user.type(screen.getByLabelText("Recipient email"), "megan@example.com");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(get).toHaveBeenCalledWith(
      expect.stringMatching(
        /^\/communications\/diagnostics\?.*status=failed.*channel=email.*notification_type=event_reminder.*recipient_email=megan%40example\.com.*page=1/,
      ),
    ));
  });

  it("loads more results using the returned next_page cursor", async () => {
    const user = userEvent.setup();
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      if (path.startsWith("/communications/diagnostics")) {
        if (path.includes("page=2"))
          return Promise.resolve({ items: [{ ...entries[0], id: "d-2" }], next_page: null });
        return Promise.resolve({ items: entries, next_page: 2 });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    render(<NotificationDeliveryLogsPage />);
    await waitFor(() => expect(screen.getByLabelText("Status")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument());
    expect(screen.getAllByText("Event reminder")).toHaveLength(2);
  });
});
