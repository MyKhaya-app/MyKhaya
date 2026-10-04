import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import MySupportRequests from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/requests",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: { ...actual.api, me: vi.fn(), listSupportTickets: vi.fn() },
  };
});

const { api } = await import("@mykhaya/api-client");

const openTicket = {
  id: "t1",
  reference: "MK-1001",
  type: "bug" as const,
  status: "open" as const,
  priority: "normal" as const,
  subject: "Calendar events disappearing",
  created_at: "2026-09-01T09:00:00Z",
  updated_at: "2026-09-01T09:20:00Z",
  resolved_at: null,
};

const resolvedTicket = {
  ...openTicket,
  id: "t2",
  reference: "MK-1002",
  status: "resolved" as const,
  subject: "Old bug report",
  resolved_at: "2026-09-02T09:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
});

describe("My support requests — list", () => {
  it("shows a loading state before the list resolves", () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(() => {}));
    render(<MySupportRequests />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });

  it("renders the requester's own tickets with reference, subject, status and updated date", async () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [openTicket, resolvedTicket],
    });
    render(<MySupportRequests />);
    await screen.findByText("MK-1001");
    expect(screen.getByText("Calendar events disappearing")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("MK-1002")).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /MK-1001/ });
    expect(link).toHaveAttribute("href", "/help-support/requests/t1");
  });

  it("shows a truthful empty state with actions when there are no requests", async () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    render(<MySupportRequests />);
    expect(await screen.findByText("No support requests yet.")).toBeInTheDocument();
    expect(
      screen.getByText("If you need help, you can report a bug or contact support."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Report a bug" })).toHaveAttribute(
      "href",
      "/help-support/report-bug",
    );
    expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute(
      "href",
      "/help-support/contact-support",
    );
  });

  it("shows a safe error message, not a crash, when the list fails to load", async () => {
    (api.listSupportTickets as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("network down"));
    render(<MySupportRequests />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Support requests are temporarily unavailable. Please try again later.",
    );
  });
});
