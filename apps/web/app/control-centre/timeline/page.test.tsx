import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TimelinePage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/timeline",
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

const entryOne = {
  id: "t1",
  occurred_at: "2026-09-07T09:00:00Z",
  notification_type: "event_reminder",
  label: "Event reminder sent",
  channel: "email",
  status: "sent",
  friendly_status: "Delivered",
  recipient_display_name: "Jane Doe",
  retry_count: 0,
};
const entryTwo = {
  ...entryOne,
  id: "t2",
  occurred_at: "2026-09-07T08:00:00Z",
  label: "Push reminder failed",
  status: "failed",
  friendly_status: "Failed",
  recipient_display_name: null,
};

const actor = { id: "op-1", email: "op@mykhaya.app", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" as const };

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    return Promise.resolve({ items: [entryOne, entryTwo], next_page: null });
  });
});

describe("Timeline", () => {
  it("renders entries in the order returned by the API with status badges", async () => {
    render(<TimelinePage />);
    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Event reminder sent");
    expect(items[1]).toHaveTextContent("Push reminder failed");
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been sent", async () => {
    get.mockResolvedValue({ items: [], next_page: null });
    render(<TimelinePage />);
    expect(await screen.findByText("Nothing has been sent yet.")).toBeInTheDocument();
  });

  it("loads more entries via the next_page cursor and appends them", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      if (path === "/communications/timeline?page=2") return Promise.resolve({ items: [entryTwo], next_page: null });
      return Promise.resolve({ items: [entryOne], next_page: 2 });
    });
    render(<TimelinePage />);
    await screen.findByText("Event reminder sent");
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/communications/timeline?page=2"));
    expect(await screen.findByText("Push reminder failed")).toBeInTheDocument();
    expect(screen.getByText("Event reminder sent")).toBeInTheDocument();
  });

  it("surfaces a safe error message on a failed load", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(actor);
      return Promise.reject(new ApiError(500, "Something went wrong. Please try again."));
    });
    render(<TimelinePage />);
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
  });
});
