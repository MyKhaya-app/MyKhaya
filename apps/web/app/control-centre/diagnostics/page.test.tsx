import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DiagnosticsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/diagnostics",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const entry = {
  id: "d1",
  occurred_at: "2026-09-07T09:00:00Z",
  notification_type: "event_reminder",
  label: "Event reminder",
  channel: "email",
  status: "failed",
  recipient_email: "a@b.com",
  sanitised_failure_reason: "Mailbox full",
  retry_count: 2,
  idempotency_key: "abc",
};

const actor = { id: "op-1", email: "op@mykhaya.app", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" as const };

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    return Promise.resolve({ items: [entry], next_page: null });
  });
});

describe("Diagnostics", () => {
  it("renders search actions before any search is run", () => {
    render(<DiagnosticsPage />);
    expect(screen.getByRole("button", { name: "Search" })).toBeInTheDocument();
  });

  it("sends the exact filter payload as query params on search", async () => {
    render(<DiagnosticsPage />);
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    await userEvent.selectOptions(screen.getByLabelText("Channel"), "email");
    await userEvent.type(screen.getByLabelText("Notification type"), "event_reminder");
    await userEvent.type(screen.getByLabelText("Recipient email"), "a@b.com");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining("/communications/diagnostics?")));
    const calledPath = get.mock.calls.map((call) => call[0] as string).find((path) => path.startsWith("/communications/diagnostics")) as string;
    expect(calledPath).toContain("status=failed");
    expect(calledPath).toContain("channel=email");
    expect(calledPath).toContain("notification_type=event_reminder");
    expect(calledPath).toContain("recipient_email=a%40b.com");
    expect(calledPath).toContain("page=1");
  });

  it("renders result rows after a search", async () => {
    render(<DiagnosticsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Event reminder")).toBeInTheDocument();
    expect(screen.getByText("Mailbox full")).toBeInTheDocument();
  });

  it("shows an empty state when nothing matches the filters", async () => {
    get.mockResolvedValue({ items: [], next_page: null });
    render(<DiagnosticsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No deliveries match those filters.")).toBeInTheDocument();
  });

  it("surfaces a safe error message on a failed search", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.reject(new ApiError(500, "Something went wrong. Please try again."));
    });
    render(<DiagnosticsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
  });
});
